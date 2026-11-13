"""Camera lens + per-frame ground geometry: ``Geometry`` ray/ground maths and the ``FrameGeo`` of one collision
frame."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

import numpy as np
import numpy.typing as npt
from scipy import ndimage

from engine.core.geom import ground_distance_m, lateral_m

if TYPE_CHECKING:
    from engine.core.settings import CollisionSettings

__all__ = [
    "FrameGeo",
    "Geometry",
    "bottom_point",
    "ego_frame",
    "frame_geometry",
    "ground_dist",
    "ground_m",
    "ground_pixel",
    "ground_point",
    "ground_z",
    "lateral_at",
    "lateral_of",
    "pitch",
    "ray_dir",
    "walking_axis_offset_m",
]


_A = npt.NDArray[np.float64]
_F = float | _A
_FF = tuple[_A, _A]


class _HasMask(Protocol):
    """The part of the collision ``Region`` that ``frame_geometry`` reads."""

    mask: npt.NDArray[np.bool_]


class Geometry:
    """Lens + camera: grid size, HFOV, projection ("fisheye" equidistant or "rectilinear"), camera height (m, without
    any gait scale)."""

    def __init__(self, gh: int, gw: int, hfov_deg: float, projection: str, cam_h: float):
        self.gh, self.gw, self.hfov = gh, gw, float(hfov_deg)
        self.fisheye, self.cam_h = projection == "fisheye", float(cam_h)
        self.f_eq = gw / math.radians(self.hfov)
        self.f_pin = (gw / 2.0) / math.tan(math.radians(self.hfov) / 2.0)
        # v26.2.11 (``ego.rollCorrect``): the camera roll (rad, + = right side down) the geometry undoes; set per frame
        self.roll = 0.0


def pitch(geo: Geometry, horizon: float) -> float:
    """The camera pitch (rad, + = looking down) the horizon row implies: the ray of the horizon row on the centre
    column is level."""
    off = geo.gh / 2.0 - horizon * geo.gh
    return off / geo.f_eq if geo.fisheye else math.atan(off / geo.f_pin)


def ray_dir(geo: Geometry, row_b: _F, col_c: _F) -> _FF:
    """(xn, yn): the normalised camera ray (x right, y down, z = 1 along the optical axis) of grid position
    (``row_b`` row coordinate, ``col_c`` column coordinate, floats, pixel centres at +0.5): the equidistant
    fisheye's or the pinhole's. nan where a fisheye ray points (almost) sideways or backwards."""
    row_b, col_c = np.broadcast_arrays(np.asarray(row_b, dtype=np.float64), np.asarray(col_c, dtype=np.float64))
    px, py = col_c - geo.gw / 2.0, row_b - geo.gh / 2.0
    if geo.roll:  # the pixel as a level camera would see it
        cr, sr = math.cos(geo.roll), math.sin(geo.roll)
        px, py = px * cr - py * sr, px * sr + py * cr
    if geo.fisheye:
        r = np.hypot(px, py)
        theta = r / geo.f_eq
        ct = np.cos(theta)
        with np.errstate(divide="ignore", invalid="ignore"):
            k = np.where(r > 0, np.tan(theta) / np.maximum(r, 1e-12), 1.0 / geo.f_eq)
        xn, yn = k * px, k * py
        ok = ct > 1e-3
        return np.where(ok, xn, np.nan), np.where(ok, yn, np.nan)
    return px / geo.f_pin, py / geo.f_pin


def ground_z(geo: Geometry, row_b: _F, col_c: _F, horizon: float, cam_h: float | None = None) -> _A:
    """z-depth (m, along the optical axis) of the ground point seen at grid position (``row_b`` row coordinate,
    ``col_c`` column coordinate, both float, pixel centres at +0.5), for a flat floor ``cam_h`` (default
    ``geo.cam_h``) below the camera and the horizon at ``horizon`` (fraction of the height; it fixes the pitch:
    the ray of the horizon row on the centre column is level). nan above the horizon."""
    _xn, yn = ray_dir(geo, row_b, col_c)
    phi = pitch(geo, horizon)
    h = geo.cam_h if cam_h is None else float(cam_h)
    down = yn * math.cos(phi) + math.sin(phi)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(down > 1e-4, h / down, np.nan)


def ground_point(geo: Geometry, row_b: _F, col_c: _F, horizon: float, cam_h: float | None = None) -> _FF:
    """v26.2.7: the floor point seen at grid position (``row_b``, ``col_c``): (forward m, right m) in the level frame of
    the camera (the horizon's pitch removed; camera axis, no body offset). forward = z (cos phi - yn sin phi), right =
    xn z. nan above the horizon. This is the ONE lens ground geometry of the map's surfaces, the object bases and the
    items (the collision pass's old pinhole formulas are 1.2 - 1.8 times off on the 118 deg fisheye)."""
    xn, yn = ray_dir(geo, row_b, col_c)
    z = ground_z(geo, row_b, col_c, horizon, cam_h)
    phi = pitch(geo, horizon)
    return z * (math.cos(phi) - yn * math.sin(phi)), xn * z


def ground_pixel(geo: Geometry, fwd: _F, right: _F, horizon: float, cam_h: float | None = None) -> _FF:
    """v26.2.7: the exact inverse of ``ground_point``: the float grid position (row coordinate, column coordinate) that
    sees the floor point (``fwd`` m forward, ``right`` m right). nan where the point is not in front of the camera."""
    fwd, right = np.broadcast_arrays(np.asarray(fwd, dtype=np.float64), np.asarray(right, dtype=np.float64))
    phi = pitch(geo, horizon)
    h = geo.cam_h if cam_h is None else float(cam_h)
    cp, sp = math.cos(phi), math.sin(phi)
    z = fwd * cp + h * sp
    y = h * cp - fwd * sp
    with np.errstate(divide="ignore", invalid="ignore"):
        ok = z > 1e-6
        xn, yn = np.where(ok, right / z, np.nan), np.where(ok, y / z, np.nan)
        if geo.fisheye:
            rho = np.hypot(xn, yn)
            r = np.arctan(rho) * geo.f_eq
            k = np.where(rho > 0, r / np.maximum(rho, 1e-12), geo.f_eq)
            px, py = k * xn, k * yn
        else:
            px, py = xn * geo.f_pin, yn * geo.f_pin
    if geo.roll:  # back into the rolled camera's image
        cr, sr = math.cos(geo.roll), math.sin(geo.roll)
        px, py = px * cr + py * sr, -px * sr + py * cr
    return py + geo.gh / 2.0, px + geo.gw / 2.0


def lateral_at(geo: Geometry, row_b: _F, col_c: _F, fwd: _F, horizon: float) -> _A:
    """v26.2.7: the right offset (m, camera axis) of the pixel's ray at the forward distance ``fwd``: xn fwd / (cos
    phi - yn sin phi)."""
    xn, yn = ray_dir(geo, row_b, col_c)
    phi = pitch(geo, horizon)
    with np.errstate(divide="ignore", invalid="ignore"):
        return xn * np.asarray(fwd, dtype=np.float64) / (math.cos(phi) - yn * math.sin(phi))


def ground_m(
    geo: Geometry, row_b: _F, col_c: _F, horizon: float, rep: dict[str, float] | None, sigma_rows: float | None = None
) -> tuple[_A, _A | None]:
    """The ground ray in depth metres, ``ref x ground_z`` (nan without ``ref``). With ``sigma_rows``: also its
    1-sigma (m) from a base-row error."""
    z = ground_z(geo, row_b, col_c, horizon)
    if rep is None:
        return np.full_like(z, np.nan), np.full_like(z, np.nan)
    q = float(rep["ref"])
    if sigma_rows is None:
        return q * z, None
    hi = ground_z(geo, np.asarray(row_b) - sigma_rows, col_c, horizon)
    lo = ground_z(geo, np.asarray(row_b) + sigma_rows, col_c, horizon)
    with np.errstate(invalid="ignore"):
        sg = np.where(np.isnan(hi), np.abs(q * z - q * lo), np.abs(hi - lo) / 2.0 * q)
    return q * z, sg


@dataclass
class FrameGeo:
    """Everything derived from the horizon, shared by all items of one frame."""

    gh: int
    gw: int
    f: float
    horizon: float
    camera_height_m: float
    hfov_deg: float
    projection: str
    below: npt.NDArray[np.bool_]  # (H,) rows whose bottom edge is below the horizon
    lane: npt.NDArray[np.bool_]  # (H, W) danger lane
    lane_region: npt.NDArray[np.bool_]  # lane within the dilated walking region
    region_dilated: npt.NDArray[np.bool_]  # (H, W)
    floor_below: npt.NDArray[np.bool_]  # (H, W) True where the pixel below is walking region
    # walking axis relative to the camera axis (+ = right), see walking_axis_offset_m
    lateral_offset_m: float = 0.0
    # v26.2.7: the lens ground geometry of a fisheye run (None = the pinhole formulas, exact there)
    lens: Geometry | None = None


def walking_axis_offset_m(settings: CollisionSettings, heading_deg: float | None = None) -> float:
    """Lateral position (m, + = right) of the camera relative to the body centre line that the danger lane,
    the collision-course test and the reported laterals are centred on.

    The ONE place the lane's direction is decided. Today the lane runs straight along the camera's optical axis,
    shifted by the mounting side offset. With head or glasses mounting the camera heading differs from the
    walking direction when the head turns; a body heading (IMU) is meant to replace this (``heading_deg`` is the
    future hook: the body-vs-camera yaw), and only this function has to change."""
    return float(getattr(settings, "lateral_offset_m", 0.0))


def frame_geometry(
    gh: int,
    gw: int,
    horizon: float,
    camera_height_m: float,
    f: float,
    hfov_deg: float,
    lane_half_m: float,
    region: _HasMask | None,
    margin_px: int,
    projection: str = "rectilinear",
    lateral_offset_m: float = 0.0,
    lens_ground: bool = True,
) -> FrameGeo:
    rows_bottom = (np.arange(gh) + 1.0) / gh
    below = rows_bottom > horizon + 1e-9
    # half width of the lane in px at each row = lane_half * f / distance
    half_px = np.where(below, lane_half_m * (rows_bottom - horizon) * gh / camera_height_m, -1.0)
    col_c = np.arange(gw) + 0.5 - gw / 2.0
    if lateral_offset_m:
        # body lateral = camera lateral + offset; lane = |body lateral| <= half:
        # its centre sits -offset*f/d px from the axis
        shift_px = np.where(below, lateral_offset_m * (rows_bottom - horizon) * gh / camera_height_m, 0.0)
        lane = np.abs(col_c[None, :] + shift_px[:, None]) <= half_px[:, None]
    else:
        lane = np.abs(col_c)[None, :] <= half_px[:, None]
    if region is not None:
        dil = (
            ndimage.binary_dilation(
                region.mask, structure=ndimage.generate_binary_structure(2, 1), iterations=max(1, margin_px)
            )
            if margin_px > 0
            else region.mask
        )
    else:
        dil = np.zeros((gh, gw), dtype=bool)
    floor = np.zeros((gh, gw), dtype=bool)
    if region is not None:
        floor[:-1] = region.mask[1:]
    # v26.2.7: the lens ground geometry of a fisheye run with depth distances. (Ground-distance runs keep the pinhole
    # formulas: their gait scale k, fitted on pinhole closings, already absorbs the lens factor; correcting the distance
    # as well would apply it twice.)
    lens = (
        Geometry(gh, gw, hfov_deg, projection, camera_height_m) if (projection == "fisheye" and lens_ground) else None
    )
    return FrameGeo(
        gh,
        gw,
        f,
        horizon,
        camera_height_m,
        hfov_deg,
        projection,
        below,
        lane,
        lane & dil,
        dil,
        floor,
        lateral_offset_m,
        lens,
    )


def ground_dist(geo: FrameGeo, y_norm: float, col: float) -> float | None:
    """Forward distance (m) of the floor point seen at the bottom edge ``y_norm`` (fraction of the grid height) of image
    column ``col``; None at or above the horizon. v26.2.7: on a fisheye run through the lens (``ground_point``, 1.2 -
    1.8 times the old pinhole value on the 118 deg lens); on a rectilinear run the pinhole formula (exact there,
    unchanged)."""
    if geo.lens is None:
        return ground_distance_m(y_norm, geo.horizon, geo.camera_height_m, geo.gh, geo.f)
    fwd = float(ground_point(geo.lens, y_norm * geo.gh, col + 0.5, geo.horizon)[0])
    return fwd if math.isfinite(fwd) and fwd > 0.0 else None


def lateral_of(geo: FrameGeo, row: float, col: float, dist: float) -> float:
    """Camera-axis lateral (m, + right) of the pixel ``col`` at forward distance ``dist``; ``row`` = its bottom edge
    (row coordinate). v26.2.7: through the lens on a fisheye run, the pinhole formula on a rectilinear one."""
    if geo.lens is None:
        return lateral_m((col + 0.5) / geo.gw, dist, geo.gw, geo.f)
    return float(lateral_at(geo.lens, row, col + 0.5, dist, geo.horizon))


def bottom_point(
    rows: npt.NDArray[np.int_], cols: npt.NDArray[np.int_], sel: npt.NDArray[np.bool_], gw: int
) -> tuple[int, int]:
    """Lowest selected pixel; on that row the column nearest the image centre."""
    r = rows[sel].max()
    on_row = sel & (rows == r)
    c_all = cols[on_row]
    c = int(c_all[np.argmin(np.abs(c_all + 0.5 - gw / 2.0))])
    return int(r), c


def ego_frame(pose: tuple[float, float, float], x: float, y: float) -> tuple[float, float]:
    """World (x, y) -> (forward, right) metres of the pose (x, y, heading deg)."""
    th = math.radians(pose[2])
    s_, c_ = math.sin(th), math.cos(th)
    dx, dy = x - pose[0], y - pose[1]
    return dx * s_ + dy * c_, dx * c_ - dy * s_
