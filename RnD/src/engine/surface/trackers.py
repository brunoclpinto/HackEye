"""Surface and crosswalk trackers over the frames of a run."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import numpy.typing as npt


class CrosswalkTracker:
    """Is the user standing on a crosswalk? (v26.1.14, ``config["crosswalk"]``).

    The signal is the share of crosswalk-class cells in the surface seed box (bottom centre of the picture, under the
    feet), so a
    crosswalk merely seen ahead never counts and a crossing that runs along the walking direction keeps counting. In:
    the share
    is >= ``enterFraction`` for ``enterSeconds`` without a break, never while the user stands still. Out: <=
    ``exitFraction`` for
    ``exitSeconds`` without a break. ``update`` returns "enter" / "exit" on the frame that decides, else None.
    """

    def __init__(self, cfg: dict[str, Any]):
        self.enter_f = float(cfg["enterFraction"])
        self.enter_s = float(cfg["enterSeconds"])
        self.exit_f = float(cfg["exitFraction"])
        self.exit_s = float(cfg["exitSeconds"])
        self.inside = False
        self._since: float | None = None  # start of the current run above the enter / below the exit level

    def update(self, t: float, fraction: float, stationary: bool) -> str | None:
        if not self.inside:
            if stationary or fraction < self.enter_f:
                self._since = None
                return None
            self._since = t if self._since is None else self._since
            if t - self._since >= self.enter_s - 1e-9:
                self.inside, self._since = True, None
                return "enter"
            return None
        if fraction > self.exit_f:
            self._since = None
            return None
        self._since = t if self._since is None else self._since
        if t - self._since >= self.exit_s - 1e-9:
            self.inside, self._since = False, None
            return "exit"
        return None


def seed_fraction(grid: npt.NDArray[np.integer[Any]], class_id: int | None, seed_box: list[float]) -> float:
    """Share of cells of ``class_id`` in the seed box (the box ``walking_region`` seeds from)."""
    if class_id is None:
        return 0.0
    gh, gw = grid.shape
    x0, y0, x1, y1 = seed_box
    box = grid[
        int(y0 * gh) : max(int(math.ceil(y1 * gh)), int(y0 * gh) + 1),  # noqa: RUF046
        int(x0 * gw) : max(int(math.ceil(x1 * gw)), int(x0 * gw) + 1),  # noqa: RUF046
    ]
    return float(np.count_nonzero(box == class_id)) / max(1, box.size)


class SurfaceTracker:
    """Surface group with strict evidence (CONTRACTS.md 15 design 4; supersedes 14.1.8).

    A change of the adopted (stable) surface needs ALL of
      * the new surface holds at least ``majority`` (70 percent) of the frames of a sliding
        ``windowSeconds`` (10 s) window (and the window spans at least ``minPersistSeconds``),
      * (kept from v26.1.6, so this is only ever stricter) it has also run without interruption for
        ``minPersistSeconds``, and
      * a curb or crosswalk edge *passed under the user* that belongs to the change: no earlier than
        ``evidenceLookbackSeconds`` (3 s) before and no later than ``evidenceLeadSeconds`` (2 s) after the new surface's
        stretch began (v26.1.11; ``note_evidence``: the driver reports it when the contact of a track that had crossed
        the
        lane for ``confirmFrames`` frames reached the bottom ``passUnderRows`` grid rows inside the lane and the track
        was gone within 1.5 s).
    Otherwise the previous surface is kept, silently: the region still follows the model frame by frame,
    but nothing is announced and (see the driver) the context memory is not reset. The first surface of a
    run needs only the majority and is adopted silently (``announceFirstSurface``): with nothing to compare with,
    a model that reads a sidewalk as road for the first seconds (192-200 s of the review) cannot be told from a
    real start on the road. Announced surfaces are road / rail only, see ``SpeechPolicy``.
    """

    def __init__(self, cfg: dict[str, Any]):
        self.window_s = float(cfg.get("windowSeconds", 10.0))
        self.majority = float(cfg.get("majority", 0.7))
        self.persist_s = float(cfg.get("minPersistSeconds", 8.0))
        self.need_evidence = bool(cfg.get("requireCrossingEvidence", True))
        self.announce_first = bool(cfg.get("announceFirstSurface", False))
        self.lookback_s = float(cfg.get("evidenceLookbackSeconds", self.window_s))
        # v26.1.11: evidence later than this after the run began did not cause it
        self.lead_s = float(cfg.get("evidenceLeadSeconds", 1e9))
        self.stable: str | None = None
        self._window: list[tuple[float, str]] = []
        self._evidence: list[float] = []
        self._run: str | None = None  # the surface currently running without interruption ...
        self._run_since = 0.0  # ... since
        # group -> (since, last seen): its stretch, gaps up to 1.5 s (a flicker) bridged
        self._seen: dict[str, tuple[float, float]] = {}

    def note_evidence(self, t: float) -> None:
        self._evidence.append(t)
        self._evidence = [e for e in self._evidence if e >= t - 60.0]

    def update(self, t: float, group: str | None) -> tuple[str | None, str, bool] | None:
        """Returns (old, new, announce) when a new group is adopted (old is None for the first), else None."""
        if group is not None:
            self._window.append((t, group))
            since, last = self._seen.get(group, (t, t))
            self._seen[group] = (since if t - last <= 1.5 + 1e-9 else t, t)
            if group != self._run:
                self._run, self._run_since = group, t
        lo = t - self.window_s - 1e-9
        while self._window and self._window[0][0] < lo:
            self._window.pop(0)
        if not self._window or t - self._window[0][0] < self.persist_s - 1e-9:
            return None  # not enough history to call anything a majority
        counts: dict[str, int] = {}
        for _, g in self._window:
            counts[g] = counts.get(g, 0) + 1
        leader = max(counts, key=lambda g: counts[g])
        if counts[leader] < self.majority * len(self._window) - 1e-9 or leader == self.stable:
            return None
        if leader != self._run or t - self._run_since < self.persist_s - 1e-9:
            # kept from v26.1.6: the new surface must also run uninterrupted for minPersistSeconds
            return None
        if self.stable is None:
            self.stable = leader
            return None, leader, self.announce_first
        # the change began where the new surface's stretch (flickers bridged) did
        began = self._seen[leader][0]
        crossed = any(began - self.lookback_s - 1e-9 <= e <= min(t, began + self.lead_s) + 1e-9 for e in self._evidence)
        if self.need_evidence and not crossed:
            return None  # a model relabel of the same pavement: keep the old surface
        old, self.stable = self.stable, leader
        self._evidence.clear()
        return old, leader, True
