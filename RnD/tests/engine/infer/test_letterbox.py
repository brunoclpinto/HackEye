"""Characterisation tests for engine.infer.segmentation.letterbox (v26.3.0 p5-01).

Every literal was printed by the legacy ``letterbox.letterbox_with_meta`` / ``geometry.letterbox_params`` /
``LetterboxMeta`` methods in the hackeye-rnd image before the move. The engine modules are imported inside each test.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any

import numpy as np
import pytest

import geometry
import letterbox

if TYPE_CHECKING:
    from numpy.typing import NDArray

META_FIELDS = ["src_w", "src_h", "dst_w", "dst_h", "scale", "pad_x", "pad_y"]


def _img(h: int, w: int) -> NDArray[Any]:
    return (np.arange(h * w * 3).reshape(h, w, 3) * 7 % 256).astype(np.uint8)


def test_facade_identity() -> None:
    from engine.infer.segmentation import letterbox as eng

    assert letterbox.letterbox_with_meta is eng.letterbox_with_meta
    assert geometry.LetterboxMeta is eng.LetterboxMeta
    assert geometry.letterbox_params is eng.letterbox_params


def test_geometry_keeps_box_helpers() -> None:
    from engine.core.geom import Box

    assert geometry.Box is Box
    b = geometry.expand_box(Box(10, 10, 20, 20), 100, 100, 0.5)
    assert (b.x1, b.y1, b.x2, b.y2) == (5.0, 5.0, 25.0, 25.0)
    c = geometry.expand_box(Box(0, 0, 20, 20), 15, 15, 0.5)
    assert (c.x1, c.y1, c.x2, c.y2) == (0.0, 0.0, 15, 15)
    d = geometry.expand_box(Box(10, 10, 20, 20), 100, 100, 0)
    assert (d.x1, d.y1, d.x2, d.y2) == (10, 10, 20, 20)
    assert callable(geometry._clamp_box)


def test_meta_fields() -> None:
    from engine.infer.segmentation.letterbox import LetterboxMeta

    assert [f.name for f in dataclasses.fields(LetterboxMeta)] == META_FIELDS


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ((6, 4, 8, 8), (6.0, 4.0, 8.0, 8.0, 1.3333333333333333, 0.0, 1.5)),
        ((1920, 1080, 1280, 736), (1920.0, 1080.0, 1280.0, 736.0, 0.6666666666666666, 0.0, 8.0)),
        ((4, 6, 8, 8), (4.0, 6.0, 8.0, 8.0, 1.3333333333333333, 1.5, 0.0)),
        ((8, 8, 8, 8), (8.0, 8.0, 8.0, 8.0, 1.0, 0.0, 0.0)),
    ],
)
def test_letterbox_params(args: tuple[int, int, int, int], expected: tuple[float, ...]) -> None:
    from engine.infer.segmentation.letterbox import letterbox_params

    assert dataclasses.astuple(letterbox_params(*args)) == expected


def test_meta_box_mapping() -> None:
    from engine.core.geom import Box
    from engine.infer.segmentation.letterbox import letterbox_params

    m = letterbox_params(1920, 1080, 1280, 736)
    assert dataclasses.astuple(m.dst_to_src(Box(10, 20, 300, 400))) == (15.0, 18.0, 450.0, 588.0)
    assert dataclasses.astuple(m.clamp_to_src(Box(-5, -6, 2000, 1100))) == (0.0, 0.0, 1920.0, 1080.0)


def test_letterbox_with_meta_pixels() -> None:
    from engine.infer.segmentation.letterbox import letterbox_with_meta

    out, meta = letterbox_with_meta(_img(4, 6), 8, 8)
    assert out.shape == (8, 8, 3)
    assert out.dtype == np.uint8
    assert int(out.sum()) == 14873
    assert out[:, :, 0].tolist() == [
        [0, 0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0, 0],
        [0, 13, 29, 44, 60, 76, 92, 105],
        [88, 101, 117, 133, 148, 164, 180, 193],
        [189, 122, 90, 106, 121, 137, 153, 166],
        [213, 114, 62, 78, 94, 110, 126, 139],
        [122, 135, 151, 166, 182, 198, 214, 227],
        [0, 0, 0, 0, 0, 0, 0, 0],
    ]
    assert out.reshape(8, -1).sum(1).tolist() == [0, 0, 1426, 3541, 3068, 2484, 4354, 0]
    assert dataclasses.astuple(meta) == (6.0, 4.0, 8.0, 8.0, 1.3333333333333333, 0.0, 1.5)


def test_letterbox_with_meta_keeps_dtype_and_shape() -> None:
    from engine.infer.segmentation.letterbox import letterbox_with_meta

    out, _ = letterbox_with_meta(_img(4, 6).astype(np.float32), 5, 9)
    assert out.shape == (9, 5, 3)
    assert out.dtype == np.float32
