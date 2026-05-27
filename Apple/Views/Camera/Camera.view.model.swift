//
//  Camera.view.model.swift
//  MEyes
//
//  Created by Bruno Pinto on 27/02/2026.
//

import SwiftUI
internal import Combine
import AVFoundation
import CoreImage

/// Describes what the camera view should display in its action area.
enum CameraAction {
  /// An interactive button the user can tap.
  case button(icon: String, label: String, hint: String)
  /// A non-interactive status message (with a spinner).
  case status(message: String)
}

@MainActor
class CameraViewModel: ObservableObject {
  @Published var camera: CameraSnapshot
  @Published var state: CameraState = .disconnected(.notInit)
  @Published var action: CameraAction = .status(message: "Initializing")
  
  private var stateTask: Task<Void, Never>?
  private let tracker: BusApproachTracker?
  private let speaker = Speaker()
  private var busy: Bool = false
  
  private var seenBusIDs: Set<String> = []

  #if DevDebug
  private var frameSaver: DebugFrameSaver?
  private var lastFrameTime: CFAbsoluteTime = 0
  private var currentFPS: Double = 0
  private var lastTiming: BusApproachTracker.TimingInfo?
  #endif
  
  init(camera: CameraSnapshot) {
    self.camera = camera

    let stage1 = try? YOLOModel(.bundle(name: "yolo26sINT8512x896"))
    self.tracker = BusApproachTracker(model: stage1)
  }
  
  func processFrame(_ frame: CIImage) async {
    guard !self.busy else {
      return
    }
    guard let tracker else { return }
    self.busy = true

    #if DevDebug
    // FPS calculation
    let now = CFAbsoluteTimeGetCurrent()
    if lastFrameTime > 0 {
      let delta = now - lastFrameTime
      if delta > 0 { currentFPS = 1.0 / delta }
    }
    lastFrameTime = now
    #endif

    do {
      let (results, timing) = try await tracker.processFrame(frame)

      #if DevDebug
      lastTiming = timing
      #endif

      // Announce newly seen buses.
      var newBuses: [String] = []
      for bus in results {
        if seenBusIDs.insert(bus.id).inserted {
          newBuses.append(bus.id)
        }
      }

      let spokenString = newBuses.joined(separator: ". ")
      if !spokenString.isEmpty {
        speaker.speak(spokenString)
      }
      
      #if DevDebug
      frameSaver?.appendFrame(
        frame,
        timing: lastTiming,
        currentFPS: currentFPS,
        busResults: results,
        spokenString: spokenString
      )
      #endif
    } catch {
      print("[CameraViewModel] processFrame error: \(error)")
    }
    
    self.busy = false
  }
  
  func performAction() async {
    guard let device = camera.device else {
      switch state {
        case .disconnected(_):
          break
        default:
          state = .disconnected(.notInit)
      }
      return
    }
    
    switch state {
      case .connected, .stopped:
        await device.start()
      case .started:
        await device.stop()
      default:
        break
    }
  }

  #if DevDebug
  // MARK: - Debug: Frame Recording

  private func startRecording() {
    lastFrameTime = 0
    currentFPS = 0
    lastTiming = nil
    frameSaver = DebugFrameSaver()
    frameSaver?.start()
  }

  private func stopRecording() {
    frameSaver?.stop()
    frameSaver = nil
  }

  #endif
  
  func startObservingState() async {
    guard let camera = self.camera.device else { return }
    stateTask?.cancel()
    stateTask = Task { [weak self] in
      guard let self else { return }
      for await state in await camera.stateUpdates() {
        self.state = state
        self.action = self.actionForState(state)
        #if DevDebug
        switch state {
          case .started:
            startRecording()
          default:
            stopRecording()
        }
        #endif
      }
    }
  }

  func stopObservingState() {
    stateTask?.cancel()
    stateTask = nil
  }

  // MARK: - Private
  
  private func actionForState(_ state: CameraState) -> CameraAction {
    if camera.isRegistration {
      return actionForRegistrationState(state)
    }
    return actionForCameraState(state)
  }

  private func actionForCameraState(_ state: CameraState) -> CameraAction {
    switch state {
      case .connected, .stopped:
        return .button(
          icon: "play.fill",
          label: String(localized: "Start"),
          hint: String(localized: "Start using camera")
        )
      case .started:
        return .button(
          icon: "stop.fill",
          label: String(localized: "Stop"),
          hint: String(localized: "Stop using camera")
        )
      case .connecting:
        return .status(message: String(localized: "Connecting to camera"))
      case .starting:
        return .status(message: String(localized: "Starting camera feed"))
      case .stopping:
        return .status(message: String(localized: "Stopping camera feed"))
      case .disconnecting:
        return .status(message: String(localized: "Disconnecting from camera"))
      case .disconnected(let error):
        if let error {
          return .status(message: error.rawValue)
        }
        return .status(message: String(localized: "Disconnected"))
      case .forceDisconnect:
        return .status(message: String(localized: "Connection lost"))
    }
  }

  private func actionForRegistrationState(_ state: CameraState) -> CameraAction {
    switch state {
      case .connected:
        return .button(
          icon: "link.badge.plus",
          label: String(localized: "Register"),
          hint: String(localized: "Opens Meta AI to register this app with your glasses")
        )
      case .connecting, .starting:
        return .status(
          message: String(localized: "Waiting for registration in Meta AI. Approve the request and return to this app.")
        )
      case .started:
        return .status(
          message: String(localized: "Registration complete. Discovering cameras.")
        )
      default:
        return .status(message: state.stringValue)
    }
  }
}
