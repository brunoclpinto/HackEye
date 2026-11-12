"""v26.3.0 equivalence oracle: record what the Lab computes today, compare any later checkout against it.

The Lab (``src/collision.py run_collision``, ``src/worldmap.py``, ``src/worldtracks.py``, the ``lab/`` API) is
refactored into packages over many tasks and its behaviour must not change. This tool

* ``capture``: runs every review fixture window (``tests/fixtures/*.npz``) through the pipeline in several modes (see
  ``MODES``) with the REAL, unpatched ``collision.json`` / ``worldmap.json`` (no conftest patches: the work runs in
  spawned worker processes that never load tests/conftest.py), plus a Lab API session (FastAPI TestClient on a
  temporary LAB_DIR built from a fixture), and writes the outputs to tests/fixtures/equivalence/ (xz JSON + npz).
* ``compare``: reruns the same cases on the current checkout and checks them against that corpus (``Tolerances``,
  README next to the corpus). Exit status is non-zero on any violation; ``--report`` writes the drift report.

Run inside the rnd image from ``RnD/``::

    docker compose run --rm --entrypoint python rnd tools/equivalence.py capture --out tests/fixtures/equivalence
    docker compose run --rm --entrypoint python rnd tools/equivalence.py compare [--quick] [--report /tmp/drift]

Determinism: every case runs in a spawned worker with ``CUDA_VISIBLE_DEVICES=""``, single-threaded BLAS / OpenCV,
fixed seeds, no network. Timing is never recorded (worldmap ``ms``, ``collision.LAST_WORLD_TRACKS_MS``, elapsed / ``ms``
fields are VOLATILE or left out). Bulky polygons (``GEOM_KEYS``) are stored as digests (vertex count, per-column
mean / min / max, shoelace area, index-weighted mean) to keep the corpus small; everything else is stored in
full, floats rounded to 3 decimals (tolerance floor 1e-3).
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import importlib
import io
import json
import lzma
import math
import multiprocessing
import os
import random
import re
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeAlias

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence

import numpy as np
import numpy.typing as npt

RND = Path(__file__).resolve().parents[1]
FIXTURES = RND / "tests" / "fixtures"
DEFAULT_CORPUS = FIXTURES / "equivalence"
FORMAT = 1

Json = Any
Array: TypeAlias = npt.NDArray[Any]

# --- what is compared ------------------------------------------------------------------------------------------------

#: Keys excluded from every comparison, at any depth: wall-clock, timing, paths, versions (a version bump is not drift).
VOLATILE: frozenset[str] = frozenset(
    {
        "createdAt",
        "updatedAt",
        "builtAt",
        "savedAt",
        "exportedAt",
        "closedAt",
        "noteUpdatedAt",
        "baseUpdatedAt",
        "since",
        "lastWipe",
        "elapsedSeconds",
        "msMean",
        "msP95",
        "msPerFrame",
        "depthMsPerFrame",
        "ms",
        "path",
        "file",
        "mtime",
        "size",
        "version",
        "collisionVersion",
        "worldmapVersion",
        "analysisVersion",
    }
)

#: Keys holding bulky polygons / point lists, stored as digests (``_digest``).
GEOM_KEYS: frozenset[str] = frozenset(
    {"outline", "outlineFull", "faceEdge", "faceEdgeLines", "lane", "rows", "corridor"}
)

WM_STRIDE = 24  # default mode: worldmap frames kept (class grid + conf): every WM_STRIDE-th and the last
WM_LITE_SAMPLES = 3  # the other worldmap modes: class grid only, this many frames per window
LITE_FRAME_KEYS = ("index", "t", "horizonY", "horizonEstimated", "pathChange", "ego")
LITE_HAZARD_KEYS = (
    "trackId",
    "className",
    "label",
    "role",
    "urgency",
    "distanceM",
    "stepsTo",
    "bearingDeg",
    "clock",
    "clockText",
    "collision",
    "moving",
    "closingMps",
    "source",
    "lateralM",
)
LITE_TRACK_KEYS = ("id", "class", "state", "x", "y", "speedMps", "cpaM", "onCourse", "ttcS")
LONG_WINDOW_S = 40.0  # windows longer than this run in the default mode only
NDIGITS = 3
EVENT_TIME_KEYS = ("t", "tEnd")
EVENT_EXACT_KEYS = ("type", "text", "role", "label")


@dataclass(frozen=True)
class Tolerances:
    abs_floor: float = 1e-3  # |a-b| <= max(abs_floor, rel * |a|) + 1e-9
    rel: float = 1e-4
    event_frames: float = 1.0  # event times: +- this many analysed frames
    wm_class_min_same: float = 0.999
    wm_conf: float = 1e-3  # on conf / 255, cells whose class matches


TOL = Tolerances()

# --- modes -----------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Mode:
    name: str
    collision: dict[str, Any] = field(default_factory=dict)  # dotted-key overrides of collision.json
    object_distance: str | None = None  # None: the fixture's own setting / the config default
    sensors: bool = True  # pass the fixture's sensors when it has them
    needs_depth: bool = False
    needs_sensors: bool = False
    v2629: bool = False  # worldtracks fixtures: person split off + v26.2.9 map settings
    worldmap: str = ""  # "full" (conf too, strided), "lite" (class grid, 3 frames), "" none
    full: bool = False  # full hazards / world tracks record; else the decision fields only
    only: tuple[str, ...] = ()  # restrict to these fixtures (empty: all)


# v26.2.9 map behaviour (tests/conftest.py _V2629_MAP) used by the worldtracks fixtures (tests/worldtracks_fixtures.py)
V2629_MAP: dict[str, Any] = {
    "decay": "time",
    "conflictFactor": 1.0,
    "voteCap": 0.0,
    "poseAlign": False,
    "gapCloseM": 0.5,
    "faceThicknessM": 0.3,
}
WT_NAMES = (
    "4929_review1",
    "4929_review2",
    "4929_review3",
    "4929_review4",
    "chest0002_crosswalk",
    "chest0004_review7",
    "chest0004_review8",
)

MODES: dict[str, Mode] = {
    m.name: m
    for m in (
        Mode("default", worldmap="full", full=True),
        Mode("image", collision={"source.mode": "image"}, worldmap="lite"),
        Mode("depth", object_distance="depth", needs_depth=True),
        Mode("ground", object_distance="ground-contact"),
        Mode("ground+depth", object_distance="ground+depth", needs_depth=True, worldmap="lite"),
        Mode("nopred", collision={"speech.predictive.enabled": False}),
        Mode("onepose_on", collision={"ego.onePose": "on"}, worldmap="lite"),
        Mode("onepose_off", collision={"ego.onePose": "off"}),
        Mode("nosensors", sensors=False, needs_sensors=True),
        Mode(
            "wt_depth",
            object_distance="depth",
            needs_depth=True,
            v2629=True,
            sensors=False,
            only=WT_NAMES,
            worldmap="lite",
        ),
        Mode(
            "wt_ground+depth",
            object_distance="ground+depth",
            needs_depth=True,
            v2629=True,
            sensors=False,
            only=WT_NAMES,
        ),
    )
}

QUICK_WINDOWS = (("chest0002_crosswalk", "w2"), ("chest0004_review9", "w0"), ("4929_review4", "w0"))
QUICK_MODES = ("default", "image", "ground+depth")
API_FIXTURE = ("chest0004_review9", "w0")
API_KEY = "labapi"


@dataclass(frozen=True)
class Spec:
    fixture: str
    window: str
    mode: str

    @property
    def key(self) -> str:
        return f"{self.fixture}/{self.window}/{self.mode}"


def _meta(fixture: str) -> dict[str, Any]:
    with open(FIXTURES / f"{fixture}.json") as f:
        meta: dict[str, Any] = json.load(f)
    return meta


def fixture_names() -> list[str]:
    return sorted(
        p.stem for p in FIXTURES.glob("*.json") if (FIXTURES / f"{p.stem}.npz").exists() and "windows" in _meta(p.stem)
    )


def plan() -> tuple[list[Spec], list[dict[str, str]]]:
    """(cases to run, skipped cases with the reason) for every fixture window and mode."""
    cases: list[Spec] = []
    skipped: list[dict[str, str]] = []
    for name in fixture_names():
        meta = _meta(name)
        with np.load(FIXTURES / f"{name}.npz") as z:
            files = set(z.files)
        has_sensors = any(k.startswith("sensors_") for k in files)
        for w in meta["windows"]:
            key = str(w["key"])
            has_depth = f"{key}_depth" in files and "depth" in meta
            long_window = float(w["end"]) - float(w["start"]) > LONG_WINDOW_S
            for m in MODES.values():
                reason = ""
                if m.only and name not in m.only:
                    reason = "mode is for the worldtracks fixtures only"
                elif m.needs_depth and not has_depth:
                    reason = "fixture window has no depth maps"
                elif m.needs_sensors and not has_sensors:
                    reason = "fixture has no device sensors"
                elif long_window and m.name != "default":
                    reason = f"window longer than {LONG_WINDOW_S:g} s: default mode only (run time)"
                if reason:
                    if m.name != "default" and not (m.only and name not in m.only):
                        skipped.append({"case": Spec(name, key, m.name).key, "reason": reason})
                else:
                    cases.append(Spec(name, key, m.name))
    return cases, skipped


def quick_plan(cases: Sequence[Spec]) -> list[Spec]:
    want = {Spec(f, w, m).key for f, w in QUICK_WINDOWS for m in QUICK_MODES}
    return [c for c in cases if c.key in want]


# --- canonical form --------------------------------------------------------------------------------------------------


def _digest(v: Any) -> Any:
    """Polygon / point list -> fingerprint; anything else unchanged (rounded by the caller)."""
    if isinstance(v, list) and v:
        rows: list[list[float]] | None
        if all(isinstance(x, (int, float, np.number)) and not isinstance(x, bool) for x in v):
            rows = [[float(x)] for x in v]
        elif all(
            isinstance(x, (list, tuple)) and x and all(isinstance(y, (int, float, np.number)) for y in x) for x in v
        ):
            rows = [[float(y) for y in x] for x in v]
            if len({len(r) for r in rows}) != 1:
                rows = None
        else:
            rows = None
        if rows is not None:
            a = np.asarray(rows, dtype=np.float64)
            ramp: Array = np.arange(1, len(a) + 1, dtype=np.float64)[:, None]
            out: dict[str, Any] = {
                "_n": len(a),
                "mean": a.mean(0).tolist(),
                "min": a.min(0).tolist(),
                "max": a.max(0).tolist(),
                "ramp": ((a * ramp).sum(0) / ramp.sum()).tolist(),
            }
            if a.shape[1] == 2 and len(a) >= 3:
                out["area"] = float(0.5 * (a[:, 0] * np.roll(a[:, 1], -1) - np.roll(a[:, 0], -1) * a[:, 1]).sum())
            return canon(out)
    return v


def canon(o: Any, geom: bool = True) -> Any:
    """JSON-ready copy: numpy -> python, floats rounded to NDIGITS (NaN / inf as strings), geometry keys digested."""
    if isinstance(o, dict):
        out: dict[str, Any] = {}
        for k, v in o.items():
            ks = str(k)
            out[ks] = canon(_digest(v), False) if geom and ks in GEOM_KEYS else canon(v, geom)
        return out
    if isinstance(o, (list, tuple)):
        return [canon(v, geom) for v in o]
    if isinstance(o, np.ndarray):
        return canon(o.tolist(), geom)
    if isinstance(o, np.generic):
        return canon(o.item(), geom)
    if isinstance(o, bool) or o is None or isinstance(o, (int, str)):
        return o
    if isinstance(o, float):
        if math.isnan(o):
            return "nan"
        if math.isinf(o):
            return "inf" if o > 0 else "-inf"
        return round(o, NDIGITS)
    return str(o)


# --- comparison ------------------------------------------------------------------------------------------------------


@dataclass
class Violation:
    case: str
    path: str
    kind: str
    detail: str
    drift: float = 0.0


@dataclass
class Drift:
    count: int = 0
    max_abs: float = 0.0
    max_rel: float = 0.0
    worst_path: str = ""


@dataclass
class CaseResult:
    case: str
    status: str = "ok"  # ok | violations | missing | error
    drift: dict[str, Drift] = field(default_factory=dict)
    violations: list[Violation] = field(default_factory=list)
    n_violations: int = 0
    seconds: float = 0.0
    note: str = ""


MAX_VIOLATIONS_PER_CASE = 40
_IDX = re.compile(r"\[\d+\]")


def field_of(path: str) -> str:
    """Path with array indices removed: ``frames[12].hazards[0].distanceM`` -> ``frames[].hazards[].distanceM``."""
    return _IDX.sub("[]", path)


class Cmp:
    """One case's comparison: collects violations (capped) and the maximum drift per field."""

    def __init__(self, case: str, tol: Tolerances = TOL, frame_dt: float = 0.0) -> None:
        self.res = CaseResult(case)
        self.tol = tol
        self.dt = frame_dt

    def violate(self, path: str, kind: str, detail: str, drift: float = 0.0) -> None:
        self.res.n_violations += 1
        if len(self.res.violations) < MAX_VIOLATIONS_PER_CASE:
            self.res.violations.append(Violation(self.res.case, path, kind, detail, drift))

    def note_drift(self, path: str, a: float, b: float, limit: float) -> None:
        d = abs(a - b)
        if d == 0.0:
            return
        f = field_of(path)
        e = self.res.drift.setdefault(f, Drift())
        e.count += 1
        rel = d / abs(a) if a else float("inf")
        if d > e.max_abs:
            e.max_abs, e.worst_path = d, path
        if rel != float("inf") and rel > e.max_rel:
            e.max_rel = rel
        if d > limit:
            self.violate(path, "number", f"{a!r} -> {b!r} (|d|={d:.6g}, limit {limit:.6g})", d)

    def value(self, a: Any, b: Any, path: str, exact: bool = False, limit: float | None = None) -> None:
        """Generic tree walk: numbers within tolerance (or exact), everything else equal; VOLATILE keys are skipped."""
        if isinstance(a, dict) and isinstance(b, dict):
            for k in a.keys() | b.keys():
                if k in VOLATILE:
                    continue
                p = f"{path}.{k}" if path else str(k)
                if k not in b:
                    self.violate(p, "missing", "present in the corpus, absent now")
                elif k not in a:
                    self.violate(p, "extra", "absent in the corpus, present now")
                else:
                    self.value(a[k], b[k], p, exact, limit)
        elif isinstance(a, list) and isinstance(b, list):
            if len(a) != len(b):
                self.violate(path, "length", f"{len(a)} -> {len(b)}", abs(len(a) - len(b)))
            for i, (x, y) in enumerate(zip(a, b, strict=False)):
                self.value(x, y, f"{path}[{i}]", exact, limit)
        elif (
            isinstance(a, (int, float))
            and isinstance(b, (int, float))
            and not isinstance(a, bool)
            and not isinstance(b, bool)
        ):
            lim = (
                0.0
                if exact
                else (limit if limit is not None else max(self.tol.abs_floor, self.tol.rel * abs(a)) + 1e-9)
            )
            self.note_drift(path, float(a), float(b), lim)
        elif a != b or (type(a) is not type(b) and not (isinstance(a, (int, float)) and isinstance(b, (int, float)))):
            self.violate(path, "value", f"{_short(a)} -> {_short(b)}")

    # -- hazards: the same tracks (label, role) in every frame, then the numbers --------------------------------------
    def hazards(self, a: dict[str, Any], b: dict[str, Any], prefix: str = "hazards") -> None:
        fa, fb = a.get("frames") or [], b.get("frames") or []
        rest_a = {k: v for k, v in a.items() if k != "frames"}
        rest_b = {k: v for k, v in b.items() if k != "frames"}
        self.value(rest_a, rest_b, prefix)
        if len(fa) != len(fb):
            self.violate(f"{prefix}.frames", "length", f"{len(fa)} -> {len(fb)}")
        for i, (x, y) in enumerate(zip(fa, fb, strict=False)):
            hx, hy = x.get("hazards") or [], y.get("hazards") or []
            sx = sorted((h.get("trackId", -1), str(h.get("label")), str(h.get("role"))) for h in hx)
            sy = sorted((h.get("trackId", -1), str(h.get("label")), str(h.get("role"))) for h in hy)
            path = f"{prefix}.frames[{i}]"
            if sx != sy:
                self.violate(f"{path}.hazards", "tracks", f"track set {_short(sx)} -> {_short(sy)}")
                continue
            by_id = {h.get("trackId"): h for h in hy}
            unique = len(by_id) == len(hy)
            xs = {k: v for k, v in x.items() if k != "hazards"}
            ys = {k: v for k, v in y.items() if k != "hazards"}
            self.value(xs, ys, path)
            for j, h in enumerate(hx):
                other = by_id.get(h.get("trackId")) if unique else hy[j]
                if other is not None:
                    self.value(h, other, f"{path}.hazards[{j}]")

    # -- events: text / order / role / label exact, times +- one analysed frame ---------------------------------------
    def events(self, a: list[dict[str, Any]], b: list[dict[str, Any]], prefix: str = "events") -> None:
        ca: dict[str, int] = {}
        cb: dict[str, int] = {}
        for e in a:
            ca[str(e.get("type"))] = ca.get(str(e.get("type")), 0) + 1
        for e in b:
            cb[str(e.get("type"))] = cb.get(str(e.get("type")), 0) + 1
        if ca != cb:
            self.violate(prefix, "counts", f"event counts {ca} -> {cb}")
        if len(a) != len(b):
            self.violate(prefix, "length", f"{len(a)} -> {len(b)}")
        limit = self.tol.event_frames * self.dt
        for i, (x, y) in enumerate(zip(a, b, strict=False)):
            p = f"{prefix}[{i}]"
            for k in EVENT_EXACT_KEYS:
                if x.get(k) != y.get(k):
                    self.violate(f"{p}.{k}", "event", f"{_short(x.get(k))} -> {_short(y.get(k))} (t={x.get('t')})")
            for k in EVENT_TIME_KEYS:
                if k in x or k in y:
                    if k in x and k in y and isinstance(x[k], (int, float)) and isinstance(y[k], (int, float)):
                        self.note_drift(f"{p}.{k}", float(x[k]), float(y[k]), limit)
                    else:
                        self.violate(f"{p}.{k}", "event", f"{x.get(k)!r} -> {y.get(k)!r}")
            ra = {k: v for k, v in x.items() if k not in EVENT_EXACT_KEYS and k not in EVENT_TIME_KEYS}
            rb = {k: v for k, v in y.items() if k not in EVENT_EXACT_KEYS and k not in EVENT_TIME_KEYS}
            self.value(ra, rb, p)

    # -- worldmap -----------------------------------------------------------------------------------------------------
    def worldmap(self, a: dict[str, Array], b: dict[str, Array]) -> None:
        if a.keys() != b.keys():
            self.violate("worldmap", "keys", f"{sorted(a.keys())} -> {sorted(b.keys())}")
            return
        if a["idx"].shape != b["idx"].shape or not np.array_equal(a["idx"], b["idx"]):
            self.violate("worldmap.idx", "length", "sampled frames differ")
            return
        ca, cb = a["classes"], b["classes"]
        if ca.shape != cb.shape:
            self.violate("worldmap.classes", "shape", f"{ca.shape} -> {cb.shape}")
            return
        worst = 1.0
        conf_max = 0.0
        has_conf = "conf" in a
        for s in range(len(ca)):
            same = ca[s] == cb[s]
            frac = float(same.mean())
            worst = min(worst, frac)
            if frac < self.tol.wm_class_min_same:
                self.violate(
                    f"worldmap.classes[{int(a['idx'][s])}]",
                    "cells",
                    f"{frac * 100:.3f}% of the cells identical (need >= {self.tol.wm_class_min_same * 100:.1f}%)",
                    1.0 - frac,
                )
            if has_conf and same.any():
                conf_max = max(
                    conf_max,
                    float(np.abs(a["conf"][s][same].astype(np.float64) - b["conf"][s][same].astype(np.float64)).max())
                    / 255.0,
                )
        if worst < 1.0:
            self.res.drift["worldmap.classes"] = Drift(
                round((1 - worst) * ca[0].size), 1.0 - worst, 1.0 - worst, "worst sampled frame"
            )
        if conf_max > 0.0:
            self.res.drift["worldmap.conf"] = Drift(1, conf_max, conf_max, "max over matching cells")
            if conf_max > self.tol.wm_conf:
                self.violate(
                    "worldmap.conf", "conf", f"max |dconf|/255 = {conf_max:.6g} (limit {self.tol.wm_conf:g})", conf_max
                )
        for k, va in a.items():
            if k in ("classes", "conf", "idx"):
                continue
            x, y = np.asarray(va, dtype=np.float64), np.asarray(b[k], dtype=np.float64)
            if x.shape != y.shape:
                self.violate(f"worldmap.{k}", "shape", f"{x.shape} -> {y.shape}")
                continue
            both_nan = np.isnan(x) & np.isnan(y)
            if (np.isnan(x) != np.isnan(y)).any():
                self.violate(f"worldmap.{k}", "nan", "NaN pattern differs")
                continue
            d = np.where(both_nan, 0.0, np.abs(x - y))
            lim = np.maximum(self.tol.abs_floor, self.tol.rel * np.abs(np.where(both_nan, 0.0, x)))
            m = float(d.max()) if d.size else 0.0
            if m > 0.0:
                self.res.drift[f"worldmap.{k}"] = Drift(int((d > 0).sum()), m, m, "")
            if (d > lim).any():
                self.violate(f"worldmap.{k}", "number", f"max |d| = {m:.6g}", m)


def _short(v: Any) -> str:
    s = json.dumps(v, default=str) if not isinstance(v, str) else repr(v)
    return s if len(s) <= 160 else s[:157] + "..."


def compare_records(case: str, old: dict[str, Any], new: dict[str, Any], tol: Tolerances = TOL) -> CaseResult:
    """Compare two case records (``capture_case`` output, as JSON), plus their ``worldmap`` arrays."""
    dt = float(old.get("dt") or 0.0)
    c = Cmp(case, tol, dt)
    if old.get("nFrames") != new.get("nFrames"):
        c.violate("nFrames", "length", f"{old.get('nFrames')} -> {new.get('nFrames')}")
    c.hazards(old["hazards"], new["hazards"])
    c.value(old["worldTracks"], new["worldTracks"], "worldTracks")
    c.events(old["events"], new["events"], "events")
    c.value(old["tones"], new["tones"], "tones", limit=tol.event_frames * dt if dt else None)
    ow, nw = old.get("worldmap"), new.get("worldmap")
    if (ow is None) != (nw is None):
        c.violate("worldmap", "missing", "worldmap present in only one run")
    elif ow is not None and nw is not None:
        c.worldmap(ow, nw)
    c.res.status = "ok" if c.res.n_violations == 0 else "violations"
    return c.res


def compare_snapshots(case: str, old: dict[str, Any], new: dict[str, Any]) -> CaseResult:
    """Lab API snapshots: identical JSON (exact numbers) except the VOLATILE keys."""
    c = Cmp(case)
    c.value(old, new, "", exact=True)
    c.res.status = "ok" if c.res.n_violations == 0 else "violations"
    return c.res


# --- running the pipeline --------------------------------------------------------------------------------------------


def setup_worker() -> None:
    """Deterministic, CPU-only, offline process: called in every worker (and in-process for ``jobs=0``)."""
    os.environ.update(
        {
            "CUDA_VISIBLE_DEVICES": "",
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
            "PYTHONHASHSEED": "0",
            "HF_HUB_OFFLINE": "1",
            "WANDB_MODE": "disabled",
        }
    )
    for p in (str(RND / "src"), str(RND)):
        if p not in sys.path:
            sys.path.insert(0, p)
    try:
        cv2: Any = importlib.import_module("cv2")
        cv2.setNumThreads(1)
    except ImportError:
        pass


def _seed() -> None:
    random.seed(0)
    np.random.seed(0)


def _dotted_set(cfg: dict[str, Any], key: str, value: Any) -> None:
    node: Any = cfg
    parts = key.split(".")
    for p in parts[:-1]:
        node = node[p]
    if parts[-1] not in node:
        raise KeyError(f"unknown config key {key!r}")
    node[parts[-1]] = value


def _sensors(z: Any) -> dict[str, Array] | None:
    s = {k[len("sensors_") :]: z[k] for k in z.files if k.startswith("sensors_")}
    return s or None


def _wm_sample(arrays: dict[str, Array], full: bool) -> dict[str, Array]:
    n = len(arrays["classes"])
    if full:
        idx = sorted(set(range(0, n, WM_STRIDE)) | {n - 1}) if n else []
    else:
        idx = sorted({round(i * (n - 1) / max(WM_LITE_SAMPLES - 1, 1)) for i in range(WM_LITE_SAMPLES)}) if n else []
    ix = np.asarray(idx, dtype=np.int64)
    out: dict[str, Array] = {"idx": ix, "classes": arrays["classes"][ix]}
    if full:
        out["conf"] = arrays["conf"][ix]
    for k in ("t", "pose", "alignDeg", "alignM", "agree", "agreePrior"):
        if k in arrays:
            out[k] = np.asarray(arrays[k], dtype=np.float64)
    return out


def run_case(spec: Spec) -> dict[str, Any]:
    """Run one case on the current checkout: {"record": canonical dict, "worldmap": arrays | None, "seconds": float}."""
    setup_worker()
    _seed()
    col: Any = importlib.import_module("collision")
    wmod: Any = importlib.import_module("worldmap")
    mode = MODES[spec.mode]
    meta = _meta(spec.fixture)
    t0 = time.perf_counter()
    with np.load(FIXTURES / f"{spec.fixture}.npz") as z:
        w = spec.window
        grids, times = z[f"{w}_grids"], z[f"{w}_t"]
        motion = {"t": z[f"{w}_mt"], "dx": z[f"{w}_mdx"], "dy": z[f"{w}_mdy"]}
        if f"{w}_mresid" in z.files:
            motion["resid"] = z[f"{w}_mresid"]
        depth = None
        if f"{w}_depth" in z.files and "depth" in meta:
            d = meta["depth"]
            depth = {"t": times, "depth": z[f"{w}_depth"], "units": d["units"], "anchor": d["anchor"]}
        sensors = _sensors(z) if mode.sensors and not mode.v2629 else None
    config: dict[str, Any] = copy.deepcopy(col.load_config())
    wcfg: dict[str, Any] = copy.deepcopy(wmod.load_config())
    if mode.v2629:
        config["personSplit"]["enabled"] = False
        wcfg.update(V2629_MAP)
    for key, value in meta.get("overrides", {}).get("collision", {}).items() if not mode.v2629 else []:
        _dotted_set(config, key, value)
    for key, value in meta.get("overrides", {}).get("worldmap", {}).items() if not mode.v2629 else []:
        _dotted_set(wcfg, key, value)
    for key, value in mode.collision.items():
        _dotted_set(config, key, value)
    s = meta["settings"]
    object_distance = mode.object_distance if mode.object_distance is not None else s.get("objectDistance")
    settings = col.resolve_settings(
        config,
        s["mount"],
        s["hfovDeg"],
        s["cameraHeightM"],
        s["stepLengthM"],
        projection=s.get("projection"),
        distance_source=s.get("distanceSource", "ground"),
        user_height_m=s.get("userHeightM"),
        camera_location=s.get("cameraLocation"),
        camera_side=s.get("cameraSide"),
        object_distance=object_distance,
        use_horizon=s.get("useHorizon"),
    )
    sounds = {"kinds": {}, "speechRate": meta.get("speechRate", 1.0)}
    extra = {"sensors": sensors} if sensors is not None else {}
    with contextlib.redirect_stderr(io.StringIO()):
        doc, ev = col.run_collision(
            grids,
            times,
            meta["classNames"],
            config,
            settings,
            motion,
            depth=depth,
            sounds=sounds,
            worldmap_config=wcfg,
            **extra,
        )
    wm_arrays: dict[str, Array] | None = None
    if mode.worldmap:
        wdepth = None if depth is None else {"t": depth["t"], "depth": depth["depth"]}
        with contextlib.redirect_stderr(io.StringIO()):
            built: dict[str, Array] = wmod.build(grids, times, meta["classNames"], doc, config, wcfg, wdepth)
        wm_arrays = _wm_sample(built, mode.worldmap == "full")
    ft = [float(f["t"]) for f in doc["frames"]]
    dt = float(np.median(np.diff(ft))) if len(ft) > 1 else 0.0
    wt_frames = [f.get("worldTracks") for f in doc["frames"]]
    hz = {k: v for k, v in doc.items() if k != "worldTracksSettings"}
    if mode.full:
        hz["frames"] = [{k: v for k, v in f.items() if k != "worldTracks"} for f in doc["frames"]]
    else:  # the decision fields only (the events / tones are always complete): keeps the corpus small
        hz["frames"] = [
            {
                **{k: f[k] for k in LITE_FRAME_KEYS if k in f},
                "hazards": [{k: h[k] for k in LITE_HAZARD_KEYS if k in h} for h in f["hazards"]],
            }
            for f in doc["frames"]
        ]
        wt_frames = [
            None if w is None else [{k: t[k] for k in LITE_TRACK_KEYS if k in t} for t in w] for w in wt_frames
        ]
    events = list(ev["events"])
    record = {
        "format": FORMAT,
        "case": spec.key,
        "nFrames": len(ft),
        "dt": round(dt, 6),
        "hazards": canon(hz),
        "worldTracks": canon({"settings": doc.get("worldTracksSettings"), "frames": wt_frames}),
        "events": canon([e for e in events if e.get("type") != "tone"]),
        "tones": canon([e for e in events if e.get("type") == "tone"]),
    }
    return {"record": record, "worldmap": wm_arrays, "seconds": time.perf_counter() - t0}


# --- the Lab API session ---------------------------------------------------------------------------------------------


@contextlib.contextmanager
def _patched(pairs: list[tuple[Any, str, Any]]) -> Iterator[None]:
    saved = [(o, n, getattr(o, n)) for o, n, _ in pairs]
    try:
        for o, n, v in pairs:
            setattr(o, n, v)
        yield
    finally:
        for o, n, v in reversed(saved):
            setattr(o, n, v)


def _body(r: Any) -> Any:
    ctype = r.headers.get("content-type", "")
    if "json" in ctype:
        return r.json()
    import hashlib

    return {"_bytes": len(r.content), "_sha256": hashlib.sha256(r.content).hexdigest(), "_type": ctype}


def run_lab_api(fixture: str = API_FIXTURE[0], window: str = API_FIXTURE[1]) -> dict[str, Any]:
    """Drive the Lab API (``lab.server.app``, FastAPI TestClient) on a temporary LAB_DIR built from a fixture window,
    snapshot the answers (JSON through ``canon``; binary bodies as length + sha256); hazards.json: a few frames."""
    setup_worker()
    _seed()
    meta = _meta(fixture)
    rec_id, run_id = "rec1", "0123456789ab"
    testclient: Any = importlib.import_module("fastapi.testclient")
    recordings: Any = importlib.import_module("lab.recordings")
    analysis: Any = importlib.import_module("lab.analysis")
    reviews: Any = importlib.import_module("lab.reviews")
    server: Any = importlib.import_module("lab.server")
    win = next(x for x in meta["windows"] if x["key"] == window)
    rec = {
        "id": rec_id,
        "name": rec_id,
        "duration": float(win["end"]) + 10.0,
        "width": int(meta["srcW"]),
        "height": int(meta["srcH"]),
        "fps": 30.0,
        "chapters": [],
        "proxy": {"status": "none", "progress": 0.0, "error": None},
    }
    snap: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="equivalence-lab-") as tmp_s, np.load(FIXTURES / f"{fixture}.npz") as z:
        tmp = Path(tmp_s)
        sens = _sensors(z)
        counter = iter(range(1, 10_000))
        pairs: list[tuple[Any, str, Any]] = [
            (recordings, "LAB_DIR", tmp),
            (analysis, "LAB_DIR", tmp),
            (reviews, "LAB_DIR", tmp),
            (analysis, "_active", {}),
            (server, "_wm_cache", server.OrderedDict()),
            (server, "_hz_cache", server.OrderedDict()),
            (recordings, "get_recording", lambda i: dict(rec) if i == rec_id else None),
            (recordings, "list_recordings", lambda: [dict(rec)]),
            (recordings, "sensors_for", lambda i: sens),
            (reviews.secrets, "token_hex", lambda n=4: f"{next(counter):0{2 * n}x}"),
        ]
        with _patched(pairs):
            d = tmp / "runs" / run_id
            d.mkdir(parents=True)
            run = {
                "id": run_id,
                "request": {"recording": rec_id, "depth": meta.get("depth", {}).get("model", "")},
                "status": "done",
                "classNames": meta["classNames"],
                "createdAt": "2026-01-01T00:00:00Z",
                "gridW": meta["gridW"],
                "gridH": meta["gridH"],
                "srcW": meta["srcW"],
                "srcH": meta["srcH"],
                "frameCount": len(z[f"{window}_t"]),
            }
            (d / "run.json").write_text(json.dumps(run))
            np.savez(
                d / "grids.npz",
                grids=z[f"{window}_grids"],
                t=z[f"{window}_t"],
                index=z[f"{window}_index"] if f"{window}_index" in z.files else np.arange(len(z[f"{window}_t"])),
            )
            if f"{window}_depth" in z.files:
                np.savez(
                    d / "depth.npz",
                    depth=z[f"{window}_depth"],
                    t=z[f"{window}_t"],
                    units=np.array(meta["depth"]["units"]),
                    anchor=np.array(meta["depth"]["anchor"]),
                )
            mot = {"t": z[f"{window}_mt"], "dx": z[f"{window}_mdx"], "dy": z[f"{window}_mdy"]}
            if f"{window}_mresid" in z.files:
                mot["resid"] = z[f"{window}_mresid"]
            np.savez(d / "motion.npz", **mot)
            c = testclient.TestClient(server.app)

            def get(name: str, url: str, **kw: Any) -> Any:
                r = c.get(url, **kw)
                snap[name] = {"status": r.status_code, "body": canon(_body(r))}
                return r

            def send(name: str, method: str, url: str, body: Any = None) -> Any:
                r = c.request(method, url, json=body)
                snap[name] = {"status": r.status_code, "body": canon(_body(r))}
                return r

            get("version", "/api/version")
            get("recordings", "/api/recordings")
            s = meta["settings"]
            send(
                "put_settings",
                "PUT",
                f"/api/recordings/{rec_id}/settings",
                {
                    k: s[k]
                    for k in (
                        "mount",
                        "hfovDeg",
                        "cameraHeightM",
                        "stepLengthM",
                        "projection",
                        "distanceSource",
                        "userHeightM",
                        "cameraLocation",
                        "cameraSide",
                        "objectDistance",
                        "useHorizon",
                    )
                    if k in s
                },
            )
            get("settings", f"/api/recordings/{rec_id}/settings")
            get("config_collision", "/api/config/collision")
            get("runs", "/api/runs")
            get("runs_by_recording", f"/api/runs?recording={rec_id}")
            for n, body in (
                ("c1", {}),
                ("c2", {"overrides": {"collision": {"speech.predictive.enabled": False}}, "label": "no predictive"}),
            ):
                r = send(f"post_collision_{n}", "POST", f"/api/runs/{run_id}/collision", body)
                end = time.time() + 600
                while r.status_code == 200 and time.time() < end:
                    docs = c.get(f"/api/runs/{run_id}/collisions").json()
                    if next(x for x in docs if x["id"] == r.json()["id"])["status"] != "running":
                        break
                    time.sleep(0.05)
            get("run", f"/api/runs/{run_id}")
            get("collisions", f"/api/runs/{run_id}/collisions")
            get("collisions_compare", f"/api/runs/{run_id}/collisions/compare?a=c1&b=c2")
            t0 = float(win["start"])
            for cid in ("c1", "c2"):
                q = f"collision={cid}"
                get(f"hazards_{cid}", f"/api/runs/{run_id}/hazards", params={"from": 0.0, "to": 1.0, "collision": cid})
                get(f"frame_{cid}", f"/api/runs/{run_id}/frame?t=2.0&{q}")
                get(f"events_{cid}", f"/api/runs/{run_id}/events.json?{q}")
                r = c.get(f"/api/runs/{run_id}/hazards.json?{q}")
                doc = r.json() if r.status_code == 200 else {}
                snap[f"hazards_json_{cid}"] = {
                    "status": r.status_code,
                    "body": canon(
                        {
                            "head": {k: v for k, v in doc.items() if k != "frames"},
                            "nFrames": len(doc.get("frames", [])),
                            "frames": doc.get("frames", [])[:3] + doc.get("frames", [])[-2:],
                        }
                    ),
                }
                get(f"worldmap_{cid}", f"/api/runs/{run_id}/worldmap?{q}")
                get(f"worldmap_pose_{cid}", f"/api/runs/{run_id}/worldmap/pose.json?{q}")
                get(f"worldmap_cell_{cid}", f"/api/runs/{run_id}/worldmap/cell?i=10&col=100&row=190&{q}")
                get(f"worldmap_png_{cid}", f"/api/runs/{run_id}/worldmap/10.png?{q}")
            get("classes", f"/api/runs/{run_id}/classes")
            get("classes_png", f"/api/runs/{run_id}/frames/10/classes.png")
            get("depth_png", f"/api/runs/{run_id}/depth/10.png")
            get("sounds", "/api/sounds")
            get("display", "/api/display/safety_mapping.json")
            send("put_notes", "PUT", "/api/notes", {"text": "equivalence note", "baseUpdatedAt": None})
            get("notes", "/api/notes")
            get("issues", "/api/issues")
            for ev in json.loads((d / "collisions" / "c1" / "events.json").read_text())["events"]:
                if ev.get("type") == "speech":
                    send(
                        "post_review_verdict",
                        "POST",
                        f"/api/recordings/{rec_id}/reviews",
                        {
                            "kind": "verdict",
                            "verdict": "incorrect",
                            "note": "n",
                            "runId": run_id,
                            "collisionId": "c1",
                            "event": {k: ev[k] for k in ("t", "text", "role", "type") if k in ev},
                        },
                    )
                    break
            send(
                "post_review_added",
                "POST",
                f"/api/recordings/{rec_id}/reviews",
                {
                    "kind": "added",
                    "t": t0 + 3.0,
                    "text": "person ahead",
                    "role": "final",
                    "runId": run_id,
                    "collisionId": "c1",
                },
            )
            get("reviews", f"/api/recordings/{rec_id}/reviews")
            get("reviews_export", f"/api/reviews/export?recording={rec_id}")
    return snap


# --- corpus io -------------------------------------------------------------------------------------------------------


def _fname(key: str) -> str:
    return key.replace("/", "__").replace("+", "_")


def write_xz(path: Path, obj: Any) -> int:
    data = json.dumps(obj, separators=(",", ":"), sort_keys=True).encode()
    path.write_bytes(lzma.compress(data, preset=6))
    return path.stat().st_size


def read_xz(path: Path) -> Any:
    return json.loads(lzma.decompress(path.read_bytes()))


def save_case(out: Path, key: str, res: dict[str, Any]) -> int:
    size = write_xz(out / "cases" / f"{_fname(key)}.json.xz", res["record"])
    if res["worldmap"] is not None:
        p = out / "cases" / f"{_fname(key)}.wm.npz"
        np.savez_compressed(p, **res["worldmap"])
        size += p.stat().st_size
    return size


def load_case(corpus: Path, key: str) -> dict[str, Any] | None:
    p = corpus / "cases" / f"{_fname(key)}.json.xz"
    if not p.exists():
        return None
    rec: dict[str, Any] = read_xz(p)
    wp = corpus / "cases" / f"{_fname(key)}.wm.npz"
    if wp.exists():
        with np.load(wp) as z:
            rec["worldmap"] = {k: z[k] for k in z.files}
    return rec


def _pool(jobs: int) -> ProcessPoolExecutor | None:
    if jobs <= 0:
        return None
    return ProcessPoolExecutor(
        max_workers=jobs, mp_context=multiprocessing.get_context("spawn"), initializer=setup_worker
    )


def _run_all(
    specs: Sequence[Spec], with_api: bool, jobs: int, log: Callable[[str], None]
) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield (key, result) as cases finish. Longest windows are submitted first."""
    sizes = {n: _meta(n) for n in {s.fixture for s in specs}}

    def weight(s: Spec) -> float:
        w = next(x for x in sizes[s.fixture]["windows"] if x["key"] == s.window)
        return float(w["end"]) - float(w["start"])

    order = sorted(specs, key=weight, reverse=True)
    pool = _pool(jobs)
    if pool is None:
        for s in order:
            yield s.key, run_case(s)
        if with_api:
            yield API_KEY, {"snapshot": run_lab_api()}
        return
    with pool:
        futs = {}
        if with_api:
            futs[pool.submit(run_lab_api)] = API_KEY
        for s in order:
            futs[pool.submit(run_case, s)] = s.key
        from concurrent.futures import as_completed

        for fut in as_completed(futs):
            key = futs[fut]
            r = fut.result()
            yield key, ({"snapshot": r} if key == API_KEY else r)


def capture(out: Path, jobs: int, only: str | None = None, log: Callable[[str], None] = print) -> int:
    cases, skipped = plan()
    if only:
        cases = [c for c in cases if only in c.key]
    out.mkdir(parents=True, exist_ok=True)
    (out / "cases").mkdir(exist_ok=True)
    manifest: dict[str, Any] = {
        "format": FORMAT,
        "cases": {},
        "skipped": skipped,
        "volatile": sorted(VOLATILE),
        "geomKeys": sorted(GEOM_KEYS),
        "wmStride": WM_STRIDE,
        "numpy": np.__version__,
        "python": sys.version.split()[0],
    }
    total = 0
    t0 = time.time()
    n = 0
    for n, (key, res) in enumerate(_run_all(cases, True, jobs, log), 1):
        if key == API_KEY:
            size = write_xz(out / "labapi.json.xz", res["snapshot"])
            manifest["cases"][API_KEY] = {
                "kind": "api",
                "bytes": size,
                "fixture": API_FIXTURE[0],
                "window": API_FIXTURE[1],
            }
        else:
            size = save_case(out, key, res)
            rec = res["record"]
            manifest["cases"][key] = {
                "kind": "pipeline",
                "bytes": size,
                "nFrames": rec["nFrames"],
                "seconds": round(res["seconds"], 1),
            }
        total += size
        log(f"[{n}/{len(cases) + 1}] {key}  {size / 1024:.0f} KB  ({time.time() - t0:.0f}s)")
    manifest["totalBytes"] = total
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    log(f"captured {len(cases)} pipeline cases + the Lab API snapshot, skipped {len(skipped)}; {total / 1e6:.1f} MB")
    return 0


# --- compare + report ------------------------------------------------------------------------------------------------


@dataclass
class Report:
    results: list[CaseResult] = field(default_factory=list)
    seconds: float = 0.0
    quick: bool = False

    @property
    def ok(self) -> bool:
        return all(r.status == "ok" for r in self.results)

    def to_json(self) -> dict[str, Any]:
        def rd(r: CaseResult) -> dict[str, Any]:
            return {
                "case": r.case,
                "status": r.status,
                "note": r.note,
                "seconds": round(r.seconds, 1),
                "nViolations": r.n_violations,
                "drift": {
                    k: {
                        "count": v.count,
                        "maxAbs": v.max_abs,
                        "maxRel": None if math.isinf(v.max_rel) else v.max_rel,
                        "worstPath": v.worst_path,
                    }
                    for k, v in sorted(r.drift.items())
                },
                "violations": [
                    {"path": v.path, "kind": v.kind, "detail": v.detail, "drift": v.drift} for v in r.violations
                ],
            }

        return {
            "ok": self.ok,
            "quick": self.quick,
            "cases": len(self.results),
            "seconds": round(self.seconds, 1),
            "failed": sum(1 for r in self.results if r.status != "ok"),
            "results": [rd(r) for r in self.results],
        }

    def text(self) -> str:
        bad = [r for r in self.results if r.status != "ok"]
        verdict = "OK (no violations)" if self.ok else "FAILED"
        total = sum(r.n_violations for r in self.results)
        lines = [
            f"equivalence {'QUICK ' if self.quick else ''}compare: {len(self.results)} cases, "
            f"{len(bad)} with violations, "
            f"{total} violations, {self.seconds:.0f} s -> {verdict}"
        ]
        drifted = [r for r in self.results if r.drift]
        lines.append(f"cases with any (within-tolerance or not) drift: {len(drifted)}")
        for r in sorted(self.results, key=lambda r: (r.status == "ok", r.case)):
            if r.status == "ok" and not r.drift:
                continue
            lines.append(f"\n== {r.case}  [{r.status}]" + (f"  {r.note}" if r.note else ""))
            for k, d in sorted(r.drift.items(), key=lambda kv: -kv[1].max_abs)[:25]:
                lines.append(f"   drift {k}: max |d|={d.max_abs:.6g} n={d.count} worst {d.worst_path}")
            if r.n_violations:
                shown = f" (first {len(r.violations)} shown)" if r.n_violations > len(r.violations) else ""
                lines.append(f"   {r.n_violations} violation(s){shown}:")
                for v in r.violations:
                    lines.append(f"   - [{v.kind}] {v.path}: {v.detail}")
        return "\n".join(lines) + "\n"


def compare(
    corpus: Path = DEFAULT_CORPUS,
    quick: bool = False,
    jobs: int = 4,
    only: str | None = None,
    log: Callable[[str], None] = print,
) -> Report:
    """Rerun the corpus' cases on the current checkout and compare (``quick``: 3 windows x 3 modes + Lab API)."""
    manifest: dict[str, Any] = json.loads((corpus / "manifest.json").read_text())
    cases, _ = plan()
    cases = [c for c in cases if c.key in manifest["cases"]]
    if quick:
        cases = quick_plan(cases)
    if only:
        cases = [c for c in cases if only in c.key]
    with_api = API_KEY in manifest["cases"] and (not only or only in API_KEY)
    report = Report(quick=quick)
    t0 = time.time()
    done = {c.key for c in cases}
    for key in sorted(k for k in manifest["cases"] if k != API_KEY and k not in {c.key for c in plan()[0]}):
        if not only or only in key:
            r = CaseResult(key, "missing", note="in the corpus but no longer planned (fixture / mode removed)")
            r.n_violations = 1
            report.results.append(r)
    for key, res in _run_all(cases, with_api, jobs, log):
        ts = time.time()
        if key == API_KEY:
            old = read_xz(corpus / "labapi.json.xz")
            r = compare_snapshots(key, old, res["snapshot"])
        else:
            old_rec = load_case(corpus, key)
            if old_rec is None:
                r = CaseResult(key, "missing", note="no such case in the corpus")
                r.n_violations = 1
            else:
                new_rec = dict(res["record"])
                new_rec["worldmap"] = res["worldmap"]
                r = compare_records(key, old_rec, new_rec)
            r.seconds = float(res.get("seconds", 0.0))
        r.seconds = r.seconds or time.time() - ts
        report.results.append(r)
        done.discard(key)
    report.seconds = time.time() - t0
    return report


def write_report(report: Report, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.with_suffix(".json").write_text(json.dumps(report.to_json(), indent=1) + "\n")
    path.with_suffix(".txt").write_text(report.text())


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else "")
    sub = ap.add_subparsers(dest="cmd", required=True)
    cap = sub.add_parser("capture", help="record the corpus from the current checkout")
    cap.add_argument("--out", type=Path, default=DEFAULT_CORPUS)
    cap.add_argument("--jobs", type=int, default=min(8, os.cpu_count() or 2))
    cap.add_argument("--only", default=None, help="only cases whose key contains this text (debugging)")
    cmp_ = sub.add_parser("compare", help="compare the current checkout against the corpus")
    cmp_.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    cmp_.add_argument("--quick", action="store_true", help="3 windows x 3 modes + the Lab API session")
    cmp_.add_argument("--report", type=Path, default=None, help="drift report path (writes <path>.json and <path>.txt)")
    cmp_.add_argument("--jobs", type=int, default=min(8, os.cpu_count() or 2))
    cmp_.add_argument("--only", default=None, help="only cases whose key contains this text")
    a = ap.parse_args(argv)
    if a.cmd == "capture":
        return capture(a.out, a.jobs, a.only)
    report = compare(a.corpus, a.quick, a.jobs, a.only)
    if a.report is not None:
        write_report(report, a.report)
    print(report.text())
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
