"""v26.2.11 (Lab UI): pending dotted overrides pass validation, the effective object distance."""
import pytest

import collision as col
from lab import collisions


def test_pending_override_keys_are_created_with_allowed_values():
    cfg = col.load_config()
    out = collisions.apply_overrides(cfg, {"collision": {"source.mode": "map", "speech.predictive.enabled": False,
                                                         "ego.headingSource": "imu", "horizon.source": "fused",
                                                         "ego.cadenceSource": "image"}}, "collision")
    assert out["horizon"]["source"] == "fused" and out["source"]["mode"] == "map"
    assert out["ego"]["headingSource"] == "imu" and out["speech"]["predictive"]["enabled"] is False
    assert cfg.get("horizon", {}).get("source") != "fused"          # the loaded config is never mutated


@pytest.mark.parametrize("key,value", [("source.mode", "nope"), ("ego.headingSource", True), ("speech.predictive.enabled", "on"),
                                       ("horizon.mode", "image")])
def test_pending_override_keys_refuse_other_values(key, value):
    with pytest.raises(collisions.CollisionError):
        collisions.apply_overrides(col.load_config(), {"collision": {key: value}}, "collision")


def test_doc_carries_the_effective_object_distance():
    doc = {"settings": {"objectDistance": "ground-contact", "useHorizon": False}, "resolved": {}}
    collisions._add_effective(doc)
    assert doc["objectDistanceEffective"] == "depth" == doc["resolved"]["objectDistanceEffective"]
    doc = {"settings": {"objectDistance": "ground+depth", "useHorizon": True}, "resolved": {}}
    collisions._add_effective(doc)
    assert doc["objectDistanceEffective"] == "ground+depth"
