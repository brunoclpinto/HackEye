//
//  Camera.view.swift
//  MEyes
//
//  Created by Bruno Pinto on 27/02/2026.
//

import SwiftUI

struct CameraView: View {
  @StateObject var viewModel: CameraViewModel
  @Environment(\.dismiss) private var dismiss
  @Environment(\.scenePhase) private var scenePhase

  @State private var isCurtainRevealed = false
  @State private var savedBrightness: CGFloat? = nil

  private var isCurtainActive: Bool {
    viewModel.state == .started && !viewModel.camera.isRegistration
  }

  var body: some View {
    ZStack {
      VStack {
        Text("\(viewModel.camera.name)")
          .font(.title)
        Spacer()
          .frame(height: 20)

        HStack {
          Spacer()
          switch viewModel.action {
            case .button(let icon, let label, let hint):
              Button {
                Task {
                  await viewModel.performAction()
                }
              } label: {
                Image(systemName: icon)
                  .font(.title)
                  .padding(50)
                  .background(Circle().fill(Color(.darkGray).opacity(0.8)))
                  .imageScale(.large)
              }
              .buttonStyle(.plain)
              .accessibilityLabel(label)
              .accessibilityHint(hint)
            case .status(let message):
              VStack(spacing: 12) {
                ProgressView()
                  .progressViewStyle(.circular)
                  .scaleEffect(2)
                Text(message)
                  .font(.body)
                  .multilineTextAlignment(.center)
                  .foregroundStyle(.secondary)
                  .padding(.horizontal)
              }
              .padding(30)
          }
          Spacer()
        }
      }
      .frame(maxHeight: .infinity, alignment: .top)

      if isCurtainActive && !isCurtainRevealed {
        curtainOverlay
      }
    }
    .onAppear {
      Task {
        await viewModel.startObservingState()
        guard
          let camera = viewModel.camera.device
        else {
          return
        }
        await camera.connect { [weak viewModel] image in
          guard let viewModel else { return }
          Task {
            await viewModel.processFrame(image)
          }
        }
      }
    }
    .onDisappear {
      Task {
        await viewModel.camera.device?.disconnect()
        viewModel.stopObservingState()
      }
      deactivateCurtain()
    }
    .onChange(of: viewModel.state) {
      if viewModel.camera.isRegistration, viewModel.state == .started {
        dismiss()
        return
      }

      if isCurtainActive {
        if savedBrightness == nil {
          activateCurtain()
        }
      } else {
        if savedBrightness != nil {
          deactivateCurtain()
        }
      }
    }
    .onChange(of: scenePhase) {
      switch scenePhase {
        case .background, .inactive:
          if let brightness = savedBrightness {
            UIScreen.main.brightness = brightness
          }
        case .active:
          if isCurtainActive && !isCurtainRevealed {
            UIScreen.main.brightness = 0.0
          }
        @unknown default:
          break
      }
    }
  }

  // MARK: - Screen Curtain

  private var curtainOverlay: some View {
    Color.black
      .ignoresSafeArea()
      .accessibilityLabel("Screen curtain active. Swipe right to reveal controls.")
      .gesture(
        DragGesture(minimumDistance: 50)
          .onEnded { value in
            if value.translation.width > 100 {
              withAnimation(.easeInOut(duration: 0.3)) {
                revealCurtain()
              }
            }
          }
      )
      .transition(.opacity)
  }

  private func activateCurtain() {
    savedBrightness = UIScreen.main.brightness
    UIScreen.main.brightness = 0.0
    UIApplication.shared.isIdleTimerDisabled = true
    isCurtainRevealed = false
    UIAccessibility.post(
      notification: .screenChanged,
      argument: "Screen curtain activated. Swipe right to show controls."
    )
  }

  private func revealCurtain() {
    isCurtainRevealed = true
    if let brightness = savedBrightness {
      UIScreen.main.brightness = brightness
    }
  }

  private func deactivateCurtain() {
    if let brightness = savedBrightness {
      UIScreen.main.brightness = brightness
      savedBrightness = nil
    }
    UIApplication.shared.isIdleTimerDisabled = false
    isCurtainRevealed = false
  }
}

#Preview {
  CameraView(
    viewModel: CameraViewModel(
      camera: CameraSnapshot(
        state: .connected,
        name: "Camera",
        zoom: ""
      )
    )
  )
}
