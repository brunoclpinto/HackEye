"""Worldmap helpers: per-frame inputs and settings read from a stored hazards dict, and the face-contact shortcut."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import numpy.typing as npt

    from engine.worldmap.observer import Observer

__all__ = ["face_contact_samples", "first_depth_scale", "frames_from_hazards", "settings_from_hazards"]


def face_contact_samples(
    observer: Observer, grid: npt.NDArray[Any], dmap: Any, depth_scale: Any, horizon: float
) -> Any:
    """v26.2.7: (depth m, lens ground z m) of the face-class bases that stand on a surface (see
    ``Observer.face_contact_samples``)."""
    return observer.face_contact_samples(grid, dmap, depth_scale, horizon)


def frames_from_hazards(hazards: dict[str, Any]) -> list[dict[str, Any]]:
    """The per-frame inputs the observer needs: horizon, scales and the ego block (as stored by the collision pass)."""
    out = []
    for fr in hazards["frames"]:
        e = fr.get("ego") or {}
        out.append(
            {
                "horizon": fr["horizonY"],
                "scale": e.get("scale"),
                "depthScale": e.get("depthScale"),
                "ego": e,
                "dcorr": fr.get("depthCorrection"),
            }
        )
    return out


def first_depth_scale(frames: list[dict[str, Any]] | None) -> float | None:
    """The first known depth scale of a run (None when it has none)."""
    for f in frames or ():
        if f.get("depthScale"):
            return float(f["depthScale"])
    return None


def settings_from_hazards(hazards: dict[str, Any]) -> dict[str, Any]:
    s = hazards["settings"]
    return {
        "hfovDeg": s["hfovDeg"],
        "cameraHeightM": s["cameraHeightM"],
        "lateralOffsetM": s.get("lateralOffsetM", 0.0),
        "projection": hazards.get("projection"),
        "distanceSource": hazards.get("distanceSource", "ground"),
        "objectDistance": s.get("objectDistance", "depth"),
        "useHorizon": s.get("useHorizon", True),
    }
