"""Constants of the analysis runs (moved verbatim from lab/analysis.py; `analysis.<NAME>` forwards here)."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import profiles

GRID_W = 240
NO_DATA = 255  # grid cell outside the analysed window of a portrait run (collision.NO_DATA)
ANALYSIS_VERSION = (
    3  # 3: motion.npz adds `resid` (v26.1.11); 2: ego-motion track (motion.npz); v26.1.0 runs are implicitly 1
)
PROFILES = ["default", "production", "half", "quarter"]  # legacy names, still accepted
RESOLUTIONS = [f"{n}p" for n in profiles.SHORT_SIDE_OPTIONS]  # what the UI offers
IDLE_SECONDS = float(os.environ.get("HACKEYE_LAB_IDLE_SECONDS", "300"))
RUN_ID_RE = re.compile(r"^[0-9a-f]{12}$")
DEPTH_MODELS = ("none", "da3-small", "da3-base", "da2-metric-outdoor-small", "unidepth-v2-s")
# anchor mode of each depth variant (collision.run_collision depth["anchor"])
DEPTH_ANCHOR = {
    "da3-small": "per-frame",
    "da3-base": "per-frame",
    "da2-metric-outdoor-small": "plane",
    "unidepth-v2-s": "none",
}
# One-off: DA2 runs analysed before the default became "plane" stored anchor "initial" in depth.npz.
# The npz value normally beats the variant table, but these superseded values are ignored so a
# collision re-run of an old DA2 run uses the current default.
SUPERSEDED_ANCHORS = {"da2-metric-outdoor-small": {"initial"}}
DEPTH_W, DEPTH_H = 120, 68  # stored depth map size (CONTRACTS depth.npz)
DEPTH_MIN_REL = 1e-3  # floor for relative depth (non-finite / <= 0 become nan)
DEPTH_MIN_M, DEPTH_MAX_M = 0.1, 200.0  # clip range for metric depth (metres)
DEFAULT_MODEL = os.environ.get("HACKEYE_LAB_DEFAULT_MODEL", "Yolo26m-sem-HackEye26.1-48-1280.pt")
MODEL_DIRS = [
    (Path(os.environ.get("HACKEYE_MODELS_DIR", "/models")), "*.pt"),
    (Path(os.environ.get("HACKEYE_RELEASES_DIR", "/hackeye-models")), "*HackEye*.pt"),
]
