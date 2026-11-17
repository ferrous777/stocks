"""Ported strategies (see docs/strategy_audit.md). Each is pure: view + params -> Signal.

Strengths are ranking scores in [0, 1], not probabilities.
"""

from __future__ import annotations

import numpy as np

from .base import Signal, StrategySpec, clamp01, get_spec, register
from .indicators import atr, ema_series, roc, rsi_sma, sma
from .view import PointInTimeView


# --- moving average ----------------------------------------------------------

def ma_crossover(view: PointInTimeView, p: dict) -> Signal:
    c = view.c
    s, l = sma(c, p["short"]), sma(c, p["long"])
    ps, pl = sma(c[:-1], p["short"]), sma(c[:-1], p["long"])
    spread, prev = (s - l) / l, (ps - pl) / pl
    feat = {"sma_short": s, "sma_long": l, "spread": spread, "prev_spread": prev}
    if spread > 0 >= prev:
        return Signal("long", clamp01(abs(spread) * 100), ("golden_cross",), feat)
    if spread < 0 <= prev:
        return Signal("short", clamp01(abs(spread) * 100), ("death_cross",), feat)
    if abs(spread) < p["exit_band"] and abs(spread) < abs(prev):
        return Signal("exit", 0.5, ("spread_narrowing",), feat)
    if spread > 0:
        return Signal("long", clamp01(spread * 50), ("bullish_regime",), feat)
    if spread < 0:
        return Signal("short", clamp01(-spread * 50), ("bearish_regime",), feat)
    return Signal("hold", 0.0, ("flat_spread",), feat)


# --- volume / price ----------------------------------------------------------

def volume_price(view: PointInTimeView, p: dict) -> Signal:
    n = p["period"]
    if np.isnan(view.v[-(n + 1):]).any():
        return Signal("hold", 0.0, ("volume_unavailable",))
    avg = float(np.mean(view.v[-(n + 1):-1]))
    change = float(view.c[-1] / view.c[-2] - 1)
    if avg <= 0:
        return Signal("hold", 0.0, ("no_volume_history",), {"price_change": change})
    ratio = float(view.v[-1] / avg)
    feat = {"volume_ratio": ratio, "price_change": change}
    if ratio > p["volume_threshold"]:
        strength = clamp01(ratio / (2 * p["volume_threshold"]))
        if change > p["price_threshold"]:
            return Signal("long", strength, ("volume_spike_up",), feat)
        if change < -p["price_threshold"]:
            return Signal("short", strength, ("volume_spike_down",), feat)
    return Signal("hold", 0.0, (), feat)


# --- Bollinger reversion (absorbs legacy mean reversion) ---------------------

def bollinger_reversion(view: PointInTimeView, p: dict) -> Signal:
    window = view.c[-p["period"]:]
    mid, sd = float(np.mean(window)), float(np.std(window))
    price = float(view.c[-1])
    if sd == 0:
        return Signal("hold", 0.0, ("zero_band_width",), {"middle": mid})
    upper, lower = mid + p["k"] * sd, mid - p["k"] * sd
    width = upper - lower
    lower_dist, upper_dist = (price - lower) / width, (upper - price) / width
    feat = {"middle": mid, "upper": upper, "lower": lower, "lower_dist": lower_dist, "upper_dist": upper_dist}
    deviation_ok = True
    if p.get("deviation") is not None:
        dev = price / sma(view.c, p["mean_period"]) - 1
        feat["deviation"] = dev
        deviation_ok = abs(dev) > p["deviation"]
    near = p["near"]
    if lower_dist < near and deviation_ok:
        return Signal("long", clamp01((near - lower_dist) / near), ("near_lower_band",), feat)
    if upper_dist < near and deviation_ok:
        return Signal("short", clamp01((near - upper_dist) / near), ("near_upper_band",), feat)
    if 0.4 < lower_dist < 0.6:
        return Signal("exit", 0.5, ("back_to_middle",), feat)
    return Signal("hold", 0.0, (), feat)


# --- momentum ----------------------------------------------------------------

def momentum(view: PointInTimeView, p: dict) -> Signal:
    rsi = rsi_sma(view.c, p["rsi_period"])
    r = roc(view.c, p["roc_period"])
    feat = {"rsi": rsi, "roc": r}
    if rsi >= p["rsi_long"] and r >= p["min_roc"]:
        return Signal("long", clamp01((rsi - p["rsi_long"]) / 35 + abs(r) * 2.5), ("up_momentum",), feat)
    if rsi <= p["rsi_short"] and r <= -p["min_roc"]:
        return Signal("short", clamp01((p["rsi_short"] - rsi) / 35 + abs(r) * 2.5), ("down_momentum",), feat)
    if abs(r) < 0.005 and 47 <= rsi <= 53:
        return Signal("exit", 0.5, ("momentum_fading",), feat)
    return Signal("hold", 0.0, (), feat)


# --- trend breakout ----------------------------------------------------------

def trend_breakout(view: PointInTimeView, p: dict) -> Signal:
    n = p["period"]
    h, l, c, v = view.h, view.l, view.c, view.v
    resistance = float(np.max(h[-(n + 1):-1]))  # prior bars only: the current bar cannot define its own level
    support = float(np.min(l[-(n + 1):-1]))
    a = atr(h, l, c, p["atr_period"])
    diffs = np.diff(c[-n:])
    up, down = float(np.mean(diffs > 0)), float(np.mean(diffs < 0))
    if np.isnan(v[-(p["vol_lookback"] + 1):]).any():
        return Signal("hold", 0.0, ("volume_unavailable",))
    vol_avg = float(np.mean(v[-(p["vol_lookback"] + 1):-1]))
    vol_ok = vol_avg > 0 and float(v[-1]) > vol_avg * p["vol_mult"]
    price = float(c[-1])
    feat = {"support": support, "resistance": resistance, "atr": a, "up_fraction": up, "down_fraction": down}
    strong = p["min_strength"] * 1.2
    breakout_up = price > resistance + a * p["k"]
    breakdown = price < support - a * p["k"]
    if vol_ok and ((breakout_up and up > p["min_strength"]) or up > strong):
        return Signal("long", clamp01((up - 0.5) / 0.5), ("breakout" if breakout_up else "strong_uptrend",), feat)
    if vol_ok and ((breakdown and down > p["min_strength"]) or down > strong):
        return Signal("short", clamp01((down - 0.5) / 0.5), ("breakdown" if breakdown else "strong_downtrend",), feat)
    if abs(up - down) <= 0.1:
        return Signal("exit", 0.5, ("trend_faded",), feat)
    return Signal("hold", 0.0, (), feat)


# --- MACD ----------------------------------------------------------------------

def macd(view: PointInTimeView, p: dict) -> Signal:
    x = view.c[-p["warmup"]:]
    fast, slow = ema_series(x, p["fast"]), ema_series(x, p["slow"])
    line = fast[-len(slow):] - slow
    sig = ema_series(line, p["signal"])
    hist = line[-len(sig):] - sig
    price = float(view.c[-1])
    feat = {"macd": float(line[-1]), "signal": float(sig[-1]), "histogram_pct": float(hist[-1] / price)}
    strength = clamp01(abs(hist[-1] / price) * 100)
    if line[-1] > sig[-1] and line[-2] <= sig[-2]:
        return Signal("long", strength, ("bullish_crossover",), feat)
    if line[-1] < sig[-1] and line[-2] >= sig[-2]:
        return Signal("short", strength, ("bearish_crossover",), feat)
    if len(hist) >= 3 and hist[-1] * hist[-2] > 0 and abs(hist[-1]) < abs(hist[-2]) < abs(hist[-3]):
        return Signal("exit", 0.5, ("momentum_fading",), feat)
    return Signal("hold", 0.0, (), feat)


# --- ensemble ------------------------------------------------------------------

def ensemble(view: PointInTimeView, p: dict) -> Signal:
    votes = {"long": 0.0, "short": 0.0, "exit": 0.0}
    reasons = []
    for key in p["members"]:
        spec = get_spec(key)
        if len(view) < spec.min_bars:
            reasons.append(f"{key}:insufficient_bars")
            continue
        s = spec.fn(view, spec.params)
        if s.direction != "hold":
            votes[s.direction] += s.strength * p["weights"].get(key, 1.0)
            reasons.append(f"{key}:{s.direction}")
    total = sum(votes.values())
    feat = {f"vote_{k}": v for k, v in votes.items()}
    if total == 0:
        return Signal("hold", 0.0, tuple(reasons) or ("no_member_signals",), feat)
    direction, share = max(((k, v / total) for k, v in votes.items()), key=lambda kv: (kv[1], kv[0]))
    if share > p["threshold"]:
        return Signal(direction, clamp01(share), tuple(reasons), feat)
    return Signal("hold", 0.0, tuple(reasons) + ("no_consensus",), feat)


# --- registry ------------------------------------------------------------------

MA = register(StrategySpec("ma_crossover", "1", 201, {"short": 50, "long": 200, "exit_band": 0.005}, ma_crossover,
                           "SMA50/SMA200 crossover and regime"))
VP = register(StrategySpec("volume_price", "1", 21,
                           {"period": 20, "volume_threshold": 2.0, "price_threshold": 0.02}, volume_price,
                           "Volume spike with a large close-to-close move"))
BB = register(StrategySpec("bollinger_reversion", "1", 20,
                           {"period": 20, "k": 2.0, "near": 0.05, "deviation": None, "mean_period": 10},
                           bollinger_reversion, "Fade moves to the outer Bollinger bands"))
BBF = register(StrategySpec("bollinger_reversion_filtered", "1", 20,
                            {"period": 20, "k": 2.0, "near": 0.05, "deviation": 0.015, "mean_period": 10},
                            bollinger_reversion, "Bollinger reversion + 1.5% deviation filter (legacy mean reversion)"))
MOM = register(StrategySpec("momentum", "1", 15,
                            {"rsi_period": 14, "roc_period": 10, "rsi_long": 55, "rsi_short": 45, "min_roc": 0.02},
                            momentum, "SMA-RSI(14) and ROC(10) momentum"))
TREND = register(StrategySpec("trend_breakout", "1", 16,
                              {"period": 15, "atr_period": 10, "k": 1.2, "min_strength": 0.65, "vol_mult": 1.5,
                               "vol_lookback": 5}, trend_breakout, "ATR breakout of prior-bar levels"))
MACD = register(StrategySpec("macd", "1", 36, {"fast": 12, "slow": 26, "signal": 9, "warmup": 250}, macd,
                             "MACD(12,26,9) crossover over a fixed 250-bar window"))
ENSEMBLE = register(StrategySpec(
    "ensemble", "1", 201,
    {"members": [s.key for s in (MA, VP, BB, MOM, TREND, MACD)], "weights": {}, "threshold": 0.3},
    ensemble, "Strength-weighted vote of the ported strategies"))
