"""v26.2.12: a verdict on a predictive phrase keeps its `predicted` block (and clockText) in the annotation, so the export carries it."""
import pytest

from lab import analysis, collisions, reviews

PRED = {"dt": 1.99, "phraseS": 3.77, "dts": [1.99, 3.77], "steps": 5, "clock": "12:30", "fwd": 3.59, "right": 0.76, "stepsNow": 6,
        "textNow": "sign at 12:15 in 6"}


@pytest.fixture
def lab(tmp_path, monkeypatch):
    monkeypatch.setattr(reviews, "LAB_DIR", tmp_path)
    run = {"id": "abcdef012345", "collisions": ["c1"], "collisionVersion": "v", "analysisVersion": "a", "modelName": "m"}
    monkeypatch.setattr(analysis, "get_run", lambda rid: run if rid == run["id"] else None)
    monkeypatch.setattr(collisions, "read_doc", lambda rid, cid: {"collisionVersion": "v"})
    return tmp_path


def _body(**ev):
    return {"kind": "verdict", "verdict": "correct", "runId": "abcdef012345", "collisionId": "c1",
            "event": {"t": 1.17, "text": "sign at 12:30 in 5", "role": "feature", "clockText": "12:15", **ev}}


def test_predicted_block_is_kept_in_the_annotation_and_the_export(lab):
    a = reviews.create("rec", 60.0, _body(predicted=PRED))
    assert a["event"]["predicted"] == PRED and a["event"]["clockText"] == "12:15"
    ann = reviews.export(["rec"])["recordings"][0]["annotations"][0]
    assert ann["event"]["predicted"]["textNow"] == "sign at 12:15 in 6"


def test_a_malformed_predicted_value_is_dropped(lab):
    a = reviews.create("rec", 60.0, _body(predicted="yes"))
    assert "predicted" not in a["event"]
