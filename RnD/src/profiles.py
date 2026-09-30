"""Input resolution policy for the R&D rig.

Default is the footage's native size and aspect ratio. Production geometry
(512x896, portrait) is only used when explicitly requested via
--profile production — letterboxing this landscape GoPro footage into a
portrait target throws away ~68% of the frame as padding and downscales
content ~7.5x (see plan doc). Native-by-default avoids drawing conclusions
from that garbage.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

import config

STRIDE = 32
PRODUCTION_SIZE = (512, 896)  # (w, h) — matches BusDetector.Config in Swift


@dataclass
class InputSpec:
    dst_w: int
    dst_h: int
    is_native_aspect: bool
    description: str


def _align_up(value: int, stride: int = STRIDE) -> int:
    return ((value + stride - 1) // stride) * stride


def resolve_input_spec(
    src_w: int,
    src_h: int,
    profile: str | None,
    size: str | None,
    aspect: str | None,
) -> InputSpec:
    if sum(x is not None for x in (profile, size, aspect)) > 1:
        raise ValueError("Pass at most one of --profile, --size, --aspect")

    if profile == "production":
        w, h = PRODUCTION_SIZE
        return InputSpec(w, h, is_native_aspect=False, description="production (512x896, pinned)")

    if profile in ("half", "third"):
        divisor = 2 if profile == "half" else 3
        w = _align_up(round(src_w / divisor))
        h = _align_up(round(src_h / divisor))
        return InputSpec(w, h, is_native_aspect=True, description=f"{profile} of native, stride-aligned")

    if profile is not None:
        raise ValueError(f"Unknown profile: {profile!r} (expected production, half, third)")

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

    # Default: native size, stride-aligned.
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
