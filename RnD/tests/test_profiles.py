"""profiles.short_side_spec / resolve_input_spec: the Lab's Np resolution options."""
import pytest

import profiles
from profiles import SHORT_SIDE_OPTIONS, resolve_input_spec, short_side_spec

TABLE = {  # short -> (content w, h, input w, h) for 16:9 UHD/FHD
    544: (960, 540, 960, 544),
    576: (1024, 576, 1024, 576),
    608: (1056, 594, 1056, 608),
    640: (1120, 630, 1120, 640),
    672: (1184, 666, 1184, 672),
    704: (1248, 702, 1248, 704),
    736: (1280, 720, 1280, 736),
}


def test_options():
    assert SHORT_SIDE_OPTIONS == (544, 576, 608, 640, 672, 704, 736)


@pytest.mark.parametrize("src", [(1920, 1080), (3840, 2160)])
@pytest.mark.parametrize("short", SHORT_SIDE_OPTIONS)
def test_landscape_table(src, short):
    cw, ch, iw, ih = TABLE[short]
    spec = short_side_spec(*src, short)
    assert (spec.dst_w, spec.dst_h) == (iw, ih)
    assert spec.is_native_aspect
    assert spec.description == f"{short}p: {cw}x{ch} content of native {src[0]}x{src[1]}, input {iw}x{ih}"


@pytest.mark.parametrize("short", SHORT_SIDE_OPTIONS)
def test_portrait_is_transposed(short):
    cw, ch, iw, ih = TABLE[short]
    spec = short_side_spec(1080, 1920, short)
    assert (spec.dst_w, spec.dst_h) == (ih, iw)
    assert spec.description.startswith(f"{short}p: {ch}x{cw} content")


@pytest.mark.parametrize("src", [(1920, 1080), (3840, 2160), (1080, 1920), (2704, 1520), (1920, 1440)])
@pytest.mark.parametrize("short", SHORT_SIDE_OPTIONS)
def test_multiples_of_32_and_aspect(src, short):
    try:
        spec = short_side_spec(*src, short)
    except ValueError:
        pytest.skip("not reachable without upscaling")
    assert spec.dst_w % 32 == 0 and spec.dst_h % 32 == 0
    assert min(spec.dst_w, spec.dst_h) == short
    # content (parsed from the description) keeps the native aspect within one pixel of rounding
    content = spec.description.split(": ")[1].split(" content")[0]
    cw, ch = map(int, content.split("x"))
    if src[0] >= src[1]:
        assert abs(ch - src[1] * cw / src[0]) <= 0.5
    else:
        assert abs(cw - src[0] * ch / src[1]) <= 0.5
    assert cw <= spec.dst_w and ch <= spec.dst_h and cw <= src[0] and ch <= src[1]


def test_upscale_refused():
    assert short_side_spec(960, 540, 544).dst_w == 960
    for short in SHORT_SIDE_OPTIONS[1:]:
        with pytest.raises(ValueError, match="upscale"):
            short_side_spec(960, 540, short)
    with pytest.raises(ValueError):
        short_side_spec(1280, 32, 544)


def test_resolve_dispatches():
    assert resolve_input_spec(1920, 1080, "576p", None, None).dst_w == 1024
    with pytest.raises(ValueError, match="544p"):
        resolve_input_spec(1920, 1080, "999p", None, None)
    with pytest.raises(ValueError):
        resolve_input_spec(1920, 1080, "576p", "960x544", None)


def test_legacy_profiles_unchanged():
    s = resolve_input_spec(1920, 1080, None, None, None)
    assert (s.dst_w, s.dst_h) == (960, 544)
    s = resolve_input_spec(1920, 1080, "production", None, None)
    assert (s.dst_w, s.dst_h) == profiles.PRODUCTION_SIZE
    s = resolve_input_spec(1920, 1080, "half", None, None)
    assert (s.dst_w, s.dst_h) == (960, 544)
    s = resolve_input_spec(1920, 1080, "quarter", None, None)
    assert (s.dst_w, s.dst_h) == (480, 288)
    s = resolve_input_spec(1920, 1080, "native", None, None)
    assert (s.dst_w, s.dst_h) == (1920, 1088)
