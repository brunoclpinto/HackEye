"""Characterisation tests for engine.infer.segmentation mapping / grid / model (v26.3.0 p5-01).

Every literal was printed by the legacy ``segmentation`` functions in the hackeye-rnd image before the move, using the
synthetic inputs built here. The engine modules are imported inside each test (they do not exist yet).
"""

from __future__ import annotations

import dataclasses
import json
from typing import TYPE_CHECKING, Any

import numpy as np
import pytest

import geometry
import segmentation

if TYPE_CHECKING:
    from numpy.typing import NDArray

IDS = [[21, 21, 24, 24], [21, 21, 24, 24], [4, 4, 5, 5], [4, 4, 5, 5]]


def _hackeye48_names() -> list[str]:
    data: dict[str, Any] = json.loads((segmentation._CONFIG_DIR / "safety_mapping_hackeye48.json").read_text())
    return [c["name"] for c in sorted(data["classes"], key=lambda c: c["id"])]


def _vistas_names() -> list[str]:
    return [segmentation.CLASSES[i]["name"] for i in sorted(segmentation.CLASSES)]


def _meta() -> Any:
    return geometry.letterbox_params(6, 4, 8, 8)


def _mask_blocks() -> NDArray[Any]:
    mask = np.full((8, 8), 21)
    mask[2:6, 2:6] = 24
    mask[3, 3] = 30
    return mask


def test_facade_identity() -> None:
    from engine.infer.segmentation import grid, mapping

    names = ["CLASSES", "SAFETY_LEVELS", "find_mapping", "select_mapping", "_load_mapping", "_CONFIG_DIR"]
    names.append("_CONFIG_PATH")
    for name in names:
        assert getattr(segmentation, name) is getattr(mapping, name), name
    for name in [
        "SegmentationGrid",
        "_mask_padding_and_finish",
        "parse_grid",
        "grid_from_semantic_mask",
        "extract_objects",
        "_convex_hull",
        "_4_CONNECTIVITY",
    ]:
        assert getattr(segmentation, name) is getattr(grid, name), name


def test_scalar_globals_forward_current_values() -> None:
    from engine.infer.segmentation import mapping

    assert segmentation.NUM_CLASSES == mapping.NUM_CLASSES == 124
    assert segmentation.SKY_CLASS_ID == mapping.SKY_CLASS_ID == 61


def test_default_mapping() -> None:
    from engine.infer.segmentation import mapping

    assert len(mapping.CLASSES) == 124
    assert mapping.CLASSES[21]["name"] == "flat road"
    assert mapping.CLASSES[21]["safetyLevel"] == 3
    assert mapping.CLASSES[mapping.SKY_CLASS_ID]["name"] == "nature sky"
    assert sorted(mapping.SAFETY_LEVELS) == [0, 1, 2, 3, 4]
    assert mapping.SAFETY_LEVELS[3] == {"label": "danger", "color": [255, 0, 0]}
    assert mapping._CONFIG_PATH.name == "safety_mapping.json"


def test_find_mapping_is_pure() -> None:
    from engine.infer.segmentation import mapping

    path, classes, levels = mapping.find_mapping(_hackeye48_names())
    assert path.name == "safety_mapping_hackeye48.json"
    assert len(classes) == 48
    assert sorted(levels) == [0, 1, 2, 3, 4]
    assert mapping.find_mapping(_vistas_names())[0].name == "safety_mapping.json"
    assert segmentation.NUM_CLASSES == 124
    assert len(segmentation.CLASSES) == 124


def test_find_mapping_unknown_names() -> None:
    from engine.infer.segmentation import mapping

    with pytest.raises(ValueError, match="No safety mapping") as exc:
        mapping.find_mapping(["a", "b"])
    tail = "names. Add a safety_mapping_<name>.json whose classes list the model's names in id order."
    assert str(exc.value).endswith(tail)


def test_select_mapping_rebinds_facade_scalars() -> None:
    from engine.infer.segmentation import mapping

    classes, levels = segmentation.CLASSES, segmentation.SAFETY_LEVELS
    vistas = _vistas_names()
    try:
        path = mapping.select_mapping(_hackeye48_names())
        assert path.name == "safety_mapping_hackeye48.json"
        assert segmentation.NUM_CLASSES == mapping.NUM_CLASSES == 48
        assert segmentation.SKY_CLASS_ID == mapping.SKY_CLASS_ID == 30
        assert segmentation.CLASSES is classes is mapping.CLASSES
        assert segmentation.SAFETY_LEVELS is levels is mapping.SAFETY_LEVELS
        assert len(classes) == 48
        assert classes[segmentation.SKY_CLASS_ID]["name"] == "nature sky"
        assert sorted(levels) == [0, 1, 2, 3, 4]
    finally:
        path = mapping.select_mapping(vistas)
    assert path.name == "safety_mapping.json"
    assert segmentation.NUM_CLASSES == mapping.NUM_CLASSES == 124
    assert segmentation.SKY_CLASS_ID == mapping.SKY_CLASS_ID == 61
    assert len(classes) == 124


def test_select_mapping_unknown_names_changes_nothing() -> None:
    from engine.infer.segmentation import mapping

    with pytest.raises(ValueError, match="No safety mapping"):
        mapping.select_mapping(["a", "b"])
    assert segmentation.NUM_CLASSES == 124
    assert len(segmentation.CLASSES) == 124


def test_grid_fields() -> None:
    from engine.infer.segmentation.grid import SegmentationGrid

    assert [f.name for f in dataclasses.fields(SegmentationGrid)] == ["grid_w", "grid_h", "class_ids", "safety_levels"]


def test_parse_grid() -> None:
    from engine.infer.segmentation.grid import parse_grid

    raw = np.zeros((1, 124, 4, 4), np.float32)
    for r in range(4):
        for c in range(4):
            raw[0, IDS[r][c], r, c] = 1.0
    g = parse_grid(raw, _meta())
    assert (g.grid_w, g.grid_h) == (4, 4)
    assert g.class_ids.dtype == np.int32
    assert g.safety_levels.dtype == np.int32
    assert g.class_ids.tolist() == [[21, 21, 24, 24], [21, 21, 24, 24], [4, 4, 5, 5], [4, 4, 5, 5]]
    assert g.safety_levels.tolist() == [[3, 3, 1, 1], [3, 3, 1, 1], [2, 2, 4, 4], [2, 2, 4, 4]]
    g3 = parse_grid(raw[0], _meta())
    assert g3.class_ids.tolist() == g.class_ids.tolist()


def test_parse_grid_wrong_class_count() -> None:
    from engine.infer.segmentation.grid import parse_grid

    with pytest.raises(ValueError, match="produced 5 classes, expected 124") as exc:
        parse_grid(np.zeros((1, 5, 4, 4)), _meta())
    assert str(exc.value) == (
        "Segmentation model produced 5 classes, expected 124 (per the selected safety mapping). "
        "This model may not be the semantic-segmentation checkpoint expected here "
        "— see RnD/README.md model verification notes."
    )


def test_grid_from_semantic_mask_pads_with_sky() -> None:
    from engine.infer.segmentation.grid import grid_from_semantic_mask

    mask = np.repeat(np.repeat(np.array(IDS), 2, axis=0), 2, axis=1)
    mask[0:2, :] = 21
    mask[3, 3] = 30
    g = grid_from_semantic_mask(mask, _meta())
    assert (g.grid_w, g.grid_h) == (8, 8)
    assert g.class_ids.dtype == np.int32
    assert g.class_ids.tolist() == [
        [61, 61, 61, 61, 61, 61, 61, 61],
        [21, 21, 21, 21, 21, 21, 21, 21],
        [21, 21, 21, 21, 24, 24, 24, 24],
        [21, 21, 21, 30, 24, 24, 24, 24],
        [4, 4, 4, 4, 5, 5, 5, 5],
        [4, 4, 4, 4, 5, 5, 5, 5],
        [4, 4, 4, 4, 5, 5, 5, 5],
        [61, 61, 61, 61, 61, 61, 61, 61],
    ]
    assert g.safety_levels.tolist() == [
        [0, 0, 0, 0, 0, 0, 0, 0],
        [3, 3, 3, 3, 3, 3, 3, 3],
        [3, 3, 3, 3, 1, 1, 1, 1],
        [3, 3, 3, 4, 1, 1, 1, 1],
        [2, 2, 2, 2, 4, 4, 4, 4],
        [2, 2, 2, 2, 4, 4, 4, 4],
        [2, 2, 2, 2, 4, 4, 4, 4],
        [0, 0, 0, 0, 0, 0, 0, 0],
    ]


def test_grid_uses_current_mapping_after_select() -> None:
    """The grid code must read NUM_CLASSES / SKY_CLASS_ID from the mapping module at call time."""
    from engine.infer.segmentation import mapping
    from engine.infer.segmentation.grid import extract_objects, grid_from_semantic_mask, parse_grid

    vistas = _vistas_names()
    try:
        mapping.select_mapping(_hackeye48_names())
        mask = np.full((8, 8), 3)
        mask[3:5, 3:5] = 10
        g = grid_from_semantic_mask(mask, _meta())
        assert g.class_ids.tolist() == [
            [30, 30, 30, 30, 30, 30, 30, 30],
            [3, 3, 3, 3, 3, 3, 3, 3],
            [3, 3, 3, 3, 3, 3, 3, 3],
            [3, 3, 3, 10, 10, 3, 3, 3],
            [3, 3, 3, 10, 10, 3, 3, 3],
            [3, 3, 3, 3, 3, 3, 3, 3],
            [3, 3, 3, 3, 3, 3, 3, 3],
            [30, 30, 30, 30, 30, 30, 30, 30],
        ]
        assert g.safety_levels.tolist() == [
            [0, 0, 0, 0, 0, 0, 0, 0],
            [4, 4, 4, 4, 4, 4, 4, 4],
            [4, 4, 4, 4, 4, 4, 4, 4],
            [4, 4, 4, 3, 3, 4, 4, 4],
            [4, 4, 4, 3, 3, 4, 4, 4],
            [4, 4, 4, 4, 4, 4, 4, 4],
            [4, 4, 4, 4, 4, 4, 4, 4],
            [0, 0, 0, 0, 0, 0, 0, 0],
        ]
        raw = np.zeros((1, 48, 4, 4), np.float32)
        raw[0, 3] = 1
        raw[0, 10, 1:3, 1:3] = 2
        pg = parse_grid(raw, _meta())
        assert pg.class_ids.tolist() == [[3, 3, 3, 3], [3, 10, 10, 3], [3, 10, 10, 3], [3, 3, 3, 3]]
        assert pg.safety_levels.tolist() == [[4, 4, 4, 4], [4, 3, 3, 4], [4, 3, 3, 4], [4, 4, 4, 4]]
        objs = extract_objects(pg, _meta(), 1)
        assert [(o["classId"], o["className"], o["safetyLevelName"], o["pixelCount"], o["polygon"]) for o in objs] == [
            (3, "barrier fence", "death", 12, [{"x": 1, "y": 0}, {"x": 5, "y": 0}, {"x": 5, "y": 3}, {"x": 1, "y": 3}]),
            (10, "parking", "danger", 4, [{"x": 2, "y": 1}, {"x": 4, "y": 1}, {"x": 4, "y": 3}, {"x": 2, "y": 3}]),
        ]
    finally:
        mapping.select_mapping(vistas)
    assert segmentation.NUM_CLASSES == 124


def test_extract_objects_scaled_meta() -> None:
    from engine.infer.segmentation.grid import extract_objects, grid_from_semantic_mask

    g = grid_from_semantic_mask(_mask_blocks(), _meta())
    assert g.class_ids.tolist() == [
        [61, 61, 61, 61, 61, 61, 61, 61],
        [21, 21, 21, 21, 21, 21, 21, 21],
        [21, 21, 24, 24, 24, 24, 21, 21],
        [21, 21, 24, 30, 24, 24, 21, 21],
        [21, 21, 24, 24, 24, 24, 21, 21],
        [21, 21, 24, 24, 24, 24, 21, 21],
        [21, 21, 21, 21, 21, 21, 21, 21],
        [61, 61, 61, 61, 61, 61, 61, 61],
    ]
    assert extract_objects(g, _meta(), 1) == [
        {
            "classId": 21,
            "className": "flat road",
            "safetyLevel": 3,
            "safetyLevelName": "danger",
            "pixelCount": 32,
            "polygon": [{"x": 0, "y": 0}, {"x": 5, "y": 0}, {"x": 5, "y": 3}, {"x": 0, "y": 3}],
        },
        {
            "classId": 24,
            "className": "flat sidewalk",
            "safetyLevel": 1,
            "safetyLevelName": "safe",
            "pixelCount": 15,
            "polygon": [{"x": 2, "y": 1}, {"x": 4, "y": 1}, {"x": 4, "y": 3}, {"x": 2, "y": 3}],
        },
        {
            "classId": 30,
            "className": "person individual",
            "safetyLevel": 4,
            "safetyLevelName": "death",
            "pixelCount": 1,
            "polygon": [{"x": 3, "y": 2}],
        },
    ]


def test_extract_objects_large_source_and_min_pixels() -> None:
    from engine.infer.segmentation.grid import extract_objects, grid_from_semantic_mask

    g = grid_from_semantic_mask(_mask_blocks(), _meta())
    meta2 = geometry.letterbox_params(60, 40, 8, 8)
    objs = extract_objects(g, meta2, 1)
    assert objs == [
        {
            "classId": 21,
            "className": "flat road",
            "safetyLevel": 3,
            "safetyLevelName": "danger",
            "pixelCount": 32,
            "polygon": [{"x": 4, "y": 0}, {"x": 56, "y": 0}, {"x": 56, "y": 38}, {"x": 4, "y": 38}],
        },
        {
            "classId": 24,
            "className": "flat sidewalk",
            "safetyLevel": 1,
            "safetyLevelName": "safe",
            "pixelCount": 15,
            "polygon": [{"x": 19, "y": 8}, {"x": 41, "y": 8}, {"x": 41, "y": 30}, {"x": 19, "y": 30}],
        },
        {
            "classId": 30,
            "className": "person individual",
            "safetyLevel": 4,
            "safetyLevelName": "death",
            "pixelCount": 1,
            "polygon": [{"x": 26, "y": 15}],
        },
    ]
    assert [(o["classId"], o["pixelCount"]) for o in extract_objects(g, meta2, 5)] == [(21, 32), (24, 15)]


def test_convex_hull() -> None:
    from engine.infer.segmentation.grid import _convex_hull

    square = [(0, 0), (2, 0), (2, 2), (0, 2), (1, 1), (1, 0), (0, 1)]
    assert _convex_hull(square) == [(0, 0), (2, 0), (2, 2), (0, 2)]
    assert _convex_hull([(1, 1), (0, 0)]) == [(1, 1), (0, 0)]
    assert _convex_hull([(0, 0), (1, 1), (2, 2), (3, 3)]) == [(0, 0), (3, 3)]
    assert _convex_hull([]) == []


def test_models_facade_identity() -> None:
    import models
    from engine.infer.segmentation import model

    assert models.SegmentationModel is model.SegmentationModel
    assert models.to_ultralytics is model.to_ultralytics
    assert models.load_detector is model.load_detector


def test_to_ultralytics_flips_channels() -> None:
    from engine.infer.segmentation.model import to_ultralytics

    rgb = np.arange(2 * 3 * 3, dtype=np.uint8).reshape(2, 3, 3)
    out = to_ultralytics(rgb)
    assert out.flags["C_CONTIGUOUS"]
    assert out.shape == rgb.shape
    assert out[..., 0].tolist() == rgb[..., 2].tolist()
    assert out[..., 1].tolist() == rgb[..., 1].tolist()
    assert out[..., 2].tolist() == rgb[..., 0].tolist()
