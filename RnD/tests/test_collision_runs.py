"""v26.2.8: collision runs (c1, c2, ...) of one analysis run: ids, storage, overrides, endpoints, compare, delete, reviews."""
import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

import collision as col
import worldmap
from lab import analysis, collisions, recordings, reviews, server

RUN = "0123456789ab"
REC = {"id": "rec1", "duration": 100.0, "width": 320, "height": 180, "fps": 10.0, "chapters": [], "name": "rec1"}


@pytest.fixture
def lab(monkeypatch, tmp_path):
    monkeypatch.setattr(recordings, "get_recording", lambda i: REC if i == "rec1" else None)
    for mod in (analysis, recordings):
        monkeypatch.setattr(mod, "LAB_DIR", tmp_path)
    monkeypatch.setattr(reviews, "LAB_DIR", tmp_path)
    monkeypatch.setattr(analysis, "_active", {})
    monkeypatch.setattr(server, "_wm_cache", server.OrderedDict())
    monkeypatch.setattr(server, "_hz_cache", server.OrderedDict())
    d = tmp_path / "runs" / RUN
    d.mkdir(parents=True)
    (d / "run.json").write_text(json.dumps({"id": RUN, "request": {"recording": "rec1"}, "status": "done", "classNames": ["a"],
                                            "createdAt": "2026-10-31T10:00:00Z"}))
    np.savez(d / "grids.npz", grids=np.zeros((3, 135, 240), np.uint8), t=np.arange(3.0), index=np.arange(3))
    return TestClient(server.app), d


def post(c, body=None):
    r = c.post(f"/api/runs/{RUN}/collision", json=body if body is not None else {})
    assert r.status_code == 200, r.text
    return r.json()


def test_ids_are_sequential_and_never_reused(lab):
    c, d = lab
    assert [post(c)["id"] for _ in range(3)] == ["c1", "c2", "c3"]
    assert c.delete(f"/api/runs/{RUN}/collisions/c3").status_code == 200
    assert post(c)["id"] == "c4"                         # c3 stays burnt
    run = c.get(f"/api/runs/{RUN}").json()
    assert run["collisions"] == ["c1", "c2", "c4"] and run["collisionSeq"] == 4
    for cid in ("c1", "c2", "c4"):                        # identical settings: both folders kept, nothing at the top level
        assert (d / "collisions" / cid / "hazards.json").exists() and (d / "collisions" / cid / "worldmap.npz").exists()
    assert not (d / "hazards.json").exists() and not (d / "events.json").exists() and not (d / "worldmap.npz").exists()
    doc = json.loads((d / "collisions" / "c1" / "collision.json").read_text())
    assert doc["id"] == "c1" and doc["runId"] == RUN and doc["overrides"] == {} and doc["label"] == ""
    assert doc["counts"] == {"speech": 0, "beeps": 0} and doc["worldmapVersion"] and doc["collisionVersion"]
    assert {"mount", "objectDistance"} <= set(doc["settings"]) and "distanceSource" in doc["resolved"]


def test_job_makes_c1(lab):
    c, d = lab
    doc = analysis.collision_pass(RUN)
    analysis._build_worldmap(RUN, doc["id"])
    assert doc["id"] == "c1" and (d / "collisions" / "c1" / "worldmap.npz").exists()


def test_outputs_read_by_collision_and_latest_by_default(lab):
    c, d = lab
    post(c); post(c)
    ev1 = d / "collisions" / "c1" / "events.json"
    ev1.write_text(json.dumps({"events": [{"t": 1.0, "type": "speech", "text": "only c1"}]}))
    assert c.get(f"/api/runs/{RUN}/events.json?collision=c1").json()["events"][0]["text"] == "only c1"
    assert c.get(f"/api/runs/{RUN}/events.json").json()["events"] == []              # the latest (c2)
    assert c.get(f"/api/runs/{RUN}/events.json?collision=c9").status_code == 404
    assert c.get(f"/api/runs/{RUN}/hazards.json?collision=c1").status_code == 200
    assert c.get(f"/api/runs/{RUN}/hazards?from=0&to=5&collision=c1").status_code == 200
    assert c.get(f"/api/runs/{RUN}/hazards?from=0&to=5&collision=c9").status_code == 404
    for cid in ("c1", "c2"):
        m = c.get(f"/api/runs/{RUN}/worldmap?collision={cid}").json()
        assert m["exists"] and m["collision"] == cid
        assert c.get(f"/api/runs/{RUN}/worldmap/0.png?collision={cid}").status_code == 200
        assert c.get(f"/api/runs/{RUN}/worldmap/pose.json?collision={cid}").status_code == 200
    assert c.get(f"/api/runs/{RUN}/worldmap?collision=c9").status_code == 404
    assert {k[1] for k in server._wm_cache} <= {"c1", "c2"} and all(k[0] == RUN for k in server._hz_cache)
    assert ("0123456789ab", "c1") in server._hz_cache


def test_run_without_collisions(lab):
    c, d = lab
    assert c.get(f"/api/runs/{RUN}/collisions").json() == []
    assert c.get(f"/api/runs/{RUN}/events.json").status_code == 404
    assert c.get(f"/api/runs/{RUN}/worldmap").json() == {"exists": False}


def test_overrides_are_validated(lab):
    c, d = lab
    cases = [({"collision": {"distance.nope": "off"}}, "distance.nope"),
             ({"collision": {"distance.itemLens": 3}}, "distance.itemLens"),          # string -> number
             ({"worldmap": {"gapCloseM": "wide"}}, "gapCloseM"),                       # number -> string
             ({"worldmap": {"faceClasses": "building"}}, "faceClasses"),                # list -> string
             ({"worldmap": {"faceGroundContact": 1}}, "faceGroundContact"),            # bool -> number
             ({"collision": {"distance": 1}}, "distance"),                              # a section
             ({"other": {}}, "other"), ({"collision": ["x"]}, "collision"), ("x", "overrides")]
    for ov, key in cases:
        r = c.post(f"/api/runs/{RUN}/collision", json={"overrides": ov})
        assert r.status_code == 422 and key in r.json()["detail"], (ov, r.text)
    assert c.get(f"/api/runs/{RUN}/collisions").json() == []          # nothing was created, no id burnt
    assert post(c)["id"] == "c1"


def test_overrides_are_applied_stored_and_reach_both_map_builders(lab, monkeypatch):
    c, d = lab
    seen = {}
    real_run, real_build = col.run_collision, worldmap.build

    def spy_run(grids, times, names, config, settings, *a, **k):
        seen["item_lens"] = config["distance"]["itemLens"]
        seen["run_wcfg"] = k.get("worldmap_config")
        return real_run(grids, times, names, config, settings, *a, **k)

    def spy_build(grids, times, names, hazards, ccfg, cfg=None, depth=None, hook=None):
        seen["build_gap"] = cfg["gapCloseM"]
        seen["build_lens"] = ccfg["distance"]["itemLens"]
        return real_build(grids, times, names, hazards, ccfg, cfg, depth, hook)

    monkeypatch.setattr(col, "run_collision", spy_run)
    monkeypatch.setattr(worldmap, "build", spy_build)
    base_lens, base_gap = col.load_config()["distance"]["itemLens"], worldmap.load_config()["gapCloseM"]
    ov = {"collision": {"distance.itemLens": "off"}, "worldmap": {"gapCloseM": 0}}
    doc = post(c, {"overrides": ov, "label": "lens off"})
    assert doc["overrides"] == ov and doc["label"] == "lens off"
    assert seen["item_lens"] == "off" and seen["run_wcfg"]["gapCloseM"] == 0          # the collision pass's online map
    assert seen["build_gap"] == 0 and seen["build_lens"] == "off"                      # worldmap_pass
    assert col.load_config()["distance"]["itemLens"] == base_lens and worldmap.load_config()["gapCloseM"] == base_gap
    assert json.loads((d / "collisions" / "c1" / "collision.json").read_text())["overrides"] == ov
    # a rebuild of the map reuses the stored overrides
    seen.clear()
    assert c.post(f"/api/runs/{RUN}/worldmap?collision=c1").status_code == 200
    assert seen["build_gap"] == 0 and seen["build_lens"] == "off"


def test_label(lab):
    c, d = lab
    post(c)
    r = c.patch(f"/api/runs/{RUN}/collisions/c1", json={"label": "  first try "})
    assert r.status_code == 200 and r.json()["label"] == "first try"
    assert c.get(f"/api/runs/{RUN}/collisions").json()[0]["label"] == "first try"
    assert c.patch(f"/api/runs/{RUN}/collisions/c1", json={"label": "x" * 61}).status_code == 422
    assert c.patch(f"/api/runs/{RUN}/collisions/c1", json={"label": 3}).status_code == 422
    assert c.patch(f"/api/runs/{RUN}/collisions/c7", json={"label": "x"}).status_code == 404


def write_events(d, cid, events):
    (d / "collisions" / cid / "events.json").write_text(json.dumps({"events": events}))


def test_compare(lab):
    c, d = lab
    post(c)
    post(c, {"overrides": {"collision": {"distance.itemLens": "off"}}})
    sp = lambda t, text: {"t": t, "type": "speech", "text": text}
    bp = lambda t, kind, clock, text: {"t": t, "type": "beeps", "kind": kind, "clock": clock, "text": text}
    write_events(d, "c1", [sp(1.0, "pole 12"), sp(5.0, "car 3"), sp(9.0, "bench"), bp(2.0, "collision-left", 11, "beeps a"),
                           {"t": 3.0, "type": "tone", "text": "t"}, sp(20.0, "gone")])
    write_events(d, "c2", [sp(1.4, "pole 12"), sp(5.5, "car 2"), sp(9.0, "bench"), bp(2.5, "collision-left", 11, "beeps b"),
                           sp(30.0, "new"), {"t": 3.0, "type": "tone", "text": "t"}])
    r = c.get(f"/api/runs/{RUN}/collisions/compare?a=c1&b=c2")
    assert r.status_code == 200, r.text
    j = r.json()
    assert (j["a"], j["b"]) == ("c1", "c2")
    keys = {s["key"]: s for s in j["settings"]}
    assert keys["overrides.collision.distance.itemLens"]["a"] is None and keys["overrides.collision.distance.itemLens"]["b"] == "off"
    ev = j["events"]
    assert ev["same"] == 3                                                  # pole 12, bench, the beeps (same kind + clock)
    assert [(x["a"]["text"], x["b"]["text"]) for x in ev["changed"]] == [("car 3", "car 2")]
    assert [e["text"] for e in ev["onlyA"]] == ["gone"] and [e["text"] for e in ev["onlyB"]] == ["new"]
    assert ev["onlyA"][0]["t"] == 20.0 and ev["onlyA"][0]["type"] == "speech"
    assert c.get(f"/api/runs/{RUN}/collisions/compare?a=c1&b=c9").status_code == 404


def test_match_events_is_greedy_nearest_first_and_uses_each_once():
    sp = lambda t, text: {"t": t, "type": "speech", "text": text}
    m = collisions.match_events([sp(1.0, "x"), sp(1.9, "x")], [sp(1.6, "x")])
    assert m["same"] == 1 and len(m["onlyA"]) == 1 and m["onlyA"][0]["t"] == 1.0       # 1.9 is nearer to 1.6
    assert collisions.match_events([sp(0.0, "x")], [sp(1.01, "x")])["same"] == 0       # beyond 1.0 s


def test_delete_refused_for_the_only_one_and_for_reviewed_ones(lab):
    c, d = lab
    post(c)
    r = c.delete(f"/api/runs/{RUN}/collisions/c1")
    assert r.status_code == 409 and "only" in r.json()["detail"]
    post(c)
    ev = {"t": 1.0, "text": "pole 12", "type": "speech"}
    a = c.post("/api/recordings/rec1/reviews", json={"kind": "verdict", "verdict": "correct", "t": 1.0, "event": ev, "runId": RUN,
                                                     "collisionId": "c2"})
    assert a.status_code == 201 and a.json()["collisionId"] == "c2"
    r = c.delete(f"/api/runs/{RUN}/collisions/c2")
    assert r.status_code == 409 and "1 review" in r.json()["detail"]
    assert (d / "collisions" / "c2").is_dir()
    assert c.delete(f"/api/runs/{RUN}/collisions/c1").status_code == 200              # no reviews on c1
    assert not (d / "collisions" / "c1").exists()
    assert c.get(f"/api/runs/{RUN}").json()["collisions"] == ["c2"]


def test_reviews_store_collision_id_and_export_it_with_settings(lab):
    c, d = lab
    post(c)
    post(c, {"overrides": {"collision": {"distance.itemLens": "off"}}})
    ev = {"t": 1.0, "text": "pole 12", "type": "speech"}
    body = {"kind": "verdict", "verdict": "correct", "t": 1.0, "event": ev, "runId": RUN}
    default = c.post("/api/recordings/rec1/reviews", json=body).json()
    assert default["collisionId"] == "c2"                                             # none named: the latest
    other = c.post("/api/recordings/rec1/reviews", json={**body, "collisionId": "c1"})
    assert other.status_code == 201 and other.json()["collisionId"] == "c1"           # same event on another collision run: allowed
    assert c.post("/api/recordings/rec1/reviews", json={**body, "collisionId": "c1"}).status_code == 409
    assert c.post("/api/recordings/rec1/reviews", json={**body, "collisionId": "c9"}).status_code == 404
    exp = c.get("/api/reviews/export?recording=rec1").json()["recordings"][0]["annotations"]
    by = {a["collisionId"]: a for a in exp}
    assert by["c2"]["overrides"] == {"collision": {"distance.itemLens": "off"}} and by["c1"]["overrides"] == {}
    assert "settings" in by["c2"] and "resolved" in by["c2"]
    assert reviews.count_for_collision("rec1", RUN, "c1") == 1


def test_legacy_review_without_collision_id_counts_for_c1(lab):
    c, d = lab
    post(c)
    reviews._save("rec1", {"recording": "rec1", "annotations": [{"id": "a1", "kind": "verdict", "verdict": "correct", "t": 1.0,
                                                                  "event": {"t": 1.0, "text": "x"}, "runId": RUN}]})
    assert reviews.count_for_collision("rec1", RUN, "c1") == 1 and reviews.count_for_collision("rec1", RUN, "c2") == 0
