"""v26.2.12 (W1): c2 as the default, the GPS step length, quieter beeps and speech inside the collision zone, re-announcing, followed walls,
"blocked ahead", trunks, predictive speech with a cap, the whole component of an item (plan ``docs/plans/v26.2.12.md``, W1) and the review-9 targets."""
from __future__ import annotations

import copy
import types

import numpy as np
import pytest

import collision as col
import sensors as sensor_lib
from tests.replay import fixture_sensors, load_fixture, replay
from tests.test_collision import _item, _policy, _tracks

CONFIG = col.load_config()          # conftest: the v26.2.12 defaults for this module (predictive on)
SPEECH125 = {"kinds": {}, "speechRate": 1.25}


def _pol(config=None, rate=1.25):
    p = _policy(config or CONFIG)
    p.speech_rate = rate
    return p


def _danger(tid, label, steps, lateral=0.0, clock=12, collision=True, dist=None, thin=False):
    it = _item(tid, "danger", steps, label, clock=clock, dist=dist)
    it.collision, it.lateral_m, it.thin = collision, lateral, thin
    it.urgency = "final" if steps <= 3 else "danger"
    it.clock_q = col._quarter_of_hour(clock)
    return it


# -- 1. defaults = c2 --------------------------------------------------------------------------------------------------------------------------

def test_defaults_are_c2_and_the_new_rules_are_on():
    assert CONFIG["version"] == "v26.2.12"
    assert CONFIG["source"]["mode"] == "map" and CONFIG["horizon"]["source"] == "fused"
    assert CONFIG["ego"]["headingSource"] == "imu" and CONFIG["ego"]["cadenceSource"] == "imu"
    assert CONFIG["tones"]["speechRate"] == 1.25
    sp = CONFIG["speech"]
    assert sp["minVoiceSteps"] == 2 and sp["thinStableS"] == 0.5 and sp["colocatedM"] == 1.5 and sp["zoneOnly"]["enabled"] is True
    assert sp["predictive"]["maxAdvanceM"] == 1.5 and sp["predictive"]["clockHoldQuarters"] == 2
    assert sp["reannounce"]["enabled"] and CONFIG["beeps"]["follow"]["followQuietS"] == 6.0 and CONFIG["blocked"]["aheadM"] == 3.0
    assert CONFIG["ego"]["stepLength"]["source"] == "auto" and CONFIG["tree"]["enabled"] and CONFIG["distance"]["jump"]["enabled"]


def test_the_heading_label_says_gps_only_when_gps_updates_were_applied():
    """c2's ``headingSource`` "imu" is the gyro heading WITH the slow GPS course pull (like "auto"): the resolved label reads imu+gps when >= 1
    update was applied; "gyro" is the pure gyro heading and reads imu."""
    _, doc, _ = replay("chest0004_review9", sounds=SPEECH125)
    assert doc["settings"]["headingSource"] == "imu+gps" and doc["settings"]["gpsUpdates"] > 0
    ov = {"collision": {**load_fixture("chest0004_review9")[0]["overrides"]["collision"], "ego.headingSource": "gyro"}}
    _, doc2, _ = replay("chest0004_review9", overrides=ov, sounds=SPEECH125)
    assert doc2["settings"]["headingSource"] == "imu" and doc2["settings"]["gpsUpdates"] == 0


# -- 2. the step length from the GPS -----------------------------------------------------------------------------------------------------------

def _gps(n_s=120.0, speed=1.4, fix=3, dop=1.2, hz=18.0):
    t = np.arange(0.0, n_s, 1.0 / hz)
    g = np.zeros((len(t), 5))
    g[:, 0], g[:, 1], g[:, 3] = 41.0, -8.6, speed
    return {"gps": g, "gps_t": t, "gps_fix": np.full(len(t), fix), "gps_dop": np.full(len(t), dop)}


def test_gps_step_length_is_the_median_speed_over_cadence_with_good_fix_moving_samples():
    s = _gps()
    mt = np.arange(0.0, 120.0, 1 / 24)
    cad = np.full(len(mt), 1.75)
    r = sensor_lib.gps_step_length(s, mt, cad, np.zeros(len(mt), bool), {"minS": 60.0})
    assert abs(r["stepM"] - 1.4 / 1.75) < 1e-6 and abs(r["windowsS"] - 120.0) < 1.0 and r["p10"] == r["p90"] == pytest.approx(0.8)
    # clamped to [0.5, 1.1]
    assert sensor_lib.gps_step_length(_gps(speed=3.0), mt, cad, np.zeros(len(mt), bool), {"minS": 60.0})["stepM"] == 1.1
    assert sensor_lib.gps_step_length(_gps(speed=0.9), mt, cad, np.zeros(len(mt), bool), {"minS": 60.0})["stepM"] == pytest.approx(0.9 / 1.75)
    assert sensor_lib.gps_step_length(_gps(speed=0.6), mt, np.full(len(mt), 1.75), np.zeros(len(mt), bool), {"minS": 60.0, "minSpeedMps": 0.5})["stepM"] == 0.5
    # not enough moving time / weak GPS / no cadence / stationary: None
    assert sensor_lib.gps_step_length(_gps(n_s=50.0), mt, cad, np.zeros(len(mt), bool), {"minS": 60.0}) is None
    assert sensor_lib.gps_step_length(_gps(dop=3.3), mt, cad, np.zeros(len(mt), bool), {"minS": 60.0}) is None
    assert sensor_lib.gps_step_length(_gps(fix=2), mt, cad, np.zeros(len(mt), bool), {"minS": 60.0}) is None
    assert sensor_lib.gps_step_length(s, mt, np.full(len(mt), np.nan), np.zeros(len(mt), bool), {"minS": 60.0}) is None
    assert sensor_lib.gps_step_length(s, mt, cad, np.ones(len(mt), bool), {"minS": 60.0}) is None
    assert sensor_lib.gps_step_length({}, mt, cad, None, {}) is None


def test_the_pass_resolves_the_step_length_gps_prior_or_user():
    meta, z = load_fixture("chest0004_review9")
    s = fixture_sensors(z)
    ov = {"collision": {**meta["overrides"]["collision"], "ego.stepLength.minS": 20.0}}
    # the fixture's own GPS is weak (DOP > 2.5): the prior
    _, doc, _ = replay("chest0004_review9", overrides=ov, sounds=SPEECH125)
    st = doc["settings"]
    assert st["stepLengthSource"] == "prior" and st["gpsStepWindowsS"] == 0.0 and st["stepLengthM"] == pytest.approx(0.7387, abs=1e-3)
    # a good GPS (synthetic, 1.4 m/s) over the cadence the accelerometer gives: the step is the GPS one and drives the ego speed and the steps
    g = copy.deepcopy(s)
    g["gps_fix"], g["gps_dop"] = np.full(len(g["gps_t"]), 3), np.full(len(g["gps_t"]), 1.0)
    g["gps"] = g["gps"].copy()
    g["gps"][:, 3] = 1.4
    _, doc, _ = replay("chest0004_review9", overrides=ov, sounds=SPEECH125, sensors=g)
    st = doc["settings"]
    assert st["stepLengthSource"] == "gps" and st["gpsStepWindowsS"] >= 20.0 and 0.5 <= st["stepLengthM"] <= 1.1 and st["gpsStep"]["samples"] > 100
    speeds = [(f["ego"]["speedMps"], f["ego"]["cadenceHz"], f["ego"]["stepLengthM"]) for f in doc["frames"] if f["ego"]["speedMps"] and f["ego"]["cadenceHz"]]
    assert speeds and all(abs(v - c * sl) < 0.02 for v, c, sl in speeds[10:])
    # the user's own step length wins
    meta2 = meta["settings"]
    assert meta2["stepLengthM"] is None


def test_a_step_length_typed_by_the_user_wins_over_the_gps():
    s = col.resolve_settings(CONFIG, "chest", 118.0, None, 0.9)
    assert s.step_length_user and s.step_length_m == 0.9
    assert not col.resolve_settings(CONFIG, "chest", 118.0, None, None, user_height_m=1.78).step_length_user


# -- 3. too close for voice ---------------------------------------------------------------------------------------------------------------------

def test_a_beeping_item_two_steps_away_is_not_spoken_but_three_is():
    p = _pol()
    p.ego_u = None                       # no prediction: the spoken numbers are today's
    assert p.step(10.0, [_danger(1, "obstacle", 2, clock=12)], _tracks(1)) is None
    q = _pol()
    q.ego_u = None
    e = q.step(10.0, [_danger(1, "obstacle", 3, clock=12)], _tracks(1))
    assert e["text"] == "obstacle at 12 in 3"
    # a danger that is not beeping (no collision) is still said
    r = _pol()
    r.ego_u = None
    assert r.step(10.0, [_danger(1, "person", 2, collision=False)], _tracks(1))["text"] == "person at 12 in 2"
    # only the near one of two leaves the phrase; the predicted steps decide when the phrase is predicted
    s = _pol()
    s.ego_u = None
    near = _danger(1, "pole", 2)
    near.urgency = "danger"                     # (not a final: the final of a track is its own slot)
    e = s.step(10.0, [near, _danger(2, "sign", 8, clock=11)], _tracks(1, 2))
    assert e["text"].startswith("sign at 11 in 8") and "pole" not in e["text"]
    t = _pol()
    t.ego_u = 1.0
    it = _danger(1, "sign", 5, dist=3.5)     # 5 steps now, 0.2 + 5 / 3.5 = 1.63 s at 1 m/s -> 1.9 m: 3 steps, still said
    e = t.step(10.0, [it], _tracks(1))
    assert e["predicted"]["steps"] == 3 and "in 3" in e["text"]


# -- 4. thin statics only inside the collision zone ---------------------------------------------------------------------------------------------

def test_thin_statics_outside_the_collision_zone_are_not_said():
    out = _item(1, "context", 5, "pole")
    out.thin, out.lateral_m, out.collision, out.present_run = True, 1.8, False, 2
    p = _pol()
    p.ego_u = None
    assert p.step(10.0, [out], _tracks(1)) is None
    inside = _item(2, "context", 5, "pole")
    inside.thin, inside.lateral_m, inside.collision, inside.present_run = True, 0.2, True, 2
    q = _pol()
    q.ego_u = None
    e = q.step(10.0, [inside], _tracks(2))
    assert e is not None and e["text"].startswith("pole at 12 in 5")
    # not a listed class (a person): unaffected
    assert p._zone_ok(_item(3, "none", 5, "person")) and not p._zone_ok(out) and p._zone_ok(inside)
    # switched off: the notice is back
    cfg = copy.deepcopy(CONFIG)
    cfg["speech"]["zoneOnly"]["enabled"] = False
    r = _pol(cfg)
    r.ego_u = None
    assert r.step(10.0, [out], _tracks(1)) is not None


def test_a_thin_item_whose_distance_just_jumped_stays_unspoken_until_stable():
    it = _danger(1, "pole", 6, thin=True)
    it.unstable = True
    p = _pol()
    p.ego_u = None
    assert p.step(10.0, [it], _tracks(1)) is None
    it.unstable = False
    assert p.step(10.2, [it], _tracks(1))["text"] == "pole at 12 in 6"


# -- 6. trunks and the distance jump ------------------------------------------------------------------------------------------------------------

def test_a_pole_under_a_canopy_is_a_tree():
    ids = {"nature vegetation": 3, "pole": 4}
    grid = np.zeros((30, 40), dtype=np.int64)
    grid[3:9, 10:20] = 3                        # the canopy
    grid[10:25, 14:16] = 4                      # the trunk: its top is 1 row under the canopy
    fl, nobj = __import__("scipy.ndimage", fromlist=["label"]).label(grid == 4)
    from scipy import ndimage
    fsl = ndimage.find_objects(fl)[0]
    cfg = CONFIG["tree"]
    assert col._tree_trunk(grid, 3, (fl, fsl, 1), cfg) is True
    grid[3:9, 10:20] = 0                        # no canopy: a pole
    assert col._tree_trunk(grid, 3, (fl, fsl, 1), cfg) is False
    grid[3:9, 30:38] = 3                        # a canopy elsewhere
    assert col._tree_trunk(grid, 3, (fl, fsl, 1), cfg) is False
    grid[3:6, 10:20] = 3                        # too high above the top (gap 4 rows): not touching
    assert col._tree_trunk(grid, 3, (fl, fsl, 1), cfg) is False


def test_review9_the_trunk_at_18_s_is_a_tree_and_not_spoken_while_its_distance_jumps():
    _, doc, ev = replay("chest0004_review9", sounds=SPEECH125)
    labs = [(f["t"], h["label"], h["distanceM"]) for f in doc["frames"] if 17.9 <= f["t"] <= 18.6 for h in f["hazards"] if h["trackId"] == 602]
    assert labs and all(lab == "tree" for _, lab, _ in labs)
    assert not any(e["type"] == "speech" and 17.8 <= e["t"] <= 18.7 and ("pole" in e["text"] or "tree" in e["text"]) for e in ev["events"])


# -- 5. vehicles that are no vehicles ------------------------------------------------------------------------------------------------------------

def test_review9_no_vehicle_beep_for_the_top_of_the_skip():
    """25.1 s: the top of a parked skip (track 871: its distance jumped 7.3 -> 5.6 -> 6.1 m, then the solid snap put it at 2.2 -> 1.0 m with a frozen box) was
    a "vehicle at 10:30, 1 step" beep. The distance-jump rule cuts the motion history of a vehicle (no speed from a glitch), it is judged as a static."""
    _, doc, ev = replay("chest0004_review9", sounds=SPEECH125)
    assert not any(e["type"] == "beeps" and "vehicle" in e["label"] and 24.5 <= e["t"] <= 26.0 for e in ev["events"])
    off = {"collision": {**load_fixture("chest0004_review9")[0]["overrides"]["collision"], "distance.jump.enabled": False}}
    _, _, ev0 = replay("chest0004_review9", overrides=off, sounds=SPEECH125)
    assert any(e["type"] == "beeps" and "vehicle" in e["label"] and 24.5 <= e["t"] <= 26.0 for e in ev0["events"])      # (A/B: the switch matters)


# -- 7. re-announce and the closest marker ------------------------------------------------------------------------------------------------------

def test_a_static_announced_before_is_announced_again_when_its_place_changed_a_lot():
    p = _pol()
    p.ego_u = None
    tr = _tracks(1)
    a = _danger(1, "building", 4, clock=12, dist=2.8)
    a.clock_q, a.clock_text = 3, col.clock_text(3)           # 12:45
    e = p.step(10.0, [a], tr)
    assert e["text"] == "building at 12:45 in 4"
    # the same track now means the face ahead: 12 in 9
    b = _danger(1, "building", 9, clock=12, dist=6.3)
    assert p.step(11.0, [b], tr)["text"] == "building at 12 in 9"
    # an unchanged place is not said again, and a re-announcement needs reannounce.minGapS
    assert p.step(14.0, [_danger(1, "building", 9, clock=12, dist=6.3)], tr) is None
    c = _danger(1, "building", 12, clock=12, dist=8.4)
    assert p.step(11.4, [c], tr) is None


def test_the_clock_clause_needs_a_collision_item():
    p = _pol()
    p.ego_u = None
    tr = _tracks(1)
    a = _danger(1, "building", 4, clock=12)
    a.clock_q, a.clock_text = 3, col.clock_text(3)
    assert p.step(10.0, [a], tr) is not None
    b = _danger(1, "building", 4, clock=11, collision=False)       # moved 4+ quarters but is no collision now
    b.clock_q = -4
    assert p.step(13.0, [b], tr) is None


def test_co_located_collision_items_are_said_once_with_the_closest_ones_numbers():
    p = _pol()
    p.ego_u = None
    near = _danger(1, "building", 9, clock=12, dist=6.7)
    far = _danger(2, "sign", 9, clock=11, dist=7.0, lateral=-1.0, thin=True)
    tr = _tracks(1, 2)
    e = p.step(10.0, [near, far], tr)
    assert e["text"] == "building at 12 in 9"
    # the thin notice of the same marker is consumed too: nothing follows
    assert p.step(13.0, [near, far], tr) is None
    # far apart: both are said
    q = _pol()
    q.ego_u = None
    a = _danger(1, "building", 9, clock=12, dist=6.7)
    b = _danger(2, "pole", 9, clock=3, dist=6.7, lateral=3.0)
    assert "pole" in q.step(10.0, [a, b], _tracks(1, 2))["text"]


# -- 8. walls being followed --------------------------------------------------------------------------------------------------------------------

def _wall(clock_q, steps=3.0, lat=0.5, cls="building"):
    it = _item(1, "danger", steps, cls)
    it.clock_q, it.lateral_m, it.family = clock_q, lat, "building"
    return it


def test_a_wall_on_the_same_side_within_6_s_does_not_start_a_new_beep_episode():
    cfg = CONFIG["beeps"]["follow"] | {"enabled": True}
    st: dict = {}
    assert col._followed_wall(_wall(3, lat=0.4), 10.0, st, cfg) is False       # the first episode beeps
    assert col._followed_wall(_wall(3, lat=0.4), 10.2, st, cfg) is False       # ... and runs on
    assert col._followed_wall(_wall(2, lat=0.5), 12.7, st, cfg) is True        # a new face on the same side, lateral within 0.4: followed
    assert col._followed_wall(_wall(2, lat=0.5), 14.0, st, cfg) is True
    assert col._followed_wall(_wall(2, lat=0.5), 16.5, st, cfg) is False       # > 6 s after the last real beep: beeps again
    # a wall moving to the centre, to <= 1 step, a different lateral, the other side or another family still beeps
    st = {}
    col._followed_wall(_wall(3), 10.0, st, cfg)
    assert col._followed_wall(_wall(0), 12.7, st, cfg) is False
    assert col._followed_wall(_wall(3, steps=1.0), 12.7, st, cfg) is False
    assert col._followed_wall(_wall(3, lat=1.2), 12.7, st, cfg) is False
    assert col._followed_wall(_wall(-3, lat=-0.5), 12.7, st, cfg) is False
    pole = _wall(3, cls="pole")
    assert col._followed_wall(pole, 12.7, st, cfg) is False


def test_review9_the_building_beeps_at_21_s_are_followed_and_25_99_beeps_again():
    _, _, ev = replay("chest0004_review9", sounds=SPEECH125)
    b = [e for e in ev["events"] if e["type"] == "beeps"]
    assert not any(20.8 <= e["t"] <= 21.3 for e in b)
    assert any(abs(e["t"] - 25.99) <= 0.3 and "building" in e["label"] for e in b)
    assert any(abs(e["t"] - 18.12) <= 0.3 and "building" in e["label"] for e in b)


# -- 9. blocked ahead -----------------------------------------------------------------------------------------------------------------------

def _fake_map(solid_cols=None, walk_left=True, size=200, cell=0.1):
    names = ["building", "flat sidewalk", "flat road", "barrier"]
    m = object.__new__(col._StaticMap)
    rows, cols = np.mgrid[0:size, 0:size]
    m.ob = types.SimpleNamespace(fwd=(190 - rows) * cell, right=(cols - 100) * cell, size=size, orow=190, oc=100, cell=cell)
    m.classes = np.full((size, size), 2, dtype=np.int64)
    m.conf = np.full((size, size), 255, dtype=np.int64)
    sw = (m.ob.fwd > -1) & (m.ob.right < 1.0)
    m.classes[sw] = 1
    if solid_cols is not None:
        lo, hi = solid_cols
        m.classes[(m.ob.fwd > 1.0) & (m.ob.fwd < 3.5) & (m.ob.right >= lo) & (m.ob.right <= hi)] = 0
    m._names, m.min_conf, m.lane_half = names, 178, 0.6
    return m


def test_blocked_ahead_needs_70_percent_of_the_lane_and_names_the_free_direction():
    cfg = CONFIG["blocked"]
    wide = _fake_map(solid_cols=(-0.6, 0.6)).blocked_ahead(cfg)         # the whole lane blocked, the sidewalk goes on to the left
    assert wide is not None and wide["share"] >= 0.9 and wide["free"] and wide["bearingDeg"] < 0 and wide["clock"] in ("11", "10:45", "10:30", "10:15", "10")
    assert _fake_map(solid_cols=(0.2, 0.6)).blocked_ahead(cfg) is None                      # only 40 % of the lane
    assert _fake_map(solid_cols=None).blocked_ahead(cfg) is None
    none = _fake_map(solid_cols=(-0.6, 0.6))
    none.classes[none.ob.fwd > 0.3] = np.where(none.classes[none.ob.fwd > 0.3] == 1, 2, none.classes[none.ob.fwd > 0.3])     # no walkable ground at all
    r = none.blocked_ahead(cfg)
    assert r is not None and r["free"] is None


def test_review9_21_17_an_obstacle_on_the_walkway_is_blocked_at_11_45_and_continues_right():
    """v26.2.12 follow-up (O26): the skip on the sidewalk ~6 m ahead (mostly "barrier wall"): the map cells plus the object bases of the last 0.7 s cover
    >= 50 % of the lane within 6.5 m; the phrase names where it is and where the sidewalk goes on; nothing else is "blocked" in 0-30 s."""
    _, _, ev = replay("chest0004_review9", sounds=SPEECH125)
    b = [e for e in ev["events"] if e["type"] == "speech" and "blocked" in e.get("text", "") and e["t"] <= 30.0]
    assert len(b) == 1, [(e["t"], e["text"]) for e in b]
    assert 20.47 <= b[0]["t"] <= 21.87
    assert b[0]["text"] == "sidewalk blocked at 11:45, continues 12:15"
    assert b[0]["blocked"]["kind"] == "obstacle" and b[0]["blocked"]["blockClock"] == "11:45"


def _recent(m, pts, pose=(0.0, 0.0, 0.0)):
    """Object-base points (forward m, right m) seen from the origin pose, kept as world points; ``pose`` is where we are now."""
    m.obs_hist = [(0.0, np.array([p[1] for p in pts]), np.array([p[0] for p in pts]))]
    m.pose = pose


def test_blocked_obstacle_counts_recent_bases_dead_reckoned_and_needs_half_the_lane():
    cfg = CONFIG["blocked"]
    pts = [(5.0, x) for x in np.arange(-0.55, 0.0, 0.1)]                # 6 of the 12 lane bins at 5 m, nothing in the map
    m = _fake_map()
    _recent(m, pts)
    r = m.blocked_ahead(cfg)
    assert r is not None and r["kind"] == "obstacle" and r["share"] == 0.5 and r["label"] == "sidewalk" and r["blockClock"] in ("12", "11:45")
    m2 = _fake_map()
    _recent(m2, pts[:5])                                                  # 5 of 12 bins: not enough
    assert m2.blocked_ahead(cfg) is None
    m3 = _fake_map()
    _recent(m3, pts, pose=(0.0, 4.0, 0.0))                                # walked 4 m: the points are now 1 m ahead (still in the lane strip)
    r3 = m3.blocked_ahead(cfg)
    assert r3 is not None and abs(r3["cfwd"] - 1.0) < 0.2
    m4 = _fake_map()
    _recent(m4, pts, pose=(0.0, 5.5, 0.0))                                # passed by 0.5 m: gone
    assert m4.blocked_ahead(cfg) is None
    m5 = _fake_map()
    _recent([m5][0], [(7.0, x) for x in np.arange(-0.6, 0.6, 0.1)])       # beyond obstacle.aheadM (6.5 m)
    assert m5.blocked_ahead(cfg) is None


def test_blocked_wall_keeps_the_3_m_reach_and_70_percent():
    cfg = CONFIG["blocked"]
    near = _fake_map(solid_cols=(-0.6, 0.6))                              # building at 1.0-3.5 m
    assert near.blocked_ahead(cfg)["kind"] == "wall"
    far = _fake_map(solid_cols=(-0.6, 0.6))
    far.classes[(far.ob.fwd <= 3.5) & (far.ob.fwd > 3.0)] = 1
    far.classes[(far.ob.fwd > 1.0) & (far.ob.fwd <= 3.0)] = 1             # the building only from 3.1 m on
    far.classes[(far.ob.fwd > 3.05) & (far.ob.fwd < 3.5) & (abs(far.ob.right) <= 0.6)] = 0
    assert far.blocked_ahead(cfg) is None
    bar = _fake_map(solid_cols=(-0.6, 0.6))                               # a "barrier" at 3 m is the obstacle kind (6.5 m reach), not a wall
    bar.classes[bar.classes == 0] = 3
    assert bar.blocked_ahead(cfg)["kind"] == "obstacle"


def test_blocked_free_direction_is_the_smallest_angle_past_the_blockage():
    cfg = CONFIG["blocked"]
    m = _fake_map(solid_cols=(-0.6, 0.0))                                 # the left half of the lane is a wall; the walkable ground is also to the right (right < 1.0)
    m.classes[(m.ob.fwd > 0.9) & (m.ob.fwd < 3.6) & (m.ob.right >= -0.6) & (m.ob.right <= 0.6)] = 1
    m.classes[(m.ob.fwd > 1.0) & (m.ob.fwd < 3.5) & (m.ob.right >= -0.6) & (m.ob.right <= 0.6) & (m.ob.right < 0.0)] = 0
    m.classes[(m.ob.fwd > 1.0) & (m.ob.fwd < 3.5) & (m.ob.right >= 0.0) & (m.ob.right <= 0.6)] = 0         # whole lane: blocked
    r = m.blocked_ahead(cfg)
    assert r["free"] and abs(r["bearingDeg"]) in (30.0, 37.5, 45.0) and r["bearingDeg"] < 0
    # never straight ahead, and the step is 7.5 deg
    assert r["bearingDeg"] % 7.5 == 0 and r["bearingDeg"] != 0


def test_blocked_phrase_names_where_it_is_blocked_and_where_it_continues():
    t = CONFIG["blocked"]["templates"]
    assert t["free"].format(label="sidewalk", clock="11:45", free="12:15") == "sidewalk blocked at 11:45, continues 12:15"
    assert t["none"].format(label="sidewalk", clock="11:45") == "sidewalk blocked at 11:45"
    m = _fake_map(solid_cols=(-0.6, 0.6))
    r = m.blocked_ahead(CONFIG["blocked"])
    assert r["blockClock"] == "12" and r["label"] == "sidewalk"


# -- 10. predictive speech: the advance is capped and the clock does not swing -----------------------------------------------------------------

def test_the_advance_is_capped_and_the_clock_stays_when_the_predicted_one_swings():
    p = _pol(rate=0.5)                                             # a long phrase: 2.2 s at 1.8 m/s would advance 4 m
    p.ego_u = 1.8
    it = _danger(1, "pole", 6, dist=4.5, lateral=0.5, clock=12)    # bearing 6.3 deg: 12:00 now, 3.0 m
    it.bearing, it.clock_q = 6.3, 1
    it.collision = False
    it.role, it.urgency = "danger", "danger"
    v = p._view(it, 2.2)
    assert v is not None and abs(v.distance_m - 3.0) < 0.01              # capped at 1.5 m, not 4.5 - 4.0
    # the swing: 1.9 m ahead, 0.4 m right (12:30 now); 1.5 m later it is at 0.4 m / 0.4 m = 45 deg = 1:30 -> stays 12:30
    q = _pol()
    q.ego_u = 1.0
    jt = _danger(1, "pole", 3, dist=1.9, lateral=0.4, clock=12)
    jt.bearing, jt.clock_q = 11.9, 2
    w = q._view(jt, 1.5)
    assert w.clock_q == 2 and abs(w.distance_m - 0.4) < 0.01 and w.clock_text == "12:30"
    # a swing within one half hour is kept
    kt = _danger(1, "pole", 5, dist=3.2, lateral=0.2, clock=12)
    kt.bearing, kt.clock_q = 3.6, 0
    assert q._view(kt, 1.5).clock_q == 1 and q._view(kt, 1.5).clock_text == "12:15"
    # an item that would be passed is dropped on the UNcapped advance
    pt = _danger(1, "pole", 3, dist=2.0)
    assert q._view(pt, 2.5) is None


def test_the_advance_speed_is_the_measured_one_with_a_floor():
    p = _pol()
    p.ego_u = 1.5
    it = _danger(1, "pole", 6, dist=6.0, clock=12)
    p.ego_meas = None
    assert abs(p._view(it, 1.0).distance_m - 4.5) < 0.01
    p.ego_meas = 0.9
    assert abs(p._view(it, 1.0).distance_m - 5.1) < 0.01
    p.ego_meas = 0.1                                       # floor: 0.5 x the cadence speed
    assert abs(p._view(it, 1.0).distance_m - 5.25) < 0.01
    p.ego_meas = 2.0                                       # never faster than the cadence speed
    assert abs(p._view(it, 1.0).distance_m - 4.5) < 0.01


# -- 11. the whole component of an item ---------------------------------------------------------------------------------------------------------

def test_hazards_carry_the_whole_component_with_the_rows_above_the_horizon():
    _, doc, _ = replay("chest0004_review9", sounds=SPEECH125)
    n = above = 0
    for f in doc["frames"]:
        for h in f["hazards"]:
            if h["role"] == "none":
                assert "bboxFull" not in h and "outlineFull" not in h
                continue
            if "bboxFull" not in h:
                assert "outlineFull" not in h
                continue                                    # a ghost / coasting item has no shape
            assert "outline" in h
            n += 1
            x0, y0, x1, y1 = h["bbox"]
            X0, Y0, X1, Y1 = h["bboxFull"]
            assert X0 <= x0 + 1e-6 and Y0 <= y0 + 1e-6 and X1 >= x1 - 1e-6 and Y1 >= y1 - 1e-6
            assert len(h["outlineFull"]) >= 4
            xs, ys = [p[0] for p in h["outlineFull"]], [p[1] for p in h["outlineFull"]]
            assert abs(min(xs) - X0) < 0.01 and abs(max(ys) - Y1) < 0.01 and abs(min(ys) - Y0) < 0.01
            above += Y0 < y0 - 0.01 and Y0 < f["horizonY"]
    assert n > 200 and above > 0                            # (a pole / building / tree top above the horizon)


# -- the review-9 targets (speech rate 1.25, the new default) -----------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def r9():
    meta, doc, ev = replay("chest0004_review9", sounds=SPEECH125)
    return meta, doc, ev["events"]


def _near(events, t, typ, tol=0.7):
    return [e for e in events if e["type"] == typ and abs(e["t"] - t) <= tol]


def test_review9_the_wrong_ones_are_gone(r9):
    _, _, ev = r9
    sp = lambda a, b: [e["text"] for e in ev if e["type"] == "speech" and a <= e["t"] <= b]          # noqa: E731
    assert sp(0.0, 0.7) == []                                                    # 0.17: too close for voice (the beep stays, below)
    assert _near(ev, 0.17, "beeps", 0.2)
    assert sp(0.9, 1.6) == []                                                    # 1.17: "sign at 12:30 in 5, pole at 11:15 in 5" (not in the zone)
    assert not any("pole" in x or "tree" in x for x in sp(18.0, 18.8))           # 18.34: the trunk
    assert not [x for x in sp(23.0, 24.2) if "1:15" in x]                        # 23.51: no swing to 1:15 (the pole is said at 22.84, in the zone)
    assert not _near(ev, 21.0, "beeps", 0.3)                                     # 21.0: the wall that is being followed
    assert not any(e["type"] == "beeps" and "vehicle" in e["label"] and 24.5 <= e["t"] <= 26 for e in ev)      # 25.1: the top of the skip


def test_review9_the_added_phrase_at_13_s_is_there(r9):
    _, _, ev = r9
    s = [e for e in ev if e["type"] == "speech" and 12.8 <= e["t"] <= 13.3]
    assert len(s) == 1 and s[0]["text"].startswith("building at 12 in ")         # the closest of the two markers, the face ahead
    assert "sign" not in s[0]["text"]
    n = int(s[0]["text"].rsplit(" ", 1)[1])
    assert 6 <= n <= 9


def test_review9_the_16_ticks_are_kept_as_the_same_text_within_a_step(r9):
    """Every ✓ of the review: an event of the same type within 0.7 s with the same words; the numbers (clock, steps) may move. The five known to change are
    asserted separately below (their number changes more than a step: ticks 11.66 / 22.84 / 25.29 and 1.84 / 6.84 keep their words)."""
    import re
    meta, _, ev = r9
    norm = lambda t: re.sub(r"[\d:]+", "#", t or "").replace("step", "").strip()               # noqa: E731
    lost = []
    for a in meta["annotations"]:
        if a.get("verdict") != "correct":
            continue
        e0 = a["event"]
        got = [e for e in ev if e["type"] == e0["type"] and abs(e["t"] - a["t"]) <= 0.7 and norm(e.get("text") or e.get("label")) == norm(e0.get("text") or e0.get("label"))]
        if not got:
            lost.append((a["t"], e0.get("text")))
    assert lost == [(25.293, "beeps · center · pole at 11:45 · 3 steps")] or lost == [], lost    # 25.29 merges into the long pole episode from 22.84


def test_review9_the_kept_ticks_move_by_at_most_a_step(r9):
    meta, _, ev = r9
    moved = {}
    for a in meta["annotations"]:
        if a.get("verdict") != "correct" or a["event"]["type"] != "speech":
            continue
        got = [e for e in ev if e["type"] == "speech" and abs(e["t"] - a["t"]) <= 0.7]
        assert got, a["t"]
        moved[a["t"]] = (a["event"]["text"], got[0]["text"])
    assert moved[1.8352][1] == "person at 12 and 12:15 in 7"                     # was 6 (the cap and the measured speed: a step more)
    assert moved[11.6617][1].startswith("building at 12")                       # 12:45 in 2 -> 12:30 in 3: the capped advance (a quarter-hour and a step)


# -- the new defaults pinned (v26.2.12 goldens: events of chest0004_review7 window 0, depth, speech rate 1.25) -----------------------------------------

def _events_hash(**ov) -> str:
    import hashlib
    import json
    from tests.worldtracks_fixtures import run_window
    cfg = copy.deepcopy(CONFIG)
    for k, v in ov.items():
        a, b = k.split("__")
        cfg[a][b] = v
    _, _, ev = run_window("chest0004_review7", 0, "depth", cfg)
    return hashlib.sha256(json.dumps(ev["events"], sort_keys=True).encode()).hexdigest()


# image source + predictive, every v26.2.12 rule on, speech rate 1.25 (the fixture has no sensors: the c2 heading / cadence / horizon sources do not apply)
GOLDEN_IMAGE = "db471b9fa75034fe1539ec9314938e55d57642647e33befa710ee8d4832faa6a"
# the new default (map source) + predictive, every v26.2.12 rule on, speech rate 1.25
GOLDEN_MAP = "5fa473cec608ddad94fb317bbb3975d2ca5ba3312c22bd9545490aeaedca8956"


def test_goldens_of_the_new_defaults_v26212():
    h = (_events_hash(source__mode="image"), _events_hash())
    assert h[0] == GOLDEN_IMAGE, h[0]
    assert h[1] == GOLDEN_MAP, h[1]
