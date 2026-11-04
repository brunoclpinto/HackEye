import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


import pytest  # noqa: E402

# v26.2.10 changed what the map keeps (facts only, confrontation, pose alignment) and how people are cut into items. The tests that pin
# the reviewed outputs of earlier versions run on the v26.2.9 map settings (``decay: time`` ... see ``worldtracks_fixtures.v2629_configs``);
# the v26.2.10 behaviour has its own tests (test_worldmap_v26210, test_collision_v26210) and the golden of test_orientation.
_V2629_MAP = {"decay": "time", "conflictFactor": 1.0, "voteCap": 0.0, "poseAlign": False, "gapCloseM": 0.5, "faceThicknessM": 0.3}
_CURRENT = ("test_worldmap_v26210", "test_collision_v26210", "test_orientation")


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
_PREDICTIVE_OK = ("test_orientation", "test_collision_v26210", "test_collision_v26211", "test_worldtracks_v26211", "test_lab_v26211_ui",
                  "test_sensors_v26211")


def pytest_configure(config):
    import collision
    real = collision.load_config

    def _cfg(path=None):
        c = real(path) if path is not None else real()
        caller = sys._getframe(1).f_globals.get("__name__", "").rsplit(".", 1)[-1]
        if caller not in _PREDICTIVE_OK:
            c["speech"]["predictive"]["enabled"] = False
        return c
    collision.load_config = _cfg
