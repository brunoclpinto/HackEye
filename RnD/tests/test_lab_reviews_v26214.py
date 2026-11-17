"""v26.2.14: reviewing something at time t counts every earlier notification of that collision run without a verdict as correct (`auto: true`)."""
import json

import pytest

from lab import analysis, collisions, reviews

RUN = "abcdef012345"
EVENTS = [
    {"type": "speech", "t": 1.0, "text": "pole at 12 in 8", "role": "feature", "trackId": 1},
    {"type": "beeps", "t": 2.0, "tEnd": 3.0, "text": "beeps · center · pole at 12 · 4→2 steps", "role": "danger", "kind": "collision-center"},
    {"type": "speech", "t": 4.0, "text": "person at 1 in 6", "role": "danger", "trackId": 2},
    {"type": "beeps", "t": 5.0, "tEnd": 5.5, "text": "soft · person at 1 · 3→2 steps", "role": "danger", "kind": "proximity"},
    {"type": "tone", "t": 2.0, "frequencyHz": 440},
    {"type": "speech", "t": 7.0, "text": "later", "role": "context"},
]


@pytest.fixture
def lab(tmp_path, monkeypatch):
    monkeypatch.setattr(reviews, "LAB_DIR", tmp_path)
    run = {"id": RUN, "collisions": ["c1", "c2"], "collisionVersion": "v", "analysisVersion": "a", "modelName": "m"}
    monkeypatch.setattr(analysis, "get_run", lambda rid: run if rid == RUN else None)
    monkeypatch.setattr(collisions, "read_doc", lambda rid, cid: {"collisionVersion": "v"})
    root = tmp_path / "collisions"
    for cid in ("c1", "c2"):
        (root / cid).mkdir(parents=True)
        (root / cid / "events.json").write_text(json.dumps({"events": EVENTS if cid == "c1" else EVENTS[:1]}))
    monkeypatch.setattr(collisions, "collision_dir", lambda rid, cid: root / cid)
    return tmp_path


def _verdict(ev, verdict="correct", cid="c1"):
    return {"kind": "verdict", "verdict": verdict, "runId": RUN, "collisionId": cid, "event": ev}


def _anns():
    return reviews.list_annotations("rec")["annotations"]


def test_a_verdict_counts_every_earlier_unreviewed_notification_correct(lab):
    res = reviews.create("rec", 60.0, _verdict({"t": 5.0, "text": EVENTS[3]["text"], "type": "beeps", "tEnd": 5.5}, "incorrect"))
    assert [a["event"]["t"] for a in res["autoCreated"]] == [1.0, 2.0, 4.0]
    anns = _anns()
    assert len(anns) == 4 and [a["t"] for a in anns] == [1.0, 2.0, 4.0, 5.0]
    autos = anns[:3]
    assert all(a["auto"] and a["verdict"] == "correct" and a["collisionId"] == "c1" and a["runId"] == RUN for a in autos)
    assert autos[1]["event"]["type"] == "beeps" and autos[1]["event"]["tEnd"] == 3.0
    assert "auto" not in anns[3] and anns[3]["verdict"] == "incorrect"
    assert "autoCreated" not in anns[3]                         # response only


def test_an_existing_verdict_is_kept_and_nothing_later_is_touched(lab):
    reviews.create("rec", 60.0, _verdict({"t": 2.0, "text": EVENTS[1]["text"], "type": "beeps", "tEnd": 3.0}, "remove"))
    reviews.create("rec", 60.0, _verdict({"t": 4.0, "text": EVENTS[2]["text"]}))
    by_t = {a["t"]: a for a in _anns()}
    assert by_t[2.0]["verdict"] == "remove" and "auto" not in by_t[2.0]
    assert by_t[1.0]["auto"] and "auto" not in by_t[4.0]
    assert 5.0 not in by_t and 7.0 not in by_t


def test_an_added_item_also_counts_earlier_events_and_other_collision_runs_are_left_alone(lab):
    res = reviews.create("rec", 60.0, {"kind": "added", "t": 4.5, "text": "person cutting in front", "role": "final", "runId": RUN, "collisionId": "c1"})
    assert [a["t"] for a in res["autoCreated"]] == [1.0, 2.0, 4.0]
    res2 = reviews.create("rec", 60.0, {"kind": "added", "t": 9.0, "text": "x", "runId": RUN, "collisionId": "c2"})
    assert [a["t"] for a in res2["autoCreated"]] == [1.0]       # c2 has one event: its own verdict key (collision c2) is separate
    assert sorted((a["collisionId"], a["t"]) for a in _anns() if a["kind"] == "verdict") == [("c1", 1.0), ("c1", 2.0), ("c1", 4.0), ("c2", 1.0)]


def test_an_added_item_without_a_run_creates_nothing_automatic(lab):
    res = reviews.create("rec", 60.0, {"kind": "added", "t": 9.0, "text": "x"})
    assert "autoCreated" not in res and len(_anns()) == 1


def test_the_export_carries_auto_and_editing_or_a_note_drops_it(lab):
    reviews.create("rec", 60.0, _verdict({"t": 4.0, "text": EVENTS[2]["text"]}))
    exp = reviews.export(["rec"])["recordings"][0]
    assert exp["summary"]["correct"] == 3 and [a.get("auto") for a in exp["annotations"]] == [True, True, None]
    first, second = _anns()[0], _anns()[1]
    assert reviews.update("rec", 60.0, first["id"], {"verdict": "incorrect"}).get("auto") is None
    assert reviews.update("rec", 60.0, second["id"], {"note": "fine"}).get("auto") is None
    assert [a.get("auto") for a in _anns()] == [None, None, None]


def test_deleting_the_later_verdict_keeps_the_auto_ones(lab):
    res = reviews.create("rec", 60.0, _verdict({"t": 4.0, "text": EVENTS[2]["text"]}))
    reviews.delete("rec", res["id"])
    assert [a["t"] for a in _anns()] == [1.0, 2.0] and all(a["auto"] for a in _anns())
