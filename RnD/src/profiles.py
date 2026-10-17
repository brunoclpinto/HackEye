"""Input resolution policy for the R&D rig.

Default is 960px wide at the footage's native aspect ratio (never upscaled);
--profile native keeps the full source size. Production geometry
(512x896, portrait) is only used when explicitly requested via
--profile production — letterboxing this landscape GoPro footage into a
portrait target throws away ~68% of the frame as padding and downscales
content ~7.5x (see plan doc). Native-aspect-by-default avoids drawing
conclusions from that garbage.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

import config

STRIDE = 32
PRODUCTION_SIZE = (512, 896)  # (w, h) — matches BusDetector.Config in Swift
DEFAULT_WIDTH = 960


@dataclass
class InputSpec:
    dst_w: int
    dst_h: int
    is_native_aspect: bool
    description: str


def _align_up(value: int, stride: int = STRIDE) -> int:
    return ((value + stride - 1) // stride) * stride


SHORT_SIDE_OPTIONS = tuple(range(544, 737, 32))  # padded short side of the model input, "Np"


def short_side_spec(src_w: int, src_h: int, short: int) -> InputSpec:
    """Native-aspect input whose padded short side is exactly `short`, never upscaled.

    The long-side content is the largest multiple of STRIDE (<= the source) whose
    stride-aligned short side still fits in `short`; the short side is then
    aligned up (the letterbox pads it). Raises ValueError when reaching `short`
    would need upscaling the source.
    """
    landscape = src_w >= src_h
    long_src, short_src = (src_w, src_h) if landscape else (src_h, src_w)
    for long_c in range(long_src // STRIDE * STRIDE, 0, -STRIDE):
        short_c = round(short_src * long_c / long_src)
        if _align_up(short_c) <= short:
            break
    else:
        raise ValueError(f"{short}p is not possible for a {src_w}x{src_h} source")
    if short_c > short_src or _align_up(short_c) != short:
        raise ValueError(
            f"{short}p would upscale a {src_w}x{src_h} source "
            f"(the largest native-aspect input without upscaling has a short side of {_align_up(short_c)})")
    w, h = (long_c, short_c) if landscape else (short_c, long_c)
    dst_w, dst_h = _align_up(w), _align_up(h)
    return InputSpec(dst_w, dst_h, is_native_aspect=True,
                     description=f"{short}p: {w}x{h} content of native {src_w}x{src_h}, input {dst_w}x{dst_h}")


def resolve_input_spec(
    src_w: int,
    src_h: int,
    profile: str | None,
    size: str | None,
    aspect: str | None,
) -> InputSpec:
    if sum(x is not None for x in (profile, size, aspect)) > 1:
        raise ValueError("Pass at most one of --profile, --size, --aspect")

    if profile is not None and profile.endswith("p") and profile[:-1].isdigit() \
            and int(profile[:-1]) in SHORT_SIDE_OPTIONS:
        return short_side_spec(src_w, src_h, int(profile[:-1]))

    if profile == "production":
        w, h = PRODUCTION_SIZE
        return InputSpec(w, h, is_native_aspect=False, description="production (512x896, pinned)")

    if profile in ("half", "third", "quarter"):
        divisor = {"half": 2, "third": 3, "quarter": 4}[profile]
        w = _align_up(round(src_w / divisor))
        h = _align_up(round(src_h / divisor))
        return InputSpec(w, h, is_native_aspect=True, description=f"{profile} of native, stride-aligned")

    if profile is not None and profile != "native":
        opts = ", ".join(f"{n}p" for n in SHORT_SIDE_OPTIONS)
        raise ValueError(f"Unknown profile: {profile!r} (expected {opts}, production, native, half, third, quarter)")

    if size is not None:
        try:
            w_s, h_s = size.lower().split("x")
            w, h = int(w_s), int(h_s)
        except ValueError:
            raise ValueError(f"--size must be WxH, got {size!r}") from None
        aligned_w, aligned_h = _align_up(w), _align_up(h)
        if (aligned_w, aligned_h) != (w, h):
            print(
                f"[profiles] --size {w}x{h} is not a multiple of {STRIDE}; "
                f"aligning up to {aligned_w}x{aligned_h}",
                file=sys.stderr,
            )
        is_native = abs((w / h) - (src_w / src_h)) < 1e-6
        return InputSpec(aligned_w, aligned_h, is_native_aspect=is_native, description=f"custom size {w}x{h}")

    if aspect is not None:
        try:
            aw_s, ah_s = aspect.split(":")
            aw, ah = float(aw_s), float(ah_s)
        except ValueError:
            raise ValueError(f"--aspect must be W:H, got {aspect!r}") from None
        target_ratio = aw / ah
        # Fit within native extent without upscaling.
        if target_ratio >= (src_w / src_h):
            h = src_h
            w = round(h * target_ratio)
            if w > src_w:
                w, h = src_w, round(src_w / target_ratio)
        else:
            w = src_w
            h = round(w / target_ratio)
            if h > src_h:
                h, w = src_h, round(src_h * target_ratio)
        aligned_w, aligned_h = _align_up(w), _align_up(h)
        return InputSpec(
            aligned_w, aligned_h, is_native_aspect=False,
            description=f"custom aspect {aspect} -> {aligned_w}x{aligned_h}",
        )

    if profile is None:
        # Default: DEFAULT_WIDTH wide at native aspect, stride-aligned.
        w = min(DEFAULT_WIDTH, src_w)
        h = round(src_h * w / src_w)
        aligned_w, aligned_h = _align_up(w), _align_up(h)
        return InputSpec(aligned_w, aligned_h, is_native_aspect=True,
                         description=f"default {w}w of native {src_w}x{src_h}, stride-aligned")

    # --profile native: native size, stride-aligned.
    aligned_w, aligned_h = _align_up(src_w), _align_up(src_h)
    if (aligned_w, aligned_h) != (src_w, src_h):
        # The letterbox step (geometry.letterbox_params, applied per-frame)
        # centers this padding — it is not all pushed to one edge.
        print(
            f"[profiles] native {src_w}x{src_h} is not a multiple of {STRIDE}; "
            f"target is {aligned_w}x{aligned_h}, {aligned_w - src_w}px/{aligned_h - src_h}px "
            f"of padding split evenly by the letterbox (content is not upscaled)",
            file=sys.stderr,
        )
    return InputSpec(aligned_w, aligned_h, is_native_aspect=True, description=f"native {src_w}x{src_h}")


def resolve_seg_min_pixel_count(
    grid_w: int,
    grid_h: int,
    input_spec: InputSpec,
    seg_min_pixel_count: int | None,
    seg_min_pixel_fraction: float | None,
) -> int:
    """`segMinPixelCount` is an absolute grid-cell count in the Swift config
    (default 50). That default was tuned for the 512x896 production grid; the
    same absolute count means a wildly different real-world object size on a
    much larger native-resolution grid (see plan doc). Never resolve this
    silently across resolutions — always report what was used.
    """
    grid_area = grid_w * grid_h

    if seg_min_pixel_fraction is not None:
        count = max(1, round(seg_min_pixel_fraction * grid_area))
        print(
            f"[profiles] segMinPixelFraction={seg_min_pixel_fraction} "
            f"-> {count} cells on a {grid_w}x{grid_h} grid",
            file=sys.stderr,
        )
        return count

    count = seg_min_pixel_count if seg_min_pixel_count is not None else config.SEGMENTATION["minPixelCount"]
    if not input_spec.description.startswith("production"):
        print(
            f"[profiles] WARNING: using absolute segMinPixelCount={count} on a "
            f"{grid_w}x{grid_h} grid ({input_spec.description}). This threshold was "
            f"tuned for the 512x896 production grid and likely means a different "
            f"real-world object size here. Prefer --segMinPixelFraction for "
            f"cross-resolution comparisons.",
            file=sys.stderr,
        )
    return count
