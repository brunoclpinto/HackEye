import Foundation
import CoreML

// MARK: - Safety Level

/// Safety classification for segmented scene regions.
public enum SafetyLevel: Int, Sendable, CaseIterable {
    case ignored = 0
    case safe = 1       // Green #00FF00
    case safeish = 2    // Light Orange #FFB366 (reserved for future custom classes)
    case danger = 3     // Dark Orange #FF6600
    case death = 4      // Red #FF0000

    public var colorR: UInt8 {
        switch self {
        case .safe:    return 0x00
        case .safeish: return 0xFF
        case .danger:  return 0xFF
        case .death:   return 0xFF
        case .ignored: return 0x00
        }
    }

    public var colorG: UInt8 {
        switch self {
        case .safe:    return 0xFF
        case .safeish: return 0xB3
        case .danger:  return 0x66
        case .death:   return 0x00
        case .ignored: return 0x00
        }
    }

    public var colorB: UInt8 {
        switch self {
        case .safe:    return 0x00
        case .safeish: return 0x66
        case .danger:  return 0x00
        case .death:   return 0x00
        case .ignored: return 0x00
        }
    }

    /// 75% alpha for visible levels, 0 for ignored.
    public var colorA: UInt8 {
        switch self {
        case .ignored: return 0x00
        default:       return 191
        }
    }

    public var label: String {
        switch self {
        case .ignored: return "ignored"
        case .safe:    return "safe"
        case .safeish: return "safe-ish"
        case .danger:  return "danger"
        case .death:   return "death"
        }
    }
}

// MARK: - CityscapesClass

/// A Cityscapes class with its safety mapping.
public struct CityscapesClass: Sendable {
    public let id: Int
    public let name: String
    public let safetyLevel: SafetyLevel
}

// MARK: - CityscapesMapping

/// Standard Cityscapes 19-class trainId → safety level lookup.
public enum CityscapesMapping {

    public static let classes: [CityscapesClass] = [
        CityscapesClass(id: 0,  name: "road",          safetyLevel: .danger),
        CityscapesClass(id: 1,  name: "sidewalk",      safetyLevel: .safe),
        CityscapesClass(id: 2,  name: "building",      safetyLevel: .death),
        CityscapesClass(id: 3,  name: "wall",          safetyLevel: .death),
        CityscapesClass(id: 4,  name: "fence",         safetyLevel: .death),
        CityscapesClass(id: 5,  name: "pole",          safetyLevel: .death),
        CityscapesClass(id: 6,  name: "traffic light", safetyLevel: .death),
        CityscapesClass(id: 7,  name: "traffic sign",  safetyLevel: .death),
        CityscapesClass(id: 8,  name: "vegetation",    safetyLevel: .death),
        CityscapesClass(id: 9,  name: "terrain",       safetyLevel: .death),
        CityscapesClass(id: 10, name: "sky",           safetyLevel: .ignored),
        CityscapesClass(id: 11, name: "person",        safetyLevel: .death),
        CityscapesClass(id: 12, name: "rider",         safetyLevel: .death),
        CityscapesClass(id: 13, name: "car",           safetyLevel: .death),
        CityscapesClass(id: 14, name: "truck",         safetyLevel: .death),
        CityscapesClass(id: 15, name: "bus",           safetyLevel: .death),
        CityscapesClass(id: 16, name: "train",         safetyLevel: .death),
        CityscapesClass(id: 17, name: "motorcycle",    safetyLevel: .death),
        CityscapesClass(id: 18, name: "bicycle",       safetyLevel: .death),
    ]

    public static func classFor(id: Int) -> CityscapesClass? {
        guard id >= 0, id < classes.count else { return nil }
        return classes[id]
    }
}

// MARK: - SegmentationGrid

/// Per-pixel argmax results on the downsampled grid.
public struct SegmentationGrid: Sendable {
    public let gridW: Int
    public let gridH: Int
    /// Row-major `[gridH * gridW]` — argmax class ID per pixel (0-18).
    public let classIds: [Int]
    /// Row-major `[gridH * gridW]` — safety level per pixel.
    public let safetyLevels: [SafetyLevel]
}

// MARK: - SegmentedObject

/// A connected region from the segmentation map with its convex hull polygon.
public struct SegmentedObject: Sendable {
    public let classId: Int
    public let className: String
    public let safetyLevel: SafetyLevel
    /// Convex hull polygon in original image pixel coordinates.
    public let polygon: [(x: Int, y: Int)]
    /// Number of grid cells belonging to this component.
    public let pixelCount: Int
}

// MARK: - SafetySegmentation

/// Parses a `[1, numClasses, gridH, gridW]` segmentation output into a
/// `SegmentationGrid` and extracts per-object convex hull polygons.
public final class SafetySegmentation {

    public init() {}

    // MARK: - Parse grid

    /// Argmax across the class dimension for each spatial position.
    /// Pixels inside letterbox padding are set to `.ignored`.
    public func parseGrid(
        _ arr: MLMultiArray,
        letterboxMeta meta: LetterboxMeta
    ) -> SegmentationGrid {
        let shape = arr.shape.map { $0.intValue }   // [1, C, H, W]
        let strides = arr.strides.map { $0.intValue }
        let numClasses = shape[1]
        let gridH = shape[2]
        let gridW = shape[3]

        let inputW = meta.dstW
        let inputH = meta.dstH
        let scaleX = inputW / Double(gridW)
        let scaleY = inputH / Double(gridH)

        // Valid content region (exclude letterbox padding)
        let validMinCol = Int(floor(meta.padX / scaleX))
        let validMaxCol = Int(ceil((inputW - meta.padX) / scaleX)) - 1
        let validMinRow = Int(floor(meta.padY / scaleY))
        let validMaxRow = Int(ceil((inputH - meta.padY) / scaleY)) - 1

        let total = gridH * gridW
        var classIds = [Int](repeating: 10, count: total)  // default to sky (ignored)
        var safetyLevels = [SafetyLevel](repeating: .ignored, count: total)

        for row in 0..<gridH {
            for col in 0..<gridW {
                let pixel = row * gridW + col

                // Skip padding pixels
                if row < validMinRow || row > validMaxRow ||
                   col < validMinCol || col > validMaxCol {
                    continue
                }

                var bestClass = 0
                var bestLogit = -Double.infinity

                for c in 0..<numClasses {
                    let idx = c * strides[1] + row * strides[2] + col * strides[3]
                    let val = Self.readValue(arr, linearIndex: idx)
                    if val > bestLogit {
                        bestLogit = val
                        bestClass = c
                    }
                }

                classIds[pixel] = bestClass
                safetyLevels[pixel] = CityscapesMapping.classFor(id: bestClass)?.safetyLevel ?? .ignored
            }
        }

        return SegmentationGrid(
            gridW: gridW, gridH: gridH,
            classIds: classIds, safetyLevels: safetyLevels
        )
    }

    // MARK: - Extract objects

    /// Connected-component labeling on same-class pixels, then convex hull
    /// polygon extraction with coordinates mapped to original image space.
    public func extractObjects(
        from grid: SegmentationGrid,
        meta: LetterboxMeta,
        minPixelCount: Int = 50
    ) -> [SegmentedObject] {
        let total = grid.gridH * grid.gridW
        var parent = Array(0..<total)

        // Union-Find with path compression
        func find(_ x: Int) -> Int {
            var x = x
            while parent[x] != x {
                parent[x] = parent[parent[x]]
                x = parent[x]
            }
            return x
        }
        func union(_ a: Int, _ b: Int) {
            let ra = find(a), rb = find(b)
            if ra != rb { parent[ra] = rb }
        }

        // Connect 4-neighbors with same classId
        for row in 0..<grid.gridH {
            for col in 0..<grid.gridW {
                let idx = row * grid.gridW + col
                let cls = grid.classIds[idx]
                // Right neighbor
                if col + 1 < grid.gridW && grid.classIds[idx + 1] == cls {
                    union(idx, idx + 1)
                }
                // Below neighbor
                if row + 1 < grid.gridH && grid.classIds[idx + grid.gridW] == cls {
                    union(idx, idx + grid.gridW)
                }
            }
        }

        // Group pixels by root
        var components: [Int: [Int]] = [:]
        for i in 0..<total {
            let root = find(i)
            components[root, default: []].append(i)
        }

        let scaleX = meta.dstW / Double(grid.gridW)
        let scaleY = meta.dstH / Double(grid.gridH)

        var objects: [SegmentedObject] = []

        for (_, pixels) in components {
            guard pixels.count >= minPixelCount else { continue }
            let classId = grid.classIds[pixels[0]]
            guard let csClass = CityscapesMapping.classFor(id: classId),
                  csClass.safetyLevel != .ignored else { continue }

            // Extract boundary points in grid coords
            let pixelSet = Set(pixels)
            var boundary: [(x: Int, y: Int)] = []
            for idx in pixels {
                let col = idx % grid.gridW
                let row = idx / grid.gridW
                let neighbors = [idx - 1, idx + 1, idx - grid.gridW, idx + grid.gridW]
                let isBoundary = neighbors.contains { $0 < 0 || $0 >= total || !pixelSet.contains($0) }
                if isBoundary {
                    boundary.append((x: col, y: row))
                }
            }

            // Convex hull
            let hull = convexHull(boundary)

            // Map grid coords → detector-input coords → original image coords
            let mappedHull: [(x: Int, y: Int)] = hull.map { pt in
                let detX = (Double(pt.x) + 0.5) * scaleX
                let detY = (Double(pt.y) + 0.5) * scaleY
                let srcX = (detX - meta.padX) / max(meta.scale, 1e-9)
                let srcY = (detY - meta.padY) / max(meta.scale, 1e-9)
                return (
                    x: max(0, min(Int(meta.srcW) - 1, Int(srcX.rounded()))),
                    y: max(0, min(Int(meta.srcH) - 1, Int(srcY.rounded())))
                )
            }

            objects.append(SegmentedObject(
                classId: classId,
                className: csClass.name,
                safetyLevel: csClass.safetyLevel,
                polygon: mappedHull,
                pixelCount: pixels.count
            ))
        }

        return objects.sorted { $0.pixelCount > $1.pixelCount }
    }

    // MARK: - Convex hull (Andrew's monotone chain)

    private func convexHull(_ points: [(x: Int, y: Int)]) -> [(x: Int, y: Int)] {
        guard points.count > 2 else { return points }
        let sorted = points.sorted { $0.x != $1.x ? $0.x < $1.x : $0.y < $1.y }
        var hull: [(x: Int, y: Int)] = []

        // Lower hull
        for p in sorted {
            while hull.count >= 2 && cross(hull[hull.count - 2], hull[hull.count - 1], p) <= 0 {
                hull.removeLast()
            }
            hull.append(p)
        }

        // Upper hull
        let lower = hull.count + 1
        for p in sorted.reversed() {
            while hull.count >= lower && cross(hull[hull.count - 2], hull[hull.count - 1], p) <= 0 {
                hull.removeLast()
            }
            hull.append(p)
        }
        hull.removeLast()
        return hull
    }

    private func cross(
        _ o: (x: Int, y: Int),
        _ a: (x: Int, y: Int),
        _ b: (x: Int, y: Int)
    ) -> Int {
        (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x)
    }

    // MARK: - MLMultiArray reader

    /// Read a float16/32/64 value at a linear byte offset.
    /// Duplicated from YOLOModel (private there).
    private static func readValue(_ arr: MLMultiArray, linearIndex: Int) -> Double {
        switch arr.dataType {
        case .double:
            return arr.dataPointer.assumingMemoryBound(to: Double.self)[linearIndex]
        case .float32:
            return Double(arr.dataPointer.assumingMemoryBound(to: Float.self)[linearIndex])
        case .float16:
            let u = arr.dataPointer.assumingMemoryBound(to: UInt16.self)[linearIndex]
            let sign = (u & 0x8000) != 0
            let exp  = Int((u & 0x7C00) >> 10)
            let frac = Int(u & 0x03FF)
            var f: Float
            if exp == 0 {
                f = Float(frac) / Float(1 << 10) * powf(2, -14)
            } else if exp == 0x1F {
                f = frac == 0 ? .infinity : .nan
            } else {
                f = (1.0 + Float(frac) / Float(1 << 10)) * powf(2, Float(exp - 15))
            }
            return Double(sign ? -f : f)
        default:
            return Double(truncating: arr[linearIndex] as NSNumber)
        }
    }
}
