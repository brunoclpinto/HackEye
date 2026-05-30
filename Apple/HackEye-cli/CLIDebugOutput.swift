import Foundation
import CoreImage
import CoreGraphics
import ImageIO

// MARK: - CLIDebugOutput

final class CLIDebugOutput {
    let basePath: String
    let segAlpha: UInt8
    private let ciContext: CIContext

    init(basePath: String, segAlpha: Int = 191) {
        self.basePath = basePath
        self.segAlpha = UInt8(clamping: segAlpha)
        self.ciContext = ImageLetterboxer.ciContext
    }

    /// Resolve a unique output folder, Finder-style: "name", "name 2", "name 3", ...
    func resolveOutputFolder(inputName: String) -> URL {
        let base = URL(fileURLWithPath: basePath)
        var candidate = base.appendingPathComponent(inputName)
        if !FileManager.default.fileExists(atPath: candidate.path) {
            return candidate
        }
        var n = 2
        while FileManager.default.fileExists(
            atPath: base.appendingPathComponent("\(inputName) \(n)").path
        ) {
            n += 1
        }
        candidate = base.appendingPathComponent("\(inputName) \(n)")
        return candidate
    }

    func saveFrame(
        folder: URL,
        frameIndex: Int,
        originalImage: CIImage,
        meta: LetterboxMeta,
        detections: [BusDetection],
        tracked: [TrackedBus],
        segGrid: SegmentationGrid?,
        segObjects: [SegmentedObject],
        fps: Double?,
        s1Ms: Double, s2Ms: Double, segMs: Double, totalMs: Double
    ) throws {
        let frameFolder = folder.appendingPathComponent(
            String(format: "frame_%04d", frameIndex)
        )
        try FileManager.default.createDirectory(
            at: frameFolder, withIntermediateDirectories: true
        )

        // original.png
        saveCIImageAsPNG(originalImage, to: frameFolder.appendingPathComponent("original.png"))

        // info.json
        var info: [String: Any] = [
            "frameIndex": frameIndex,
            "totalProcessingMs": totalMs,
            "width": Int(originalImage.extent.width),
            "height": Int(originalImage.extent.height)
        ]
        if let fps = fps { info["fps"] = fps }
        saveJSON(info, to: frameFolder.appendingPathComponent("info.json"))

        // BusDetection/
        let detFolder = frameFolder.appendingPathComponent("BusDetection")
        try FileManager.default.createDirectory(at: detFolder, withIntermediateDirectories: true)

        // work.png — recreate letterboxed frame
        let (letterboxed, _) = ImageLetterboxer.letterboxWithMeta(
            originalImage,
            srcW: meta.srcW, srcH: meta.srcH,
            dstW: meta.dstW, dstH: meta.dstH
        )
        saveCIImageAsPNG(letterboxed, to: detFolder.appendingPathComponent("work.png"))

        let detResult: [String: Any] = [
            "detected": !detections.isEmpty,
            "count": detections.count,
            "elapsedMs": s1Ms,
            "detections": detections.map { d in
                [
                    "score": d.score,
                    "class": d.cls,
                    "boxDetector": [
                        "x1": d.boxDetector.x1, "y1": d.boxDetector.y1,
                        "x2": d.boxDetector.x2, "y2": d.boxDetector.y2
                    ],
                    "boxOriginal": [
                        "x1": d.boxOriginal.x1, "y1": d.boxOriginal.y1,
                        "x2": d.boxOriginal.x2, "y2": d.boxOriginal.y2
                    ]
                ] as [String: Any]
            }
        ]
        saveJSON(detResult, to: detFolder.appendingPathComponent("result.json"))

        // BusTracking/
        let trackFolder = frameFolder.appendingPathComponent("BusTracking")
        try FileManager.default.createDirectory(at: trackFolder, withIntermediateDirectories: true)

        let trackResult: [String: Any] = [
            "detected": !tracked.isEmpty,
            "count": tracked.count,
            "elapsedMs": s2Ms,
            "buses": tracked.map { t in
                [
                    "id": t.id,
                    "name": t.name,
                    "isApproaching": t.isApproaching,
                    "approachingScore": t.approachingScore,
                    "score": t.lastScore
                ] as [String: Any]
            }
        ]
        saveJSON(trackResult, to: trackFolder.appendingPathComponent("result.json"))

        // SafetySegmentation/
        if let grid = segGrid {
            let segFolder = frameFolder.appendingPathComponent("SafetySegmentation")
            try FileManager.default.createDirectory(at: segFolder, withIntermediateDirectories: true)

            // work.png — letterboxed frame with colored safety overlay
            let overlayImage = renderSafetyOverlay(
                grid: grid,
                originalImage: originalImage,
                meta: meta
            )
            saveCIImageAsPNG(overlayImage, to: segFolder.appendingPathComponent("work.png"))

            // result.json
            let segResultDict: [String: Any] = [
                "gridW": grid.gridW,
                "gridH": grid.gridH,
                "elapsedMs": segMs,
                "objectCount": segObjects.count,
                "objects": segObjects.map { obj in
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
            saveJSON(segResultDict, to: segFolder.appendingPathComponent("result.json"))
        }
    }

    // MARK: - Safety Overlay Rendering

    /// Render the segmentation grid as a colored RGBA overlay composited
    /// on top of the letterboxed frame image.
    private func renderSafetyOverlay(
        grid: SegmentationGrid,
        originalImage: CIImage,
        meta: LetterboxMeta
    ) -> CIImage {
        let detectorW = Int(meta.dstW)
        let detectorH = Int(meta.dstH)

        // Recreate letterboxed background
        let (letterboxed, _) = ImageLetterboxer.letterboxWithMeta(
            originalImage,
            srcW: meta.srcW, srcH: meta.srcH,
            dstW: meta.dstW, dstH: meta.dstH
        )

        // Build RGBA overlay bitmap at detector resolution.
        // CIImage(bitmapData:) interprets row 0 as the bottom row,
        // so we flip vertically: output row py corresponds to
        // image row (detectorH - 1 - py).
        let bpp = 4
        var pixels = [UInt8](repeating: 0, count: detectorW * detectorH * bpp)

        for py in 0..<detectorH {
            let imageRow = detectorH - 1 - py  // flip for CIImage bottom-left origin
            for px in 0..<detectorW {
                let gridCol = min(grid.gridW - 1, px * grid.gridW / detectorW)
                let gridRow = min(grid.gridH - 1, imageRow * grid.gridH / detectorH)
                let gridIdx = gridRow * grid.gridW + gridCol
                let level = grid.safetyLevels[gridIdx]

                guard level != .ignored else { continue }

                let offset = (py * detectorW + px) * bpp
                pixels[offset + 0] = level.colorR
                pixels[offset + 1] = level.colorG
                pixels[offset + 2] = level.colorB
                pixels[offset + 3] = level.colorA(alpha: segAlpha)
            }
        }

        let overlayImage = CIImage(
            bitmapData: Data(pixels),
            bytesPerRow: detectorW * bpp,
            size: CGSize(width: detectorW, height: detectorH),
            format: .RGBA8,
            colorSpace: CGColorSpaceCreateDeviceRGB()
        )

        return overlayImage.composited(over: letterboxed)
    }

    // MARK: - Image & JSON Helpers

    private func saveCIImageAsPNG(_ image: CIImage, to url: URL) {
        guard let cgImage = ciContext.createCGImage(image, from: image.extent) else { return }
        guard let dest = CGImageDestinationCreateWithURL(
            url as CFURL, "public.png" as CFString, 1, nil
        ) else { return }
        CGImageDestinationAddImage(dest, cgImage, nil)
        CGImageDestinationFinalize(dest)
    }

    private func saveJSON(_ dict: [String: Any], to url: URL) {
        if let data = try? JSONSerialization.data(
            withJSONObject: dict, options: [.prettyPrinted, .sortedKeys]
        ) {
            try? data.write(to: url)
        }
    }
}
