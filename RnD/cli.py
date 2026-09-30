#!/usr/bin/env python3
"""HackEye R&D CLI. Mirrors Apple/HackEye-cli's flags where they overlap,
and adds the input-resolution flags described in the plan (native footage
size/aspect by default; production geometry only when asked for).

Example:
    docker compose run --rm rnd \\
        --input /media/GOPR4927.MP4 \\
        --stage1-model /models/detector.pt \\
        --seg-model /models/segmentation.pt \\
        --debug-destination /debug --verbose --json
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

import cv2  # noqa: E402

import config  # noqa: E402
import gpu_guard  # noqa: E402
from detect import BusDetector, DetectorConfig  # noqa: E402
from models import SegmentationModel, load_detector  # noqa: E402
from pipeline import IMAGE_EXTENSIONS, Pipeline, PipelineConfig  # noqa: E402
from profiles import resolve_input_spec  # noqa: E402


def _probe_source_size(input_path: str) -> tuple[int, int]:
    """Read width/height from the first frame/image without decoding the
    whole file — needed before we know what letterbox target to use."""
    path = Path(input_path)
    if path.is_dir():
        first = sorted(p for p in path.iterdir() if p.suffix.lower() in IMAGE_EXTENSIONS)
        if not first:
            print(f"No image files found in: {path}", file=sys.stderr)
            sys.exit(1)
        img = cv2.imread(str(first[0]))
    elif path.suffix.lower() in IMAGE_EXTENSIONS:
        img = cv2.imread(str(path))
    else:
        cap = cv2.VideoCapture(str(path))
        if not cap.isOpened():
            print(f"Cannot open input: {path}", file=sys.stderr)
            sys.exit(1)
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()
        return w, h

    if img is None:
        print(f"Cannot load image: {path}", file=sys.stderr)
        sys.exit(1)
    h, w = img.shape[:2]
    return w, h


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", required=True, help="Image, image folder, or video path")
    parser.add_argument("--stage1-model", required=True, help="Path to bus-detector .pt checkpoint")
    parser.add_argument("--seg-model", help="Path to segmentation .pt checkpoint (optional)")

    res = parser.add_mutually_exclusive_group()
    res.add_argument("--profile", choices=["production", "half", "third"],
                      help="production=512x896 (pins app geometry); half/third=native aspect, scaled down")
    res.add_argument("--size", help="Explicit WxH detector input size")
    res.add_argument("--aspect", help="Explicit W:H aspect ratio, fit to native extent")

    parser.add_argument("--stage1-conf", type=float, default=config.DETECTOR["confidence"])
    parser.add_argument("--stage1-bus-class", type=int, default=config.DETECTOR["busClass"])
    parser.add_argument("--seg-min-pixel-count", type=int, default=None,
                         help=f"Absolute grid-cell threshold (defaults to "
                              f"{config.SEGMENTATION['minPixelCount']} if unset, matching the Swift app; "
                              f"meaning changes with grid resolution, see profiles.py)")
    parser.add_argument("--seg-min-pixel-fraction", type=float, default=None,
                         help="Fraction of grid area, resolution-independent (preferred for non-production profiles)")
    parser.add_argument("--seg-alpha", type=float, default=config.SEGMENTATION["alpha"])
    parser.add_argument("--debug-destination", default="/debug", help="Where to write per-frame debug dumps")
    parser.add_argument("--no-debug", action="store_true", help="Skip debug dumps entirely")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--json", action="store_true", dest="json_output")

    args = parser.parse_args()

    device = gpu_guard.assert_torch_cuda()

    src_w, src_h = _probe_source_size(args.input)
    input_spec = resolve_input_spec(src_w, src_h, args.profile, args.size, args.aspect)
    print(f"[cli] source {src_w}x{src_h} -> input spec {input_spec.dst_w}x{input_spec.dst_h} "
          f"({input_spec.description})", file=sys.stderr)

    print("[cli] loading stage1 (detection) model...", file=sys.stderr)
    stage1 = load_detector(args.stage1_model, device)
    detector_config = DetectorConfig(
        detector_w=input_spec.dst_w, detector_h=input_spec.dst_h,
        bus_class=args.stage1_bus_class, confidence=args.stage1_conf,
    )
    detector = BusDetector(stage1, detector_config, device)

    seg_model = None
    if args.seg_model:
        print("[cli] loading segmentation model...", file=sys.stderr)
        seg_model = SegmentationModel(args.seg_model, device)

    pipeline_config = PipelineConfig(
        input_path=args.input,
        detector=detector_config,
        input_spec=input_spec,
        seg_min_pixel_count=args.seg_min_pixel_count,
        seg_min_pixel_fraction=args.seg_min_pixel_fraction,
        seg_alpha=args.seg_alpha,
        debug_destination=None if args.no_debug else Path(args.debug_destination),
        verbose=args.verbose,
        json_output=args.json_output,
    )

    Pipeline(pipeline_config, detector, seg_model).run()


if __name__ == "__main__":
    main()
