"""Detection items: connected components of a class grid with contact geometry (person split, trunk, lane part)."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import numpy as np
import numpy.typing as npt
from scipy import ndimage

from engine.core.classes import FOUR_CONNECTIVITY, ITEM_GROUPS, ClassIds
from engine.core.clock import bearing_deg, clock_from_bearing, clock_quarter, clock_text, pan_from_bearing
from engine.core.groundgeom import FrameGeo, bottom_point, ground_dist, lateral_of
from engine.core.types import Item

__all__ = ["detect_items", "lane_part_item", "split_people", "tree_trunk"]


def split_people(
    comp: npt.NDArray[Any],
    r0: int,
    c0: int,
    geo: FrameGeo,
    cfg: dict[str, Any],
    dmap: npt.NDArray[Any] | None,
    min_pixels: float,
    full: tuple[Any, ...] | None = None,
) -> list[Any] | None:
    """v26.2.10: cut a person component that is wider than ``splitWidthFactor`` x the image width of a ``personWidthM`` person at its distance
    into columns, one per person. Candidate cuts: the valleys between heads of the column height profile (the top edge per column;
    a peak needs a ``valleyRows`` / ``valleyFrac`` x height prominence), and the depth jumps between neighbouring column groups of more than
    ``splitDepthJumpM`` (metric depth map, median per column). Pieces narrower than ``minPieceM``  are merged into their narrower neighbour.
    ``comp`` is the part of the component below the horizon (what the item is made of); ``full`` = (mask, col0, row0) of the same component
    without that cut: the heads are above the horizon of a nearby person, and the height profile reads them there.
    Returns [(rows, cols, mask, col0, row0), ...] (image coordinates, the piece's own cropped mask) or None when nothing is cut."""  # noqa: E501
    from scipy.signal import find_peaks

    gh, gw = geo.gh, geo.gw
    h, w = comp.shape
    rows_a, cols_a = np.nonzero(comp)
    row, col = bottom_point(rows_a + r0, cols_a + c0, np.ones(rows_a.size, dtype=bool), gw)
    dist = ground_dist(geo, (row + 1) / gh, col)
    if dist is None or dist <= 0.0:
        return None
    px_m = geo.f / dist  # image pixels per metre across the view at this distance
    one = float(cfg.get("personWidthM", 0.55)) * px_m
    if w <= float(cfg.get("splitWidthFactor", 1.4)) * one:
        return None
    min_w = max(
        3.0, float(cfg.get("minPieceM", 0.25)) * px_m
    )  # a piece of two columns is a speck of a far person, not a person
    if w < 2 * min_w + 2:
        return None
    if full is not None:  # the profile of the whole person, heads included
        fm, fc0, fr0 = full
        cols_i = np.arange(w) + c0 - fc0
        okc = (cols_i >= 0) & (cols_i < fm.shape[1])
        ftop = np.full(w, np.nan)
        sub = fm[:, cols_i[okc]]
        ftop[okc] = np.where(sub.any(axis=0), sub.argmax(axis=0) + fr0, np.nan)
        ctop = np.where(comp.any(axis=0), comp.argmax(axis=0) + r0, np.nan)
        top_img = np.where(np.isfinite(ftop), ftop, ctop)
        top = np.where(np.isfinite(top_img), top_img, r0 + h)
        h_prof = float(r0 + h - np.nanmin(top))
        hgt = gh - top
    else:
        top = np.where(comp.any(axis=0), comp.argmax(axis=0), h).astype(float)
        h_prof = float(h)
        # (no smoothing: a head is only 2-3 columns wide)
    prom = max(float(cfg.get("valleyRows", 2)), float(cfg.get("valleyFrac", 0.08)) * h_prof)
    cuts: list[int] = []  # a cut c = the boundary between column c - 1 and c
    peaks, _ = find_peaks(
        np.pad(hgt, 1, mode="constant", constant_values=0.0), prominence=prom, distance=max(1, int(min_w))
    )
    peaks = peaks - 1
    for a_, b_ in zip(peaks[:-1], peaks[1:]):  # noqa: B905, RUF007
        seg = hgt[a_ : b_ + 1]
        low = np.flatnonzero(seg <= seg.min() + 1e-9)
        cuts.append(int(a_ + low[len(low) // 2]))
    if dmap is not None and float(cfg.get("splitDepthJumpM", 0.0)) > 0.0:
        dh, dw = dmap.shape
        dcol = np.full(w, np.nan)
        for c in range(w):
            rr_ = np.flatnonzero(comp[:, c])
            if rr_.size:
                dr = np.minimum(dh - 1, ((rr_ + r0 + 0.5) / gh * dh).astype(int))
                v = dmap[dr, min(dw - 1, int((c + c0 + 0.5) / gw * dw))].astype(float)
                v = v[np.isfinite(v) & (v > 0)]
                if v.size:
                    dcol[c] = np.median(v)
        jump = np.zeros(w + 1)
        g = max(1, int(round(min_w / 2.0)))  # noqa: RUF046
        for b_ in range(1, w):
            l_, r_ = dcol[max(0, b_ - g) : b_], dcol[b_ : b_ + g]
            if np.isfinite(l_).any() and np.isfinite(r_).any():
                jump[b_] = abs(float(np.nanmedian(r_) - np.nanmedian(l_)))
        thr = float(cfg["splitDepthJumpM"])
        for b_ in np.flatnonzero(jump >= thr):
            lo, hi = max(0, b_ - int(min_w)), min(w, b_ + int(min_w) + 1)
            if jump[b_] >= jump[lo:hi].max() - 1e-9 and int(b_) not in cuts:
                cuts.append(int(b_))
    cuts = sorted(set(c for c in cuts if 0 < c < w))
    while cuts:  # merge pieces narrower than ``minPieceM`` into their narrower neighbour
        edges = [0] + cuts + [w]  # noqa: RUF005
        widths = np.diff(edges)
        j = int(np.argmin(widths))
        if widths[j] >= min_w:
            break
        if j == 0:
            drop = 0
        elif j == len(widths) - 1:
            drop = len(cuts) - 1
        else:
            drop = j - 1 if widths[j - 1] <= widths[j + 1] else j
        cuts.pop(drop)
    if not cuts:
        return None
    edges = [0] + cuts + [w]  # noqa: RUF005
    out = []
    for e0, e1 in zip(edges[:-1], edges[1:]):  # noqa: B905, RUF007
        m = np.zeros_like(comp)
        m[:, e0:e1] = comp[:, e0:e1]
        lab, n = ndimage.label(m, structure=FOUR_CONNECTIVITY)
        if n == 0:
            continue
        if n > 1:
            m = lab == (1 + int(np.argmax(np.bincount(lab.ravel())[1:])))
        rr, cc = np.nonzero(m)
        if rr.size < min_pixels:
            continue
        out.append((rr + r0, cc + c0, m, c0, r0))
    return out if len(out) >= 2 else None


def detect_items(
    grid: npt.NDArray[Any], ids: ClassIds, geo: FrameGeo, config: dict[str, Any], dmap: npt.NDArray[Any] | None = None
) -> list[Item]:
    """Components (per class, 4-connected, below the horizon) with contact geometry.

    Per class rather than per class *group*: a pole standing against a wall is
    two items, not one wall-labelled blob that hides the pole.

    v26.2.10 (``personSplit``): a ``person`` / ``rider`` component much wider than one person at its distance is several people standing
    together (a semantic model has no instances): it is cut into one piece per head (``split_people``), each piece an item of its own.
    ``dmap`` (metric metres) adds the depth jumps between columns as cut candidates.
    """  # noqa: E501
    gh, gw = geo.gh, geo.gw
    min_pixels = config["minComponentFraction"] * gw * gh
    max_range = config["geometry"]["maxRangeM"]
    items: list[Item] = []
    lane_base_classes = frozenset(config["roles"].get("laneBaseClasses", ()))
    if config["roles"].get("staticSource", "image") == "map":
        lane_base_classes = frozenset()  # v26.2.1: the corridor test of the map covers the lane part
    present = np.bincount(grid.ravel(), minlength=int(grid.max()) + 1)
    split_cfg = config.get("personSplit") or {}
    split_on = bool(split_cfg.get("enabled", False))
    split_names = frozenset(split_cfg.get("classes", ("person", "rider")))
    full_cache: dict[Any, Any] = {}
    tree_cfg = config.get("tree") or {}
    tree_pole = tree_cfg.get("poleClass", "pole")
    veg_id = (
        ids.names.index(tree_cfg.get("canopyClass", "nature vegetation"))
        if tree_cfg.get("canopyClass", "nature vegetation") in ids.names
        else None
    )
    if veg_id is None:
        tree_cfg = {}
    for group in ITEM_GROUPS:
        for cid in ids.items[group]:
            if cid >= len(present) or present[cid] == 0:
                continue
            mask = (grid == cid) & geo.below[:, None]
            if not mask.any():
                continue
            labels, _n = ndimage.label(mask, structure=FOUR_CONNECTIVITY)
            for k, sl in enumerate(ndimage.find_objects(labels), start=1):
                comp = labels[sl] == k
                rr, cc = np.nonzero(comp)
                if rr.size < min_pixels:
                    continue
                pieces = [(rr + sl[0].start, cc + sl[1].start, comp, sl[1].start, sl[0].start)]
                if cid not in full_cache:  # the same class without the horizon cut: heads above it
                    fl, _ = ndimage.label(grid == cid, structure=FOUR_CONNECTIVITY)
                    full_cache[cid] = (fl, ndimage.find_objects(fl))
                fl, fobj = full_cache[cid]
                fid = int(fl[rr[0] + sl[0].start, cc[0] + sl[1].start])
                full_ref: tuple[Any, Any, int] | None = (
                    fl,
                    fobj[fid - 1],
                    fid,
                )  # v26.2.12: the whole component, rows above the horizon too
                if split_on and ids.names[cid] in split_names:
                    fsl = fobj[fid - 1]
                    full = (fl[fsl] == fid, fsl[1].start, fsl[0].start)
                    split = split_people(comp, sl[0].start, sl[1].start, geo, split_cfg, dmap, min_pixels, full)
                    if split:
                        pieces, full_ref = (
                            split,
                            None,
                        )  # a piece of a group: its own shape (the whole group is not its outline)
                for rr, cc, shape_mask, sc0, sr0 in pieces:
                    in_lane_region = geo.lane_region[rr, cc]
                    in_lane = geo.lane[rr, cc]
                    everything = np.ones(rr.size, dtype=bool)
                    if group == "feature":
                        sel = in_lane if in_lane.any() else everything
                        lane_hit = bool(in_lane.any())
                    else:
                        # v26.1.5: the contact point is the item's true lowest pixel (where it stands). It
                        # counts as "in the lane" only if that lowest row itself touches the lane inside the
                        # walking region; a car beside the path whose roof or bumper pixels intrude does not.
                        sel = everything
                        lane_hit = bool(in_lane_region[rr == rr.max()].any())
                    row, col = bottom_point(rr, cc, sel, gw)
                    if ids.names[cid] == "rider":
                        # v26.1.13 (review 6, 445.3 s "position is wrong"): the lowest row of a bicycle + rider is the wheels, and the column  # noqa: E501
                        # nearest the image centre on it is the wheel's far edge, up to a quarter-hour clock position off the body. A rider's  # noqa: E501
                        # horizontal position is the middle of that row.
                        on_row = cc[rr == rr.max()]
                        col = int((on_row.min() + on_row.max()) // 2)
                    contact_y = (row + 1) / gh
                    dist = ground_dist(geo, contact_y, col)
                    if dist is None or dist > max_range:
                        continue
                    inreg = geo.region_dilated[rr, cc]
                    # "Runs along the path" is judged on where the item stands on the floor: its pixels
                    # with walking region directly below. A wall's or median's base spans a long stretch of
                    # path; a pole touches the floor on one row. (Its upper pixels would all look like far
                    # ground, which is why every row of a thin pole is NOT used.)
                    base = geo.floor_below[rr, cc]
                    along = False
                    if base.any():
                        d_far = ground_dist(geo, (rr[base].min() + 1) / gh, col)
                        d_near = ground_dist(geo, (rr[base].max() + 1) / gh, col)
                        along = bool(d_far and d_near and d_near / d_far < config["roles"]["alongPathRatio"])
                    lane_row = geo.lane[row]
                    cover = 0.0
                    if lane_row.any():
                        cover = float(np.count_nonzero((rr == row) & in_lane)) / float(lane_row.sum())
                    x = (col + 0.5) / gw
                    bearing = bearing_deg(x, geo.hfov_deg, geo.projection)
                    is_tree = (
                        tree_cfg.get("enabled", False)
                        and group == "static"
                        and ids.names[cid] == tree_pole
                        and full_ref is not None
                        and tree_trunk(grid, veg_id, full_ref, tree_cfg)
                    )
                    main = Item(
                        group=group,
                        class_name=ids.names[cid],
                        bbox=[cc.min() / gw, rr.min() / gh, (cc.max() + 1) / gw, (rr.max() + 1) / gh],
                        contact_y=contact_y,
                        distance_m=dist,
                        lateral_m=lateral_of(geo, row + 1.0, col, dist) + geo.lateral_offset_m,
                        bearing=bearing,
                        clock=clock_from_bearing(bearing),
                        clock_q=(cq := clock_quarter(bearing)),
                        clock_text=clock_text(cq),
                        pan=pan_from_bearing(bearing),
                        area_frac=rr.size / (gh * gw),
                        clipped=bool(rr.max() == gh - 1),
                        touches=bool(inreg.any()),
                        lane_hit=lane_hit,
                        along_path=along,
                        lane_cover=cover,
                        contact_y_raw=contact_y,
                        area_m2=rr.size * (dist / geo.f) ** 2,
                        people=ids.names[cid] in ids.people,
                        fast=ids.names[cid] in ids.fast,
                        thin=ids.names[cid] in ids.thin,
                        landmark=ids.names[cid] in ids.landmark,
                        base_row=int(row),
                        base_col=int(col),
                        shape=(shape_mask, sc0, sr0),
                        full_ref=full_ref,
                        tree=bool(is_tree),
                    )
                    if is_tree:
                        main.thin = False
                    items.append(main)
                    if group == "static" and ids.names[cid] in lane_base_classes and (not lane_hit or along):
                        part = lane_part_item(main, rr, cc, geo, config)
                        if part is not None:
                            items.append(part)
    return items


def tree_trunk(grid: npt.NDArray[Any], veg_id: int | None, full_ref: tuple[Any, ...], cfg: dict[str, Any]) -> bool:
    """v26.2.12 (review 9, 18.34 s: a tree trunk at the curb was called a pole): a ``pole`` component whose TOP meets a vegetation canopy: in the
    ``gapRows`` rows above its top row (and the top row itself) at least ``minOverlap`` of the pole's columns have a vegetation pixel."""  # noqa: E501
    fl, fsl, fid = full_ref
    mask = fl[fsl] == fid
    cols = np.flatnonzero(mask.any(axis=0)) + fsl[1].start
    if not cols.size:
        return False
    top = fsl[0].start
    lo = max(0, top - int(cfg.get("gapRows", 2)) - 1)
    band = grid[lo : top + 1, cols] == veg_id
    return float(band.any(axis=0).mean()) >= float(cfg.get("minOverlap", 0.5))


def lane_part_item(
    main: Item, rr: npt.NDArray[Any], cc: npt.NDArray[Any], geo: FrameGeo, config: dict[str, Any]
) -> Item | None:
    """v26.1.16 follow-up (review 8, 10.9 s): the part of a wall / building that stands IN the lane.

    A static item is measured at its lowest pixel, so a building whose side wall runs along the sidewalk and whose scaffolded
    section juts out across the path is measured at the side wall's base (context) and the section in the lane is never
    judged. Its ground base is: the component's pixels with walking region directly below them (``floor_below``, the same
    test as ``along_path``) that lie inside the lane within the walking region. Pixels ABOVE such a base never count (the
    earlier attempt, "any pixel over a lane cell", made every wall along a sidewalk a danger). With at least
    ``laneBaseMinColumns`` columns of it, the extra item has its contact at the lowest base cell (on that row the column
    nearest the lane centre), ``lane_hit`` True and ``along_path`` False; area and outline are the whole component's."""  # noqa: E501
    roles = config["roles"]
    gh, gw = geo.gh, geo.gw
    sel = geo.floor_below[rr, cc] & geo.lane_region[rr, cc]
    if not sel.any() or np.unique(cc[sel]).size < roles.get("laneBaseMinColumns", 2):
        return None
    # a wall seen edge-on along the path has a DIAGONAL base (one or two cells per row, over many rows); a face across the  # noqa: E501
    # lane has a FLAT one: enough cells in one row, and that row holding a good share of all the base cells
    widest = int(np.bincount(rr[sel]).max())
    flat = widest >= roles.get("laneBaseMinRowColumns", 1) and widest >= roles.get(
        "laneBaseMinConcentration", 0.0
    ) * np.count_nonzero(sel)
    row = int(rr[sel].max())
    on_row = cc[sel & (rr == row)]
    lane_cols = np.flatnonzero(geo.lane[row])
    centre = float(lane_cols.mean()) if lane_cols.size else gw / 2.0 - 0.5
    col = int(on_row[np.argmin(np.abs(on_row - centre))])
    contact_y = (row + 1) / gh
    dist = ground_dist(geo, contact_y, col)
    if dist is None or dist > config["geometry"]["maxRangeM"]:
        return None
    x = (col + 0.5) / gw
    bearing = bearing_deg(x, geo.hfov_deg, geo.projection)
    return replace(
        main,
        contact_y=contact_y,
        contact_y_raw=contact_y,
        distance_m=dist,
        lateral_m=lateral_of(geo, row + 1.0, col, dist) + geo.lateral_offset_m,
        bearing=bearing,
        clock=clock_from_bearing(bearing),
        clock_q=(cq := clock_quarter(bearing)),
        clock_text=clock_text(cq),
        pan=pan_from_bearing(bearing),
        clipped=bool(row == gh - 1),
        touches=True,
        lane_hit=True,
        along_path=False,
        lane_cover=float(np.count_nonzero(sel & (rr == row))) / float(max(1, lane_cols.size)),
        lane_part=True,
        lane_part_weak=not flat,
        depth_cells=(rr[sel], cc[sel]),
        base_row=int(row),
        base_col=int(col),
    )
