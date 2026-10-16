"""Collision hazards and audio warning events from a sequence of class grids.

Model
-----
* Input is a stack of semantic class grids already mapped 1:1 onto the video
  frame (CONTRACTS.md section 1), so grid (row, col) -> normalised (y, x).
* **Flat-ground proximity.** With no depth sensor we assume obstacles stand on
  a flat floor. The lowest in-corridor pixel of an obstacle (its "contact
  point") then encodes distance: the nearer to the bottom of the frame, the
  closer. ``proximity`` is that row mapped linearly from [horizon, bottomY]
  to [0, 1]. It is a monotone proxy for distance, not metres.
* **Corridor.** Only pixels inside a trapezoid in front of the wearer count,
  so a lamp post three metres to the side is not a hazard.
* **Pinhole bearing.** Horizontal position maps to an angle through the
  camera's horizontal field of view; the angle becomes a clock position for
  speech and a stereo pan for beeps.
* **Time-to-collision** comes from the least-squares slope of proximity over a
  short window; moving obstacles need no special handling because their
  closing speed shows up in the same slope.
* **One beep stream.** Several simultaneous beepers are unintelligible for a
  listener who relies on sound. Only the most urgent hazard beeps, at that
  hazard's rate, and the beep phase carries over so switching hazards never
  produces a burst or a stutter.

Pure logic (numpy, scipy, stdlib) so it can be ported to Swift.
"""

from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy import ndimage

from common_paths import find_common_dir
from geometry import Box, iou

_4_CONNECTIVITY = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]])
LEVELS = ["none", "caution", "warning", "imminent"]
_LEVEL_RANK = {name: i for i, name in enumerate(LEVELS)}
GROUPS = ("static", "moving")


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------

@dataclass
class Corridor:
    horizon: float
    bottom_y: float
    top_width: float
    bottom_width: float
    center_x: float

    @classmethod
    def from_dict(cls, d: dict) -> "Corridor":
        return cls(float(d["horizon"]), float(d["bottomY"]), float(d["topWidth"]),
                   float(d["bottomWidth"]), float(d["centerX"]))

    def to_dict(self) -> dict:
        return {"horizon": self.horizon, "bottomY": self.bottom_y, "topWidth": self.top_width,
                "bottomWidth": self.bottom_width, "centerX": self.center_x}


@dataclass
class CollisionSettings:
    corridor: Corridor
    hfov_deg: float


def load_config(path: Path | None = None) -> dict:
    path = path or (find_common_dir() / "config" / "collision.json")
    with open(path) as f:
        return json.load(f)


def resolve_settings(config: dict, mount: str | None, hfov_deg: float | None,
                     corridor: dict | None) -> CollisionSettings:
    """Explicit corridor wins over the mount preset; None falls back to defaults."""
    if corridor is None:
        preset = config["mountPresets"][mount or config["defaultMount"]]
        corridor = preset["corridor"]
    hfov = config["defaultHfovDeg"] if hfov_deg is None else hfov_deg
    return CollisionSettings(Corridor.from_dict(corridor), float(hfov))


# --------------------------------------------------------------------------
# Geometry helpers
# --------------------------------------------------------------------------

def corridor_mask(grid_w: int, grid_h: int, c: Corridor) -> np.ndarray:
    """Boolean (H, W) mask of grid pixels whose centre lies in the trapezoid."""
    ys = (np.arange(grid_h) + 0.5) / grid_h
    xs = (np.arange(grid_w) + 0.5) / grid_w
    span = max(c.bottom_y - c.horizon, 1e-9)
    frac = np.clip((ys - c.horizon) / span, 0.0, 1.0)
    half = (c.top_width + (c.bottom_width - c.top_width) * frac) / 2.0
    row_ok = (ys >= c.horizon) & (ys <= c.bottom_y)
    col_ok = np.abs(xs[None, :] - c.center_x) <= half[:, None]
    return col_ok & row_ok[:, None]


def bearing_deg(x_norm: float, hfov_deg: float) -> float:
    """Pinhole model: atan((x - 0.5) * 2 * tan(hfov / 2)); positive = right."""
    t = math.tan(math.radians(hfov_deg) / 2.0)
    return math.degrees(math.atan((x_norm - 0.5) * 2.0 * t))


def clock_from_bearing(bearing: float) -> int:
    """12 + round(bearing / 30), clamped to +-90 deg, as 9..12 and 1..3."""
    b = max(-90.0, min(90.0, bearing))
    k = int(math.floor(b / 30.0 + 0.5))
    if k == 0:
        return 12
    return 12 + k if k < 0 else k


def _pan_from_bearing(bearing: float) -> float:
    return max(-1.0, min(1.0, math.sin(math.radians(bearing))))


# --------------------------------------------------------------------------
# Per-frame detection
# --------------------------------------------------------------------------

@dataclass
class _Detection:
    group: str
    class_name: str
    bbox: list[float]
    contact_y: float
    proximity: float
    bearing: float
    clock: int
    pan: float
    area_frac: float


def _resolve_class_ids(config: dict, class_names: list[str]) -> dict[str, np.ndarray]:
    index = {n: i for i, n in enumerate(class_names)}
    out: dict[str, np.ndarray] = {}
    for group in GROUPS:
        ids = []
        for name in config["obstacleClasses"].get(group, []):
            if name in index:
                ids.append(index[name])
            else:
                print(f"[collision] unknown obstacle class '{name}' skipped", file=sys.stderr)
        out[group] = np.array(ids, dtype=np.int64)
    return out


def _detect_frame(grid: np.ndarray, ids_by_group: dict[str, np.ndarray], inside: np.ndarray,
                  class_names: list[str], s: CollisionSettings,
                  min_pixels: float) -> list[_Detection]:
    h, w = grid.shape
    c = s.corridor
    dets: list[_Detection] = []
    for group in GROUPS:
        ids = ids_by_group[group]
        if ids.size == 0:
            continue
        mask = np.isin(grid, ids) & inside
        if not mask.any():
            continue
        labels, n = ndimage.label(mask, structure=_4_CONNECTIVITY)
        for sl, comp_id in zip(ndimage.find_objects(labels), range(1, n + 1)):
            rows, cols = np.nonzero(labels[sl] == comp_id)
            count = rows.size
            if count < min_pixels:
                continue
            rows = rows + sl[0].start
            cols = cols + sl[1].start
            majority = int(np.bincount(grid[rows, cols]).argmax())
            contact_y = (rows.max() + 1) / h
            span = max(c.bottom_y - c.horizon, 1e-9)
            proximity = min(1.0, max(0.0, (contact_y - c.horizon) / span))
            mean_x = (cols.mean() + 0.5) / w
            bearing = bearing_deg(mean_x, s.hfov_deg)
            dets.append(_Detection(
                group=group, class_name=class_names[majority],
                bbox=[cols.min() / w, rows.min() / h, (cols.max() + 1) / w, (rows.max() + 1) / h],
                contact_y=contact_y, proximity=proximity, bearing=bearing,
                clock=clock_from_bearing(bearing), pan=_pan_from_bearing(bearing),
                area_frac=count / (h * w)))
    return dets


# --------------------------------------------------------------------------
# Tracking
# --------------------------------------------------------------------------

@dataclass
class _Track:
    id: int
    group: str
    box: Box
    last_seen_t: float
    history: list[tuple[float, float]] = field(default_factory=list)
    spoken_rank: int = 0
    last_spoken_t: float | None = None


def _box(bbox: list[float]) -> Box:
    return Box(*bbox)


def _match(tracks: dict[int, _Track], dets: list[_Detection], iou_min: float) -> dict[int, int]:
    """Greedy IoU, same group only, best pair first. Returns {det index: track id}."""
    pairs = []
    for tid, tr in tracks.items():
        for di, d in enumerate(dets):
            if d.group != tr.group:
                continue
            v = iou(tr.box, _box(d.bbox))
            if v >= iou_min:
                pairs.append((v, tid, di))
    pairs.sort(key=lambda p: -p[0])
    used_t: set[int] = set()
    result: dict[int, int] = {}
    for _, tid, di in pairs:
        if tid in used_t or di in result:
            continue
        used_t.add(tid)
        result[di] = tid
    return result


def _ttc(history: list[tuple[float, float]], now: float, window: float) -> float | None:
    """(1 - p) / slope of the least-squares line over the window, else None."""
    pts = [(t, p) for t, p in history if t >= now - window - 1e-9]
    if len(pts) < 2:
        return None
    t = np.array([q[0] for q in pts])
    p = np.array([q[1] for q in pts])
    tc = t - t.mean()
    denom = float((tc * tc).sum())
    if denom <= 0:
        return None
    slope = float((tc * (p - p.mean())).sum() / denom)
    if slope <= 1e-9:
        return None
    return max(0.0, (1.0 - float(p[-1])) / slope)


def _urgency(group_rules: dict, proximity: float, ttc: float | None) -> str:
    level = "none"
    for name in LEVELS[1:]:
        rule = group_rules[name]
        by_prox = proximity >= rule["proximity"]
        by_ttc = ttc is not None and rule.get("ttc") is not None and ttc <= rule["ttc"]
        if by_prox or by_ttc:
            level = name
    return level


# --------------------------------------------------------------------------
# Speech and tones
# --------------------------------------------------------------------------

def _pick_most_urgent(items: list[dict]) -> dict:
    return max(items, key=lambda h: (_LEVEL_RANK[h["urgency"]], h["proximity"]))


def _speech_event(frame_hazards: list[dict], tracks: dict[int, _Track], t: float,
                  speech_cfg: dict, state: dict) -> dict | None:
    """Apply the escalation / cooldown / global-gap rules for one frame.

    Every hazard whose level rose past what it last spoke at is "consumed"
    (its spoken rank advances) even if it loses the tie-break or is muted:
    the contract says suppressed speech is dropped, not delayed.
    """
    candidates = []
    for h in frame_hazards:
        tr = tracks[h["trackId"]]
        rank = _LEVEL_RANK[h["urgency"]]
        tr.spoken_rank = min(tr.spoken_rank, rank)  # allow re-announcing after a drop
        if rank > tr.spoken_rank:
            tr.spoken_rank = rank
            imminent = h["urgency"] == "imminent"
            cooled = tr.last_spoken_t is None or t - tr.last_spoken_t >= speech_cfg["trackCooldownSeconds"]
            if cooled or imminent:
                candidates.append(h)
    if not candidates:
        return None
    best = _pick_most_urgent(candidates)
    gap_ok = state["last_t"] is None or t - state["last_t"] >= speech_cfg["globalMinGapSeconds"]
    if not (gap_ok or best["urgency"] == "imminent"):
        return None
    state["last_t"] = t
    tracks[best["trackId"]].last_spoken_t = t
    return {"t": round(t, 4), "type": "speech", "trackId": best["trackId"],
            "text": best["_text"], "urgency": best["urgency"],
            "clock": best["clock"], "pan": best["pan"]}


def _tone_events(frames: list[list[dict]], times: np.ndarray, tones_cfg: dict) -> list[dict]:
    """Single phase-continuous beep stream (see module docstring)."""
    if len(times) > 1:
        last_dt = float(np.median(np.diff(times)))
    else:
        last_dt = 1.0
    events: list[dict] = []
    next_due = -math.inf
    last_beep = -math.inf
    for i, hazards in enumerate(frames):
        active = [h for h in hazards if h["urgency"] != "none"]
        if not active:
            continue
        t0 = float(times[i])
        t1 = float(times[i + 1]) if i + 1 < len(times) else t0 + last_dt
        top = _pick_most_urgent(active)
        interval = tones_cfg["intervalSeconds"][top["urgency"]]
        # A faster stream must not wait out the previous slower interval.
        due = max(t0, min(next_due, last_beep + interval))
        while due < t1 - 1e-9:
            events.append({"t": round(due, 4), "type": "tone", "trackId": top["trackId"],
                           "urgency": top["urgency"], "pan": top["pan"],
                           "frequencyHz": tones_cfg["frequencyHz"][top["urgency"]],
                           "durationSeconds": tones_cfg["durationSeconds"]})
            last_beep = due
            due += interval
        next_due = due
    return events


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------

def run_collision(grids, times, class_names, config, settings) -> tuple[dict, dict]:
    grids = np.asarray(grids)
    times = np.asarray(times, dtype=float)
    n, gh, gw = grids.shape
    ids_by_group = _resolve_class_ids(config, class_names)
    inside = corridor_mask(gw, gh, settings.corridor)
    min_pixels = config["minComponentFraction"] * gw * gh
    trk = config["tracking"]
    speech_cfg = config["speech"]
    labels = config.get("spokenLabels", {})

    tracks: dict[int, _Track] = {}
    next_id = 1
    speech_state = {"last_t": None}
    frames_out: list[dict] = []
    frame_hazards: list[list[dict]] = []
    events: list[dict] = []

    for i in range(n):
        t = float(times[i])
        tracks = {k: v for k, v in tracks.items() if t - v.last_seen_t <= trk["maxMissedSeconds"]}
        dets = _detect_frame(grids[i], ids_by_group, inside, class_names, settings, min_pixels)
        matches = _match(tracks, dets, trk["iouMatch"])

        hazards = []
        for di, d in enumerate(dets):
            tid = matches.get(di)
            if tid is None:
                tid, next_id = next_id, next_id + 1
                tracks[tid] = _Track(tid, d.group, _box(d.bbox), t)
            tr = tracks[tid]
            tr.box, tr.last_seen_t = _box(d.bbox), t
            tr.history.append((t, d.proximity))
            tr.history = [p for p in tr.history if p[0] >= t - trk["approachWindowSeconds"] - 1e-9]
            ttc = _ttc(tr.history, t, trk["approachWindowSeconds"])
            label = labels.get(d.class_name, d.class_name.replace("-", " "))
            hazards.append({
                "trackId": tid, "className": d.class_name, "group": d.group, "label": label,
                "bbox": [round(v, 4) for v in d.bbox], "contactY": round(d.contact_y, 4),
                "proximity": round(d.proximity, 4), "bearingDeg": round(d.bearing, 2),
                "clock": d.clock, "pan": round(d.pan, 4),
                "ttc": None if ttc is None else round(ttc, 3),
                "urgency": _urgency(config["urgency"][d.group], d.proximity, ttc),
                "areaFrac": round(d.area_frac, 5),
                "_text": speech_cfg["template"].format(label=label, clock=d.clock),
            })

        speech = _speech_event(hazards, tracks, t, speech_cfg, speech_state)
        if speech:
            events.append(speech)
        for h in hazards:
            h.pop("_text")  # internal only; keep the public shape exact
        frame_hazards.append(hazards)
        frames_out.append({"index": i, "t": round(t, 4), "hazards": hazards})

    events.extend(_tone_events(frame_hazards, times, config["tones"]))
    events.sort(key=lambda e: (e["t"], e["type"] != "speech"))

    version = config["version"]
    hazards_doc = {
        "version": version,
        "settings": {"corridor": settings.corridor.to_dict(), "hfovDeg": settings.hfov_deg,
                     "mount": None},
        "gridW": gw, "gridH": gh, "frames": frames_out,
    }
    return hazards_doc, {"version": version, "events": events}
