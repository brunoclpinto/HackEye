"""Cadence: step rate from the vertical camera bob, and the standing-still flag from the residual flow."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

import numpy as np
import numpy.typing as npt

if TYPE_CHECKING:
    from collections.abc import Sequence

    from numpy.typing import ArrayLike

FloatArray = npt.NDArray[np.floating[Any]]


def spectrum(seg: FloatArray, dt: float, pad: int = 4) -> tuple[FloatArray, FloatArray]:
    """Power spectrum of a detrended, Hann-windowed window, zero-padded ``pad`` times."""
    n = len(seg)
    x = seg - np.polyval(np.polyfit(np.arange(n), seg, 1), np.arange(n))
    x = x * np.hanning(n)
    nfft = pad * n
    return np.fft.rfftfreq(nfft, dt), np.abs(np.fft.rfft(x, nfft)) ** 2


def refine(freqs: FloatArray, power: FloatArray, k: int, lo: float | None = None, hi: float | None = None) -> float:
    """Parabolic interpolation around bin k.

    v26.1.11 (review 4: one -16.3 Hz cadence at 336 s): the peak search is limited to a band, so bin k can sit on the
    band edge with a larger neighbour outside it, and the parabola then extrapolates far away. A refine that moves by
    more than one bin, or leaves the search band ``[lo, hi]`` (bin-width tolerance), is rejected and the bin centre
    is kept."""
    f = float(freqs[k])
    if 0 < k < len(power) - 1:
        a, b, c = power[k - 1], power[k], power[k + 1]
        denom = a - 2 * b + c
        if denom < 0:
            df = freqs[1] - freqs[0]
            shift = 0.5 * (a - c) / denom * df
            cand = f + shift
            inside = (lo is None or cand >= lo - df) and (hi is None or cand <= hi + df)
            if abs(shift) <= df and inside:
                f = cand
    return f


def peak(freqs: FloatArray, power: FloatArray, lo: float, hi: float, lobe: int) -> tuple[int, float] | None:
    """(bin, ratio) of the strongest peak in [lo, hi].

    The ratio is peak amplitude over the RMS amplitude of the rest of the
    spectrum (the peak's main lobe and slow drift excluded), so pure noise
    gives a small ratio while a steady bob stands out whatever its amplitude.
    """
    band = (freqs >= lo) & (freqs <= hi)
    if not band.any():
        return None
    k = int(np.flatnonzero(band)[np.argmax(power[band])])
    rest_mask = freqs >= 0.25
    rest_mask[max(0, k - lobe) : k + lobe + 1] = False
    if rest_mask.sum() < 4:
        return None
    rest = float(power[rest_mask].mean())
    if rest <= 0:
        return None
    return k, math.sqrt(power[k] / rest)


# A weaker dy peak is accepted when the horizontal sway peaks at the same rhythm:
# noise rarely produces matching peaks in two independent signals.
CORROBORATED_RATIO_FRAC = 0.7


def window_cadence(
    seg: FloatArray,
    dt: float,
    band_hz: tuple[float, float],
    min_peak_ratio: float,
    seg_dx: FloatArray | None = None,
    min_step_hz: float = 1.4,
    harmonic_ratio: float = 0.25,
) -> float:
    """Step cadence of one uniformly sampled window, or nan when there is no clear peak.

    Stride awareness: a chest camera sways and bobs asymmetrically, so the
    dominant vertical peak ``f0`` is often the *stride* (left+right cycle,
    ~1.0-1.1 Hz) and the true step rate is its second harmonic. The step rate is
    taken as the peak near ``2*f0`` when
      * ``f0 < min_step_hz`` (too slow to be walking or running steps), or
      * the spectrum really has a peak there with power >= ``harmonic_ratio``
        times the ``f0`` peak, or
      * the horizontal motion ``dx`` (which sways once per stride) peaks within
        0.15 Hz of ``f0``, i.e. ``f0`` is the stride too.
    Otherwise ``f0`` itself is the step rate (a steady 1.8 Hz walk or a 2.8 Hz run,
    whose double falls outside the band).
    """
    pad = 4
    lobe = 2 * pad + 2  # Hann main lobe half-width in padded bins
    lo, hi = band_hz
    freqs, power = spectrum(seg, dt, pad)
    found = peak(freqs, power, lo, hi, lobe)
    if found is None:
        return math.nan
    k0, ratio0 = found
    f0 = refine(freqs, power, k0, lo, hi)
    fx = None  # stride rhythm seen in dx, if any
    if seg_dx is not None and len(seg_dx) == len(seg):
        xf, xp = spectrum(seg_dx, dt, pad)
        px = peak(xf, xp, 0.7, 1.7, lobe)
        if px is not None and px[1] >= CORROBORATED_RATIO_FRAC * min_peak_ratio:
            fx = refine(xf, xp, px[0], 0.7, 1.7)
    if ratio0 < min_peak_ratio:
        weak_ok = (
            fx is not None
            and ratio0 >= CORROBORATED_RATIO_FRAC * min_peak_ratio
            and (abs(fx - f0) <= 0.15 or abs(2 * fx - f0) <= 0.2)
        )
        if not weak_ok:
            return math.nan
    if 2 * f0 > hi:
        return f0
    win = (freqs >= 2 * f0 - 0.15) & (freqs <= min(2 * f0 + 0.15, hi))
    if not win.any():
        return f0
    k2 = int(np.flatnonzero(win)[np.argmax(power[win])])
    doubled = refine(freqs, power, k2, lo, hi)
    if f0 < min_step_hz or power[k2] >= harmonic_ratio * power[k0]:
        return doubled
    if fx is not None and abs(fx - f0) <= 0.15:
        return doubled
    return f0


def estimate_cadence(
    t: ArrayLike,
    dy: ArrayLike,
    window_s: float,
    band_hz: Sequence[float],
    min_peak_ratio: float,
    dx: ArrayLike | None = None,
    min_step_hz: float = 1.4,
    harmonic_ratio: float = 0.25,
) -> FloatArray:
    """Per-sample step cadence in Hz (nan while unknown) from the vertical camera bob.

    Stride-aware (see ``window_cadence``); ``dx`` is the optional cross-check.
    Causal: the estimate at time ``t`` only uses samples in (t - window_s, t],
    as the on-device version must. Needs at least 60 percent of the window. A
    value is held for one window length when a later window has no clear peak.
    """
    t = np.asarray(t, dtype=float)
    dy = np.asarray(dy, dtype=float)
    out = np.full(len(t), np.nan)
    if len(t) < 8:
        return out
    dt = float(np.median(np.diff(t)))
    if not dt > 0:
        return out
    tu = np.arange(t[0], t[-1] + 1e-9, dt)  # uniform resampling for the FFT
    yu = np.interp(tu, t, dy)
    xu = None if dx is None else np.interp(tu, t, np.asarray(dx, dtype=float))
    win = max(8, int(round(window_s / dt)))  # noqa: RUF046
    min_n = max(8, int(0.6 * win))
    stride = max(1, int(round(0.1 / dt)))  # noqa: RUF046
    band = (float(band_hz[0]), float(band_hz[1]))
    est_t: Any  # list while collecting, ndarray afterwards
    est_f: Any
    est_t, est_f = [], []
    for j in range(min_n - 1, len(tu), stride):
        sl = slice(max(0, j - win + 1), j + 1)
        est_t.append(tu[j])
        est_f.append(
            window_cadence(
                yu[sl], dt, band, min_peak_ratio, None if xu is None else xu[sl], min_step_hz, harmonic_ratio
            )
        )
    if not est_t:
        return out
    est_t, est_f = np.array(est_t), np.array(est_f)
    idx = np.searchsorted(est_t, t + 1e-9, side="right") - 1  # latest estimate <= t
    ok = idx >= 0
    out[ok] = est_f[idx[ok]]
    return hold_last(t, out, window_s)


def hold_last(t: FloatArray, series: FloatArray, hold_s: float) -> FloatArray:
    """Forward-fill nan for up to ``hold_s`` after the last valid value: cadence changes slowly,
    and a window that momentarily has no clear peak should not blank the estimate."""
    out = series.copy()
    last, last_t = math.nan, -math.inf
    for i in range(len(t)):
        if not math.isnan(series[i]):
            last, last_t = series[i], t[i]
        elif t[i] - last_t <= hold_s:
            out[i] = last
    return out


def estimate_stationary(t: ArrayLike, resid: ArrayLike, cfg: dict[str, Any]) -> npt.NDArray[np.bool_]:
    """Per-sample "the user is standing still" flag from the residual image flow (``egoflow``; v26.1.11, review 4).

    The cadence detector cannot tell standing from walking (a standing user's chest camera bobs at 1-2 Hz too: review 4,
    286-345 s read 1.3-2.2 Hz and 1.1 m/s), the picture can: walking expands it, standing leaves the scene rigid.
    ``m`` = causal median of the residual flow (px) over ``medianSeconds`` (needs half the window valid). Stationary is
    entered after ``m < enterPx`` for ``enterSeconds`` and left after ``m >= leavePx`` for ``leaveSeconds``. A frame
    without texture (m unknown) never enters, and counts as walking evidence when leaving (a false "stationary" silences
    the warnings, a false "walking" only says too much). 4929: standing 308-346 s m 0.07-0.58, walking m >= 1.34."""
    t = np.asarray(t, dtype=float)
    r = np.asarray(resid, dtype=float)
    out = np.zeros(len(t), dtype=bool)
    if len(t) < 2:
        return out
    dt = float(np.median(np.diff(t)))
    if not dt > 0:
        return out
    n = max(3, int(round(float(cfg.get("medianSeconds", 1.0)) / dt)))  # noqa: RUF046
    enter_px, leave_px = float(cfg.get("enterPx", 0.8)), float(cfg.get("leavePx", 1.0))
    enter_s, leave_s = float(cfg.get("enterSeconds", 1.5)), float(cfg.get("leaveSeconds", 1.0))
    state, since = False, None
    for i in range(len(t)):
        w = r[max(0, i - n + 1) : i + 1]
        w = w[~np.isnan(w)]
        m = float(np.median(w)) if len(w) >= 0.5 * n else math.nan
        if not state:
            if m < enter_px:
                since = t[i] if since is None else since
                if t[i] - since >= enter_s - 1e-9:
                    state, since = True, None
            else:
                since = None
        else:  # noqa: PLR5501
            if math.isnan(m) or m >= leave_px:
                since = t[i] if since is None else since
                if t[i] - since >= leave_s - 1e-9:
                    state, since = False, None
            else:
                since = None
        out[i] = state
    return out
