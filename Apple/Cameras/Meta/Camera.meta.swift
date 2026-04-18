//
//  Camera.meta.swift
//  MEyes
//
//  Created by Bruno Pinto on 25/02/2026.
//

import CoreImage
import MWDATCore
import MWDATCamera
internal import UIKit

// MARK: - FrameGate

/// Thread-safe gate that allows only one frame through at a time.
/// While a frame is being processed, all subsequent frames are discarded.
private nonisolated final class FrameGate: @unchecked Sendable {
  private var processing = false
  private let lock = NSLock()

  /// Returns `true` if no frame is currently being processed,
  /// and atomically marks the gate as busy.
  func tryEnter() -> Bool {
    lock.lock()
    defer { lock.unlock() }
    guard !processing else { return false }
    processing = true
    return true
  }

  func leave() {
    lock.lock()
    processing = false
    lock.unlock()
  }

  func reset() {
    lock.lock()
    processing = false
    lock.unlock()
  }
}

// MARK: - CameraMeta

public actor CameraMeta: Camera {
  public private(set) var state: CameraState = .disconnected(.notInit)
  public let name: String
  public let zoom: String = ""

  private let wearables: WearablesInterface
  private var stateContinuations: [AsyncStream<CameraState>.Continuation] = []

  // SDK session objects
  private var deviceSession: DeviceSession?
  private var streamSession: StreamSession?

  // Listener tokens
  private var deviceStateToken: (any AnyListenerToken)?
  private var deviceErrorToken: (any AnyListenerToken)?
  private var streamStateToken: (any AnyListenerToken)?
  private var videoToken: (any AnyListenerToken)?
  private var streamErrorToken: (any AnyListenerToken)?

  /// Discards incoming frames while one is still being processed downstream.
  private let frameGate = FrameGate()

  init(deviceId: DeviceIdentifier, wearables: WearablesInterface) {
    self.wearables = wearables
    self.name = wearables
      .deviceForIdentifier(deviceId)?
      .nameOrId() ?? String(localized: "Unnamed Meta Wearable")
  }

  // MARK: - Connect

  public func connect(nextFrame: @escaping (CIImage) -> Void) async {
    switch state {
      case
          .connected,
          .connecting,
          .disconnecting,
          .started,
          .starting,
          .stopped,
          .stopping,
          .forceDisconnect:
        return
      case .disconnected:
        break
    }
    setState(.connecting)

    // 1 — Check / request camera permission.
    do {
      let status = try await wearables.checkPermissionStatus(.camera)
      if status != .granted {
        let granted = try await wearables.requestPermission(.camera)
        guard granted == .granted else {
          setState(.disconnected(.noPermissions))
          return
        }
      }
    } catch {
      setState(.disconnected(.noPermissions))
      return
    }

    // 2 — Create a DeviceSession.
    let selector = AutoDeviceSelector(wearables: wearables)
    let session: DeviceSession
    do {
      session = try wearables.createSession(deviceSelector: selector)
    } catch {
      print("[CameraMeta] createSession failed: \(error)")
      setState(.disconnected(.noSession))
      return
    }
    self.deviceSession = session

    // 3 — Observe device session state + errors.
    deviceStateToken = session.statePublisher.listen { [weak self] sdkState in
      Task { [weak self] in
        await self?.handleDeviceSessionState(sdkState)
      }
    }
    deviceErrorToken = session.errorPublisher.listen { [weak self] sdkError in
      Task { [weak self] in
        print("[CameraMeta] DeviceSession error: \(sdkError)")
        await self?.forceDisconnect()
      }
    }

    // 4 — Start the device session (synchronous, throws).
    do {
      try session.start()
    } catch {
      print("[CameraMeta] DeviceSession.start() failed: \(error)")
      await cancelAllTokens()
      deviceSession = nil
      setState(.disconnected(.noSession))
      return
    }

    // 5 — Add the stream capability.
    let config = StreamSessionConfig(
      videoCodec: .raw,
      resolution: .high,
      frameRate: 30
    )
    let stream: StreamSession?
    do {
      stream = try session.addStream(config: config)
    } catch {
      print("[CameraMeta] addStream failed: \(error)")
      session.stop()
      await cancelAllTokens()
      deviceSession = nil
      setState(.disconnected(.noSession))
      return
    }
    guard let stream else {
      print("[CameraMeta] addStream returned nil")
      session.stop()
      await cancelAllTokens()
      deviceSession = nil
      setState(.disconnected(.noSession))
      return
    }
    self.streamSession = stream

    // 6 — Observe stream state, frames, and errors.
    streamStateToken = stream.statePublisher.listen { [weak self] sdkState in
      Task { [weak self] in
        await self?.handleStreamSessionState(sdkState)
      }
    }
    let gate = self.frameGate
    videoToken = stream.videoFramePublisher.listen { videoFrame in
      guard gate.tryEnter() else { return }
      guard
        let image = videoFrame.makeUIImage(),
        let ciImage = CIImage(image: image)
      else {
        gate.leave()
        return
      }
      nextFrame(ciImage)
      gate.leave()
    }
    streamErrorToken = stream.errorPublisher.listen { [weak self] sdkError in
      Task { [weak self] in
        print("[CameraMeta] StreamSession error: \(sdkError)")
        await self?.forceDisconnect()
      }
    }

    setState(.connected)
  }

  // MARK: - Disconnect

  public func disconnect() async {
    switch state {
      case
          .connecting,
          .disconnecting,
          .starting,
          .stopping,
          .disconnected:
        return
      case .started:
        await stop()
      case
          .forceDisconnect,
          .stopped,
          .connected:
        break
    }
    setState(.disconnecting)
    await teardown()
    setState(.disconnected(nil))
  }

  // MARK: - Start

  public func start() async {
    switch state {
      case
          .connecting,
          .disconnecting,
          .starting,
          .stopping,
          .disconnected(_),
          .forceDisconnect,
          .started:
        return
      case
          .connected,
          .stopped:
        break
    }
    setState(.starting)
    guard let streamSession else {
      setState(.disconnected(.noSession))
      return
    }
    await streamSession.start()
    setState(.started)
  }

  // MARK: - Stop

  public func stop() async {
    switch state {
      case
          .connecting,
          .disconnecting,
          .starting,
          .stopping,
          .disconnected(_),
          .forceDisconnect,
          .stopped,
          .connected:
        return
      case .started:
        break
    }
    setState(.stopping)
    await streamSession?.stop()
    setState(.stopped)
  }

  // MARK: - SDK State Handling

  private func handleDeviceSessionState(_ sdkState: DeviceSessionState) async {
    switch sdkState {
      case .started:
        // Device is ready — no action needed, stream handles its own state.
        break
      case .paused:
        // Device-initiated pause (e.g. cap-touch).
        if state == .started {
          setState(.stopped)
        }
      case .stopped:
        // Device session ended — must tear down and create a new one.
        await forceDisconnect()
      case .idle, .starting, .stopping:
        break
    }
  }

  private func handleStreamSessionState(_ sdkState: StreamSessionState) async {
    switch sdkState {
      case .streaming:
        if state == .starting { return }
        setState(.started)
      case .stopped, .paused:
        if state == .started || state == .starting {
          setState(.stopped)
        }
      case .waitingForDevice, .starting, .stopping:
        break
    }
  }

  // MARK: - Teardown

  private func forceDisconnect() async {
    state = .forceDisconnect
    await disconnect()
  }

  private func teardown() async {
    await cancelAllTokens()
    await streamSession?.stop()
    streamSession = nil
    deviceSession?.stop()
    deviceSession = nil
    frameGate.reset()
  }

  private func cancelAllTokens() async {
    await deviceStateToken?.cancel()
    await deviceErrorToken?.cancel()
    await streamStateToken?.cancel()
    await videoToken?.cancel()
    await streamErrorToken?.cancel()
    deviceStateToken = nil
    deviceErrorToken = nil
    streamStateToken = nil
    videoToken = nil
    streamErrorToken = nil
  }
}

// MARK: - Publisher

public extension CameraMeta {
  func stateUpdates() -> AsyncStream<CameraState> {
    AsyncStream { cont in
      stateContinuations.append(cont)
      cont.yield(state)
    }
  }

  private func setState(_ newState: CameraState) {
    state = newState
    stateContinuations.forEach { $0.yield(newState) }
  }
}
