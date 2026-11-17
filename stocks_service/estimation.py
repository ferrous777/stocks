"""Corrected time/outcome estimators over a PointInTimeView (daily sessions).

Fixes relative to legacy ``time_estimation/``:
* ATR in chronological order (legacy read bars newest-first and used the *next* day's close).
* Monte Carlo resamples the symbol's own returns (no forced drift), is seeded from
  (symbol, asof, version), and reports hit probabilities; no ``max_days`` placeholder
  when no path reaches the target.
* Drift estimate refuses when drift is not in the trade's direction (legacy used |drift|
  and an assumed 0.5%/day fallback).
* Pattern estimate counts every comparable start point, hits and misses (legacy counted
  only successes, biasing timing and giving no probability).
* No "SVM" estimator (it was never trained).

These are unvalidated until the phase-3 walk-forward check; outputs carry ``valid`` flags.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field

import numpy as np

from .strategies.indicators import atr
from .strategies.view import PointInTimeView

ESTIMATION_VERSION = "estimation@1"
HORIZON_SESSIONS = 126


@dataclass(frozen=True)
class Estimate:
    name: str
    days_to_target: float | None
    days_to_stop: float | None = None
    p_target: float | None = None
    p_stop: float | None = None
    p_neither: float | None = None
    range_low: float | None = None
    range_high: float | None = None
    note: str = ""


@dataclass(frozen=True)
class EnsembleEstimate:
    valid: bool
    days_to_target: float | None
    range_low: float | None
    range_high: float | None
    p_target: float | None
    p_stop: float | None
    p_neither: float | None
    components: tuple[Estimate, ...] = field(default_factory=tuple)
    reason: str = ""
    version: str = ESTIMATION_VERSION


def _sign(side: str) -> int:
    if side not in ("long", "short"):
        raise ValueError(f"side must be long or short, got {side!r}")
    return 1 if side == "long" else -1


def _log_returns(view: PointInTimeView, n: int) -> np.ndarray:
    c = view.c[-(n + 1):]
    return np.diff(np.log(c))


def atr_estimate(view: PointInTimeView, entry: float, target: float, stop: float, side: str,
                 period: int = 14, directional_factor: float = 0.4) -> Estimate:
    """Distance / (ATR x directional factor). The factor is a heuristic parameter pending validation."""
    if len(view) < period + 1:
        return Estimate("atr", None, note="insufficient_bars")
    a = atr(view.h, view.l, view.c, period)
    if a <= 0:
        return Estimate("atr", None, note="zero_atr")
    rate = a * directional_factor
    return Estimate("atr", abs(target - entry) / rate, abs(entry - stop) / rate)


def drift_estimate(view: PointInTimeView, entry: float, target: float, side: str, lookback: int = 60) -> Estimate:
    if len(view) < lookback + 1:
        return Estimate("drift", None, note="insufficient_bars")
    drift = float(np.mean(_log_returns(view, lookback))) * _sign(side)
    if drift <= 0:
        return Estimate("drift", None, note="drift_against_trade")
    return Estimate("drift", abs(math.log(target / entry)) / drift)


def _seed(symbol: str, asof, salt: str) -> int:
    return int.from_bytes(hashlib.sha256(f"{symbol}|{asof.isoformat()}|{salt}".encode()).digest()[:8], "big")


def monte_carlo_estimate(view: PointInTimeView, entry: float, target: float, stop: float, side: str,
                         lookback: int = 250, paths: int = 2000, horizon: int = HORIZON_SESSIONS) -> Estimate:
    """Bootstrap the last `lookback` daily log returns; first touch of target/stop on closes."""
    if len(view) < lookback + 1:
        return Estimate("monte_carlo", None, note="insufficient_bars")
    rets = _log_returns(view, lookback)
    rng = np.random.default_rng(_seed(view.symbol, view.asof, ESTIMATION_VERSION))
    sims = rng.choice(rets, size=(paths, horizon), replace=True).cumsum(axis=1)
    lt, ls = math.log(target / entry), math.log(stop / entry)
    s = _sign(side)
    hit_t = (sims * s) >= (lt * s)
    hit_s = (sims * s) <= (ls * s)
    first_t = np.where(hit_t.any(axis=1), hit_t.argmax(axis=1) + 1, horizon + 1)
    first_s = np.where(hit_s.any(axis=1), hit_s.argmax(axis=1) + 1, horizon + 1)
    target_first = (first_t < first_s) & (first_t <= horizon)
    stop_first = (first_s < first_t) & (first_s <= horizon)
    p_t, p_s = float(target_first.mean()), float(stop_first.mean())
    days_t = first_t[target_first]
    days_s = first_s[stop_first]
    return Estimate(
        "monte_carlo",
        float(np.median(days_t)) if len(days_t) else None,
        float(np.median(days_s)) if len(days_s) else None,
        p_target=p_t, p_stop=p_s, p_neither=1.0 - p_t - p_s,
        range_low=float(np.percentile(days_t, 25)) if len(days_t) else None,
        range_high=float(np.percentile(days_t, 75)) if len(days_t) else None,
        note="" if len(days_t) else "no_path_reached_target",
    )


def pattern_estimate(view: PointInTimeView, entry: float, target: float, stop: float, side: str,
                     lookback: int = 504, horizon: int = HORIZON_SESSIONS, min_samples: int = 20) -> Estimate:
    """Empirical first-touch outcomes from every past start point with comparable volatility.

    Only start points whose full horizon ends on or before asof are used (no unresolved outcomes).
    """
    c = view.c[-lookback:]
    if len(c) < horizon + 30:
        return Estimate("pattern", None, note="insufficient_bars")
    up, dn = (target / entry, stop / entry) if side == "long" else (stop / entry, target / entry)
    rets = np.diff(np.log(c))
    vol_now = float(np.std(rets[-20:]))
    t_days, s_days, n = [], [], 0
    for i in range(20, len(c) - horizon):
        vol_i = float(np.std(rets[i - 20:i]))
        if vol_now > 0 and not (0.5 <= vol_i / vol_now <= 2.0):
            continue
        n += 1
        path = c[i + 1:i + 1 + horizon] / c[i]
        hit_up = np.nonzero(path >= up)[0]
        hit_dn = np.nonzero(path <= dn)[0]
        first_up = hit_up[0] + 1 if len(hit_up) else horizon + 1
        first_dn = hit_dn[0] + 1 if len(hit_dn) else horizon + 1
        t_first, s_first = (first_up, first_dn) if side == "long" else (first_dn, first_up)
        if t_first < s_first and t_first <= horizon:
            t_days.append(t_first)
        elif s_first < t_first and s_first <= horizon:
            s_days.append(s_first)
    if n < min_samples:
        return Estimate("pattern", None, note=f"only_{n}_comparable_samples")
    return Estimate(
        "pattern",
        float(np.median(t_days)) if t_days else None,
        float(np.median(s_days)) if s_days else None,
        p_target=len(t_days) / n, p_stop=len(s_days) / n, p_neither=1 - (len(t_days) + len(s_days)) / n,
        range_low=float(np.percentile(t_days, 25)) if t_days else None,
        range_high=float(np.percentile(t_days, 75)) if t_days else None,
        note="" if t_days else "no_sample_reached_target",
    )


def ensemble_estimate(view: PointInTimeView, entry: float, target: float, stop: float, side: str) -> EnsembleEstimate:
    comps = (
        atr_estimate(view, entry, target, stop, side),
        drift_estimate(view, entry, target, side),
        monte_carlo_estimate(view, entry, target, stop, side),
        pattern_estimate(view, entry, target, stop, side),
    )
    days = [e.days_to_target for e in comps if e.days_to_target is not None]
    mc = comps[2]
    if len(days) < 2:
        return EnsembleEstimate(False, None, None, None, mc.p_target, mc.p_stop, mc.p_neither, comps,
                                reason=f"only {len(days)} estimator(s) produced a time estimate")
    return EnsembleEstimate(True, float(np.median(days)), mc.range_low, mc.range_high, mc.p_target, mc.p_stop,
                            mc.p_neither, comps)
