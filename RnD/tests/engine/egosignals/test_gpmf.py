"""Characterisation of engine.egosignals.gpmf (p2-03). Literals were produced by the legacy sensors.py (v26.2.x)."""

from __future__ import annotations

import math
import struct
from typing import TYPE_CHECKING

import numpy as np
import pytest

if TYPE_CHECKING:
    from pathlib import Path


def _approx(v: float) -> object:
    return pytest.approx(v, rel=1e-12, abs=1e-12)


def _klv(key: bytes, typ: bytes, size: int, rep: int, body: bytes) -> bytes:
    pad = (-len(body)) % 4
    return key + typ + bytes([size]) + struct.pack(">H", rep) + body + b"\0" * pad


def _devc(
    gyro_rows: list[tuple[int, int, int]],
    accl_rows: list[tuple[int, int, int]],
    fix: int = 3,
    dop: int = 150,
) -> bytes:
    g = b"".join(struct.pack(">hhh", *r) for r in gyro_rows)
    a = b"".join(struct.pack(">hhh", *r) for r in accl_rows)
    gps = b"".join(struct.pack(">lllll", *r) for r in [(413628997, -87580331, 58243, 1500, 160)] * 3)
    sg = _klv(b"SCAL", b"s", 2, 1, struct.pack(">h", 100)) + _klv(b"GYRO", b"s", 6, len(gyro_rows), g)
    sa = _klv(b"SCAL", b"s", 2, 1, struct.pack(">h", 10)) + _klv(b"ACCL", b"s", 6, len(accl_rows), a)
    sp = (
        _klv(b"SCAL", b"l", 4, 5, struct.pack(">lllll", 10000000, 10000000, 1000, 1000, 100))
        + _klv(b"GPSF", b"L", 4, 1, struct.pack(">L", fix))
        + _klv(b"GPSP", b"S", 2, 1, struct.pack(">H", dop))
        + _klv(b"GPSU", b"c", 16, 1, b"261104091522.000")
        + _klv(b"GPS5", b"l", 20, 3, gps)
    )
    body = b"".join(b"STRM" + b"\0" + bytes([1]) + struct.pack(">H", len(s)) + s for s in (sg, sa, sp))
    return b"DEVC" + b"\0" + bytes([1]) + struct.pack(">H", len(body)) + body


def _p1() -> bytes:
    return _devc([(100, 200, -300), (50, 0, 0)], [(98, -3, 7), (98, 0, 0), (98, 0, 0), (98, 0, 0)])


def _p2() -> bytes:
    return _devc([(0, 0, 0)] * 4, [(98, 0, 0)] * 2, fix=0, dop=9999)


def _atom(typ: bytes, body: bytes) -> bytes:
    return struct.pack(">I4s", 8 + len(body), typ) + body


def _mp4(counts: list[int]) -> bytes:
    h = struct.pack(">I", len(counts)) + b"".join(struct.pack(">I", x) for x in counts)
    udta = _atom(b"udta", _atom(b"HMMT", h))
    return _atom(b"ftyp", b"mp41\0\0\0\0") + _atom(b"moov", _atom(b"mvhd", b"\0" * 8) + udta)


def test_facade_identity() -> None:
    import sensors
    from engine.egosignals import gpmf

    for old, new in [
        ("_FMT", "_FMT"),
        ("_STREAMS", "_STREAMS"),
        ("_klv", "_klv"),
        ("_numbers", "_numbers"),
        ("parse_payload", "parse_payload"),
        ("split_payloads", "split_payloads"),
        ("_gpmd_stream", "_gpmd_stream"),
        ("_utc_epoch", "_utc_epoch"),
        ("build", "build"),
        ("extract", "extract"),
        ("hilights", "hilights"),
        ("concat", "concat"),
        ("save", "save"),
        ("load", "load"),
    ]:
        assert getattr(sensors, old) is getattr(gpmf, new), old
    assert callable(gpmf.extract)


def test_constants() -> None:
    from engine.egosignals import gpmf

    want = {"b": "b", "B": "B", "s": "h", "S": "H", "l": "i", "L": "I", "j": "q", "J": "Q", "f": "f", "d": "d"}
    assert dict(gpmf._FMT) == want
    assert gpmf._STREAMS == ("GYRO", "ACCL", "GPS5", "SHUT", "ISOG")


def test_klv_and_numbers() -> None:
    from engine.egosignals import gpmf

    assert list(gpmf._klv(_klv(b"SCAL", b"s", 2, 1, struct.pack(">h", 100)))) == [("SCAL", "s", 2, 1, b"\x00d")]
    assert list(gpmf._klv(b"")) == []
    a = gpmf._numbers("s", 2, 1, struct.pack(">h", -5))
    assert a is not None and a.tolist() == [[-5.0]]
    assert gpmf._numbers("x", 2, 1, b"ab") is None
    assert gpmf._numbers("s", 2, 2, b"ab") is None
    assert gpmf._numbers("s", 0, 1, b"") is None


def test_parse_payload() -> None:
    from engine.egosignals import gpmf

    got = gpmf.parse_payload(_p1())
    assert list(got) == ["GYRO", "ACCL", "GPS5"]
    assert got["GYRO"]["data"].shape == (2, 3)
    assert got["GYRO"]["data"].tolist() == [[1.0, 2.0, -3.0], [0.5, 0.0, 0.0]]
    assert (got["GYRO"]["fix"], got["GYRO"]["dop"], got["GYRO"]["utc"]) == (None, None, None)
    assert got["ACCL"]["data"].shape == (4, 3)
    assert got["ACCL"]["data"][0].tolist() == pytest.approx([9.8, -0.3, 0.7], rel=1e-12, abs=1e-12)
    assert got["ACCL"]["data"][1].tolist() == pytest.approx([9.8, 0.0, 0.0], rel=1e-12, abs=1e-12)
    g5 = got["GPS5"]
    assert g5["data"].shape == (3, 5)
    assert g5["data"][0].tolist() == pytest.approx([41.3628997, -8.7580331, 58.243, 1.5, 1.6], rel=1e-12, abs=1e-12)
    assert g5["fix"] == 3 and g5["dop"] == 1.5 and g5["utc"] == "261104091522.000"
    assert gpmf.parse_payload(b"") == {}


def test_split_payloads() -> None:
    from engine.egosignals import gpmf

    p1, p2 = _p1(), _p2()
    assert len(p1) == 252 and len(p2) == 252
    assert gpmf.split_payloads(p1 + p2) == [p1, p2]
    assert gpmf.split_payloads(p1 + p2 + b"XXXX1234") == [p1, p2]
    assert gpmf.split_payloads(b"") == []
    assert gpmf.split_payloads(b"ABCD\0\0\0\0") == []


def test_build() -> None:
    from engine.egosignals import gpmf

    out = gpmf.build([_p1(), _p2()], [(0.0, 1.0), (1.0, 2.0)])
    assert list(out) == ["gyro", "gyro_t", "accl", "accl_t", "gps", "gps_t", "gps_fix", "gps_dop", "gps_utc"]
    assert out["gyro"].shape == (6, 3) and out["accl"].shape == (6, 3) and out["gps"].shape == (6, 5)
    assert out["gyro"][:2].tolist() == [[1.0, 2.0, -3.0], [0.5, 0.0, 0.0]]
    assert float(np.abs(out["gyro"][2:]).sum()) == 0.0
    assert out["gyro_t"].tolist() == _approx_list([0.25, 0.75, 1.25, 1.75, 2.25, 2.75])
    assert out["accl_t"].tolist() == _approx_list([0.125, 0.375, 0.625, 0.875, 1.5, 2.5])
    assert out["gps_t"].tolist() == _approx_list(
        [0.16666666666666666, 0.5, 0.8333333333333334, 1.3333333333333333, 2.0, 2.666666666666667]
    )
    assert out["gps_fix"].dtype == np.int64 and out["gps_fix"].tolist() == [3, 3, 3, 0, 0, 0]
    assert out["gps_dop"].tolist() == _approx_list([1.5, 1.5, 1.5, 99.99, 99.99, 99.99])
    assert out["gps_utc"].tolist() == [1793783722.0] * 6
    assert gpmf.build([], []) == {}


def _approx_list(v: list[float]) -> list[object]:
    return [_approx(x) for x in v]


def test_utc_epoch() -> None:
    from engine.egosignals import gpmf

    assert gpmf._utc_epoch("261104091522.000") == 1793783722.0
    assert gpmf._utc_epoch("261104091522.500") == 1793783722.5
    for bad in (None, "", "short", "26110409152x.0", "261304091522.000"):
        assert math.isnan(gpmf._utc_epoch(bad)), bad


def test_concat() -> None:
    from engine.egosignals import gpmf

    a = gpmf.build([_p1()], [(0.0, 1.0)])
    b = gpmf.build([_p2()], [(0.0, 2.0)])
    c = gpmf.concat([(0.0, a), (10.0, b)])
    assert c is not None
    assert list(c) == ["gyro", "gyro_t", "accl", "accl_t", "gps", "gps_t", "gps_fix", "gps_dop", "gps_utc"]
    assert c["gyro"].shape == (6, 3) and c["accl"].shape == (6, 3) and c["gps"].shape == (6, 5)
    assert c["gyro_t"].tolist() == _approx_list([0.25, 0.75, 10.25, 10.75, 11.25, 11.75])
    assert c["accl_t"].tolist() == _approx_list([0.125, 0.375, 0.625, 0.875, 10.5, 11.5])
    assert c["gps_t"].tolist() == _approx_list(
        [0.16666666666666666, 0.5, 0.8333333333333334, 10.333333333333334, 11.0, 11.666666666666666]
    )
    assert c["gps_fix"].tolist() == [3, 3, 3, 0, 0, 0]
    assert c["gps_dop"].tolist() == _approx_list([1.5, 1.5, 1.5, 99.99, 99.99, 99.99])
    assert c["gps_utc"].tolist() == [1793783722.0] * 6
    assert gpmf.concat([]) is None
    assert gpmf.concat([(1.0, {})]) is None


def test_hilights(tmp_path: Path) -> None:
    from engine.egosignals import gpmf

    cases: list[tuple[str, bytes, list[float]]] = [
        ("a", _mp4([1500, 12250, 3]), [1.5, 12.25, 0.003]),
        ("b", _mp4([]), []),
        (
            "c",
            _atom(b"ftyp", b"mp41\0\0\0\0") + _atom(b"moov", _atom(b"udta", _atom(b"free", b"zz"))),
            [],
        ),
        ("d", b"", []),
        ("e", _atom(b"moov", _atom(b"udta", _atom(b"HMMT", struct.pack(">I", 5) + struct.pack(">I", 2000)))), [2.0]),
    ]
    for name, data, want in cases:
        p = tmp_path / name
        p.write_bytes(data)
        assert gpmf.hilights(str(p)) == want, name
    assert gpmf.hilights(str(tmp_path / "nope")) == []


def test_save_load_round_trip(tmp_path: Path) -> None:
    from engine.egosignals import gpmf

    out = gpmf.build([_p1(), _p2()], [(0.0, 1.0), (1.0, 2.0)])
    dest = tmp_path / "sub" / "x.npz"
    gpmf.save(dest, out)
    assert [p.name for p in (tmp_path / "sub").iterdir()] == ["x.npz"]
    back = gpmf.load(dest)
    assert back is not None
    assert sorted(back) == ["accl", "accl_t", "gps", "gps_dop", "gps_fix", "gps_t", "gps_utc", "gyro", "gyro_t"]
    for k, v in out.items():
        assert back[k].dtype == v.dtype
        assert np.array_equal(back[k], v)
    assert gpmf.load(tmp_path / "nope.npz") is None
    bad = tmp_path / "bad.npz"
    bad.write_bytes(b"garbage")
    assert gpmf.load(bad) is None
