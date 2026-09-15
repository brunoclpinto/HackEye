# HackEye iOS Project Memory

## Project Overview
iOS camera-based computer vision app to help visually impaired users perceive their surroundings: approaching-bus detection/OCR (shipped), and in-progress safety-level semantic segmentation for walkable-path navigation.
Working directory: `/Users/brunopinto/Repos/HackEye/Apple`
Current branch: `segmentation` — adding Cityscapes-based safety segmentation, not yet merged to `main`.

The `BusAndOCR.swift` monolith refactor described in earlier versions of this file is **done**: the code now lives across `WorkflowEngine/`, `Flows/`, `Domain/`, `Helpers/` as described below.

## Key Architecture

### Layers
- **Camera layer**: Protocol-driven actor-based abstraction (`Cameras/`)
  - `CameraManager` → `CameraController` → `Camera` (Actor protocol, `Cameras/Camera.swift`)
  - iPhone backend: `CameraIphone` (`Cameras/iPhone/`, AVCaptureSession, YUV420, CIImage output)
  - Meta backend: `CameraMeta` (`Cameras/Meta/`, MWDATCore/Wearables SDK) — implemented, including a `CameraMetaRegistration` pairing flow surfaced in the UI
- **ML/Workflow layer**: `Models/Workflows/BusApproachTracker.swift` — orchestrator, calls `BusDetectionFlow` then `BusTrackingFlow` directly (sequential `await`, not via `WorkflowManager`)
- **WorkflowEngine** (`Models/WorkflowEngine/`): `Flow` protocol, `AnyFlow`, `WorkflowManager` (TaskGroup-based concurrent/serial runner), `WorkflowGraph`, `WorkflowOutput` — this engine is fully built but **currently unused**; nothing in the codebase calls `WorkflowManager` or `WorkflowGraph` yet (`BusApproachTracker` bypasses it and drives the two flows itself). Treat it as scaffolding for a future multi-flow pipeline (e.g. bus + segmentation running through the same engine), not as active infrastructure.
- **Domain** (`Models/Domain/`): `YOLOModel` (CoreML wrapper, flexible tensor parsing), `ImageLetterboxer`, `BusDetector`, `BusTracker`, `SafetySegmentation` (new — see below)
- **Flows** (`Models/Flows/`): `BusDetectionFlow`, `BusTrackingFlow` — thin `Flow`-protocol adapters around the Domain types
- **Helpers**: `SaveMov.swift` (`DebugFrameSaver` — per-frame H264/JPEG + JSON debug capture under `DevDebug` builds, now also writes segmentation overlays), `Speaker.swift` (TTS)
- **Views**: SwiftUI MVVM — `MainView`/`MainViewModel` (camera list) → `CameraView`/`CameraViewModel` (per-frame processing + state machine)
- **CLI** (`HackEye-cli/`): standalone `swift run` test harness (`main.swift`, `CLIProcessor.swift`, `CLIDebugOutput.swift`) for iterating on Domain logic against image/video files without the app. Its `Shared/` folder is a set of **symlinks** into `Models/Domain/` — edit the Domain source, never the CLI copy.

### Key Types
- `BusApproachTracker`: Main public API — `processFrame(CIImage) async throws -> (results: [BusResult], timing: TimingInfo)`
- `BusResult`: id, bboxDetectorSpace, bboxOriginalTopLeft, confidence, approachingScore
- `YOLOModel`: CoreML model wrapper, flexible tensor parsing (handles float16/32/64 outputs)
- Two bus-pipeline YOLO models: `yolo26sINT8512x896` (Stage1 bus detection); a Stage2 info/OCR model referenced in the CLI config (`stage1Model`/OCR path) is not currently wired into the app pipeline
- New segmentation model: `yolo26s-semINT8512x896` — Cityscapes-19-class semantic segmentation, 512x896 input, bundled into the app and loaded in `CameraViewModel`

### Safety Segmentation (new, `segmentation` branch)
- `Models/Domain/SafetySegmentation.swift`: parses a `[1, 19, gridH, gridW]` CoreML output into a `SegmentationGrid` (per-pixel `SafetyLevel`), plus connected-component + convex-hull `SegmentedObject` extraction.
- `SafetyLevel`: `.ignored`, `.safe` (dark green #008000), `.safeish` (orange #FF8C00, defined but not yet assigned to any Cityscapes class), `.danger` (red #FF0000), `.death` (dark blue #00008B).
- `CityscapesMapping`: 19 standard Cityscapes classes → `SafetyLevel`. Currently only `sidewalk`→safe and `road`→danger are meaningfully distinguished; `sky`→ignored; everything else solid (buildings, vegetation, poles, vehicles, people, etc.)→death. Mapping is expected to keep evolving.
- Runs per-frame in `CameraViewModel.processFrame`, independently of and in parallel intent with the bus pipeline (not yet merged through WorkflowEngine). Under `DevDebug` builds, `DebugFrameSaver` writes a `work.png` color overlay + `result.json` (objects, polygons, timing) per frame into `frame_NNNNNN_seg/`.
- Also drivable standalone via `HackEye-cli` with `segModel=`, `segAlpha=` (0–1 double, default 0.55), `segMinPixelCount=` args — useful for tuning the Cityscapes→SafetyLevel mapping and overlay alpha against saved footage before touching the app.
- Roadmap context (see top-level `README.md`, "What am I working on / Navigation"): this is the "Where can I go?" piece ahead of a dedicated LRASPP-MobileNetV3 walkable-path model (external repo `LRASPP_MobileNetV3_Walkable`).

### Concurrency Model
- Swift actors throughout (`CameraManager`, `CameraController`, `Camera` conformers)
- `AsyncStream` for camera state updates, consumed in `CameraViewModel.startObservingState()`
- `TaskGroup` for parallel camera loading (`MainViewModel.snapshotCameras`) and inside `WorkflowManager.runConcurrent` (currently unused, see above)
- CIContext on `global(qos: .userInitiated)` for GPU rendering (`ImageLetterboxer`)

## Commit Conventions
- Title: 50 chars max, imperative mood, no period
- Description: what changed, why, what was deliberately left unchanged
- Never commit if project does not build

## Dependencies
- Apple: CoreML, Vision, AVFoundation, CoreImage, Metal, Photos, SwiftUI
- Third-party: Meta Wearables SDK (MWDATCore), currently on 0.6.0, used by `Cameras/Meta/`

## Important File Paths
- Orchestrator: `Models/Workflows/BusApproachTracker.swift`
- Unused engine scaffolding: `Models/WorkflowEngine/` (Flow, WorkflowGraph, WorkflowManager, WorkflowOutput)
- Segmentation domain logic: `Models/Domain/SafetySegmentation.swift`
- Debug capture: `Models/Helpers/SaveMov.swift` (`DebugFrameSaver`)
- App entry: `HackEye/HackEyeApp.swift`
- Main view: `Views/Main/Main.view.swift` + `Main.view.model.swift`
- Camera view: `Views/Camera/Camera.view.swift` + `Camera.view.model.swift`
- iPhone camera: `Cameras/iPhone/Camera.iphone.swift`
- Meta camera: `Cameras/Meta/Camera.meta.swift`, `Camera.registration.meta.swift`
- CLI: `HackEye-cli/main.swift`, `CLIProcessor.swift`, `CLIDebugOutput.swift`
- Xcode project: `HackEye.xcodeproj/project.pbxproj`
