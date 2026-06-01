import CoreImage
import CoreGraphics
import ImageIO
import Foundation
import UniformTypeIdentifiers

/// Saves individual HEIC frames to the app's Documents directory with
/// timing metadata embedded in EXIF and a per-session JSON manifest.
///
/// Directory structure:
/// ```
/// Documents/HackEye/Session_yyyyMMdd_HHmmss/
///   frame_000001.heic
///   frame_000002.heic
///   session.json
/// ```
///
/// Each HEIC file carries timing data in:
/// - **EXIF UserComment** — machine-readable JSON
/// - **TIFF ImageDescription** — human-readable summary (visible in Finder Get Info)
final class DebugFrameSaver {

  // MARK: - State

  private let queue = DispatchQueue(label: "DebugFrameSaver.queue")
  private let ciContext = CIContext()

  private var sessionDir: URL?
  private var frameIndex: Int = 0
  private var manifest: [FrameEntry] = []
  private var startTime: CFAbsoluteTime = 0
  private var sessionStartDate: Date?

  // MARK: - Manifest Types

  private nonisolated struct BusEntry: Encodable {
    let id: String
    let confidence: Double
    let approachingScore: Double
    let bbox: [String: Double]
  }

  private nonisolated struct FrameEntry: Encodable {
    let filename: String
    let elapsed: Double
    let fps: Double
    let flowTimings: [String: Double]
    let totalMs: Double
    let buses: [BusEntry]
    let spokenString: String
  }

  private nonisolated struct SessionManifest: Encodable {
    let sessionStart: String
    let frameCount: Int
    let frames: [FrameEntry]
  }

  // MARK: - Lifecycle

  func start() {
    queue.async {
      self.frameIndex = 0
      self.manifest = []
      self.startTime = 0
      self.sessionStartDate = Date()

      let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first!
      let hackEyeDir = docs.appendingPathComponent("HackEye", isDirectory: true)
      let ts = Self.timestampString(from: self.sessionStartDate!)
      let sessionDir = hackEyeDir.appendingPathComponent("Session_\(ts)", isDirectory: true)

      do {
        try FileManager.default.createDirectory(at: sessionDir, withIntermediateDirectories: true)
      } catch {
        print("[DebugFrameSaver] Failed to create session directory: \(error)")
        return
      }

      self.sessionDir = sessionDir
      print("[DebugFrameSaver] Session started: \(sessionDir.path)")
    }
  }

  func appendFrame(
    _ frame: CIImage,
    timing: BusApproachTracker.TimingInfo?,
    currentFPS: Double,
    busResults: [BusApproachTracker.BusResult],
    spokenString: String,
    segGrid: SegmentationGrid? = nil,
    segObjects: [SegmentedObject] = [],
    segMs: Double = 0,
    segDetectorW: Int = 0,
    segDetectorH: Int = 0
  ) {
    queue.async {
      guard let sessionDir = self.sessionDir else { return }

      let now = CFAbsoluteTimeGetCurrent()
      if self.startTime == 0 { self.startTime = now }
      let elapsed = now - self.startTime

      self.frameIndex += 1
      let filename = String(format: "frame_%06d.heic", self.frameIndex)
      let fileURL = sessionDir.appendingPathComponent(filename)

      // Build timing dictionaries
      var flowDict: [String: Double] = [:]
      if let timing {
        for (name, ms) in timing.flowTimings {
          flowDict[name] = ms
        }
      }

      // Build bus entries
      let busEntries = busResults.map { bus in
        let r = bus.bboxOriginalTopLeft
        return BusEntry(
          id: bus.id,
          confidence: bus.confidence,
          approachingScore: bus.approachingScore,
          bbox: ["x": r.origin.x, "y": r.origin.y, "w": r.width, "h": r.height]
        )
      }

      let entry = FrameEntry(
        filename: filename,
        elapsed: elapsed,
        fps: currentFPS,
        flowTimings: flowDict,
        totalMs: timing?.totalMs ?? 0,
        buses: busEntries,
        spokenString: spokenString
      )

      // Render CIImage → CGImage
      guard let cgImage = self.ciContext.createCGImage(frame, from: frame.extent) else {
        print("[DebugFrameSaver] Failed to create CGImage for \(filename)")
        return
      }

      // Build EXIF metadata
      let properties = Self.buildImageProperties(
        fps: currentFPS,
        timing: timing,
        elapsed: elapsed,
        busEntries: busEntries,
        spokenString: spokenString
      )

      // Write HEIC with metadata
      guard let dest = CGImageDestinationCreateWithURL(
        fileURL as CFURL,
        UTType.heic.identifier as CFString,
        1,
        nil
      ) else {
        print("[DebugFrameSaver] Failed to create image destination for \(filename)")
        return
      }

      CGImageDestinationAddImage(dest, cgImage, properties as CFDictionary)

      if !CGImageDestinationFinalize(dest) {
        print("[DebugFrameSaver] Failed to finalize \(filename)")
        return
      }

      self.manifest.append(entry)

      // SafetySegmentation debug output
      if let grid = segGrid {
        self.saveSegmentationDebug(
          frame: frame,
          grid: grid,
          objects: segObjects,
          segMs: segMs,
          segDetectorW: segDetectorW,
          segDetectorH: segDetectorH,
          sessionDir: sessionDir,
          frameIndex: self.frameIndex
        )
      }
    }
  }

  func stop() {
    queue.async {
      guard let sessionDir = self.sessionDir else { return }

      // Write session.json manifest
      let iso = ISO8601DateFormatter()
      let sessionManifest = SessionManifest(
        sessionStart: iso.string(from: self.sessionStartDate ?? Date()),
        frameCount: self.manifest.count,
        frames: self.manifest
      )

      let manifestURL = sessionDir.appendingPathComponent("session.json")
      do {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        let data = try encoder.encode(sessionManifest)
        try data.write(to: manifestURL)
      } catch {
        print("[DebugFrameSaver] Failed to write session.json: \(error)")
      }

      print("[DebugFrameSaver] Session stopped: \(self.manifest.count) frames saved to \(sessionDir.path)")

      // Reset state
      self.sessionDir = nil
      self.frameIndex = 0
      self.manifest = []
      self.startTime = 0
      self.sessionStartDate = nil
    }
  }

  // MARK: - Private

  private static func buildImageProperties(
    fps: Double,
    timing: BusApproachTracker.TimingInfo?,
    elapsed: Double,
    busEntries: [BusEntry],
    spokenString: String
  ) -> [CFString: Any] {
    // Machine-readable JSON for EXIF UserComment
    var jsonDict: [String: Any] = [
      "fps": fps,
      "elapsed": elapsed,
      "spokenString": spokenString
    ]
    if let timing {
      var flowDict: [String: Double] = [:]
      for (name, ms) in timing.flowTimings {
        flowDict[name] = ms
      }
      jsonDict["flowTimings"] = flowDict
      jsonDict["totalMs"] = timing.totalMs
    }
    if !busEntries.isEmpty {
      jsonDict["buses"] = busEntries.map { bus in
        [
          "id": bus.id as Any,
          "confidence": bus.confidence as Any,
          "approachingScore": bus.approachingScore as Any,
          "bbox": bus.bbox as Any
        ]
      }
    }
    let jsonString: String
    if let data = try? JSONSerialization.data(withJSONObject: jsonDict, options: [.sortedKeys]),
       let str = String(data: data, encoding: .utf8) {
      jsonString = str
    } else {
      jsonString = "{}"
    }

    // Human-readable summary for TIFF ImageDescription
    var lines: [String] = []
    lines.append(String(format: "FPS: %.1f", fps))
    if let timing {
      for (name, ms) in timing.flowTimings {
        lines.append(String(format: "%@: %.1f ms", name, ms))
      }
      lines.append(String(format: "workflow: %.1f ms", timing.totalMs))
    }
    if !busEntries.isEmpty {
      for bus in busEntries {
        lines.append("bus \(bus.id): conf=\(String(format: "%.2f", bus.confidence)) approach=\(String(format: "%.3f", bus.approachingScore))")
      }
    }
    if !spokenString.isEmpty {
      lines.append("spoken: \(spokenString)")
    }
    lines.append(String(format: "elapsed: %.3f s", elapsed))
    let humanReadable = lines.joined(separator: "\n")

    return [
      kCGImagePropertyExifDictionary: [
        kCGImagePropertyExifUserComment: jsonString
      ],
      kCGImagePropertyTIFFDictionary: [
        kCGImagePropertyTIFFImageDescription: humanReadable
      ]
    ]
  }

  private static func timestampString(from date: Date) -> String {
    let f = DateFormatter()
    f.locale = Locale(identifier: "en_US_POSIX")
    f.dateFormat = "yyyyMMdd_HHmmss"
    return f.string(from: date)
  }

  // MARK: - Segmentation Debug Output

  private static let segAlpha: UInt8 = UInt8(clamping: Int((0.55 * 255).rounded()))

  private func saveSegmentationDebug(
    frame: CIImage,
    grid: SegmentationGrid,
    objects: [SegmentedObject],
    segMs: Double,
    segDetectorW: Int,
    segDetectorH: Int,
    sessionDir: URL,
    frameIndex: Int
  ) {
    let segFolder = sessionDir.appendingPathComponent(
      String(format: "frame_%06d_seg", frameIndex)
    )
    do {
      try FileManager.default.createDirectory(at: segFolder, withIntermediateDirectories: true)
    } catch {
      print("[DebugFrameSaver] Failed to create seg folder: \(error)")
      return
    }

    // work.png — safety overlay on letterboxed frame
    let srcW = Double(frame.extent.width)
    let srcH = Double(frame.extent.height)
    let dstW = Double(segDetectorW)
    let dstH = Double(segDetectorH)

    let (letterboxed, _) = ImageLetterboxer.letterboxWithMeta(
      frame, srcW: srcW, srcH: srcH, dstW: dstW, dstH: dstH
    )

    let overlayW = Int(dstW)
    let overlayH = Int(dstH)
    let bpp = 4
    var pixels = [UInt8](repeating: 0, count: overlayW * overlayH * bpp)

    for py in 0..<overlayH {
      for px in 0..<overlayW {
        let gridCol = min(grid.gridW - 1, px * grid.gridW / overlayW)
        let gridRow = min(grid.gridH - 1, py * grid.gridH / overlayH)
        let gridIdx = gridRow * grid.gridW + gridCol
        let level = grid.safetyLevels[gridIdx]

        guard level != .ignored else { continue }

        let offset = (py * overlayW + px) * bpp
        pixels[offset + 0] = level.colorR
        pixels[offset + 1] = level.colorG
        pixels[offset + 2] = level.colorB
        pixels[offset + 3] = level.colorA(alpha: Self.segAlpha)
      }
    }

    let overlayImage = CIImage(
      bitmapData: Data(pixels),
      bytesPerRow: overlayW * bpp,
      size: CGSize(width: overlayW, height: overlayH),
      format: .RGBA8,
      colorSpace: CGColorSpaceCreateDeviceRGB()
    )

    let composited = overlayImage.composited(over: letterboxed)
    saveCIImageAsPNG(composited, to: segFolder.appendingPathComponent("work.png"))

    // result.json
    let resultDict: [String: Any] = [
      "gridW": grid.gridW,
      "gridH": grid.gridH,
      "elapsedMs": segMs,
      "objectCount": objects.count,
      "objects": objects.map { obj in
        [
          "classId": obj.classId,
          "className": obj.className,
          "safetyLevel": obj.safetyLevel.rawValue,
          "safetyLevelName": obj.safetyLevel.label,
          "pixelCount": obj.pixelCount,
          "polygon": obj.polygon.map { ["x": $0.x, "y": $0.y] }
        ] as [String: Any]
      }
    ]

    if let data = try? JSONSerialization.data(
      withJSONObject: resultDict, options: [.prettyPrinted, .sortedKeys]
    ) {
      try? data.write(to: segFolder.appendingPathComponent("result.json"))
    }
  }

  private func saveCIImageAsPNG(_ image: CIImage, to url: URL) {
    guard let cgImage = ciContext.createCGImage(image, from: image.extent) else { return }
    guard let dest = CGImageDestinationCreateWithURL(
      url as CFURL, "public.png" as CFString, 1, nil
    ) else { return }
    CGImageDestinationAddImage(dest, cgImage, nil)
    CGImageDestinationFinalize(dest)
  }
}
