import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


import pytest  # noqa: E402

# v26.2.10 changed what the map keeps (facts only, confrontation, pose alignment) and how people are cut into items. The tests that pin
# the reviewed outputs of earlier versions run on the v26.2.9 map settings (``decay: time`` ... see ``worldtracks_fixtures.v2629_configs``);
# the v26.2.10 behaviour has its own tests (test_worldmap_v26210, test_collision_v26210) and the golden of test_orientation.
_V2629_MAP = {"decay": "time", "conflictFactor": 1.0, "voteCap": 0.0, "poseAlign": False, "gapCloseM": 0.5, "faceThicknessM": 0.3}
_CURRENT = ("test_worldmap_v26210", "test_collision_v26210", "test_orientation", "test_collision_v26212_fixture", "test_collision_v26212",
            "test_collision_v26213_fixture", "test_collision_v26213", "test_collision_v26214_fixture", "test_collision_v26214")


@pytest.fixture(autouse=True, scope="module")
def _v2629_map_settings(request):
    if request.module.__name__.rsplit(".", 1)[-1] in _CURRENT:
        yield
        return
    import collision
    import worldmap
    mp = pytest.MonkeyPatch()
    real = worldmap.load_config
    mp.setattr(worldmap, "load_config", lambda path=None: {**real(path), **_V2629_MAP})
    real_c = collision.load_config

    def _cfg(path=None):
        c = real_c(path) if path is not None else real_c()
        c["personSplit"]["enabled"] = False
        return c
    mp.setattr(collision, "load_config", _cfg)
    yield
    mp.undo()


# v26.2.11: ``speech.predictive.enabled`` is on by default (the phrase says where the item will be when it ends). Every test that pins the
# phrases of an earlier version runs with it off: ``collision.load_config`` returns it off for any caller except the modules below (the
# caller is looked at, because several test modules read the config at import time, before any fixture runs).
_PREDICTIVE_OK = ("replay", "test_orientation", "test_collision_v26210", "test_collision_v26211", "test_worldtracks_v26211", "test_lab_v26211_ui",
                  "test_sensors_v26211", "test_collision_v26212_fixture", "test_collision_v26212", "test_collision_v26213_fixture", "test_collision_v26213",
                  "test_collision_v26214_fixture", "test_collision_v26214")


# v26.2.12: c2 is the default (map source, IMU heading / cadence, fused horizon) and the new speech / beep rules are on. Every module that pins the
# phrases of an earlier version runs with the v26.2.11 settings (``V26211_SETTINGS``, same dotted keys the Lab's overrides use) for the same
# reason as above; the modules below test the v26.2.12 defaults.
_V26212_OK = ("replay", "test_collision_v26212", "test_collision_v26212_fixture", "test_lab_reviews_v26212", "test_sensors_v26212",
              "test_collision_v26213", "test_collision_v26213_fixture", "test_collision_v26214", "test_collision_v26214_fixture")
V26211_SETTINGS = {("source", "mode"): "image", ("ego", "headingSource"): "auto", ("ego", "cadenceSource"): "auto", ("horizon", "source"): "gravity",
                   ("speech", "minVoiceSteps"): 0, ("speech", "thinStableS"): 0, ("speech", "colocatedM"): 0, ("speech", "zoneOnly", "enabled"): False,
                   ("speech", "reannounce", "enabled"): False, ("speech", "predictive", "maxAdvanceM"): 0, ("speech", "predictive", "clockHoldQuarters"): 0,
                   ("speech", "predictive", "measuredFloor"): 0, ("distance", "jump", "enabled"): False, ("tree", "enabled"): False,
                   ("beeps", "follow", "enabled"): False, ("blocked", "enabled"): False, ("ego", "stepLength", "source"): "prior"}


# v26.2.13: the walls-followed ratio rule, the known-wall memory, "moved away" and the soft beeps for a person passing close are on by default.
# The modules that pin the v26.2.12 output run with them off (``replay.replay`` has no caller of its own: the module running is looked at).
_V26213_OK = ("test_collision_v26213", "test_collision_v26213_fixture", "test_lab_reviews_v26213", "test_collision_v26214", "test_collision_v26214_fixture")
V26212_SETTINGS = {("beeps", "follow", "windowS"): 0, ("speech", "knownWall", "enabled"): False, ("speech", "away", "enabled"): False,
                   ("beeps", "passing", "enabled"): False}


# v26.2.14: the movers' own motion (near-collision course, side, cutting in front, moving away, parked vehicles), the width rule of the "blocked" obstacle kind
# and the whole component of every hazards item are on by default. The modules that pin the v26.2.13 output run with them off.
_V26214_OK = ("test_collision_v26214", "test_collision_v26214_fixture")
V26213_SETTINGS = {("motion", "enabled"): False, ("blocked", "obstacle", "minWidthM"): 0.0, ("output", "fullAllItems"): False}
_STATE = {"module": ""}


@pytest.fixture(autouse=True, scope="module")
def _module_name(request):
    _STATE["module"] = request.module.__name__.rsplit(".", 1)[-1]
    yield
    _STATE["module"] = ""


def legacy_settings(c: dict) -> dict:
    for path, v in V26211_SETTINGS.items():
        d = c
        for k in path[:-1]:
            d = d[k]
        d[path[-1]] = v
    return c


def pytest_configure(config):
    import collision
    real = collision.load_config

    def _cfg(path=None):
        c = real(path) if path is not None else real()
        caller = sys._getframe(1).f_globals.get("__name__", "").rsplit(".", 1)[-1]
        if caller not in _PREDICTIVE_OK:
            c["speech"]["predictive"]["enabled"] = False
        if caller not in _V26212_OK:
            legacy_settings(c)
        module = _STATE["module"] if caller in ("replay", "worldtracks_fixtures", "collision_score") else caller
        if module not in _V26213_OK:
            for path, v in V26212_SETTINGS.items():
                d = c
                for k in path[:-1]:
                    d = d[k]
                d[path[-1]] = v
        if module not in _V26214_OK:
            for path, v in V26213_SETTINGS.items():
                d = c
                for k in path[:-1]:
                    d = d[k]
                d[path[-1]] = v
        return c
    collision.load_config = _cfg
