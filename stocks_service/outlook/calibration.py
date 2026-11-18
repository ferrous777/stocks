"""Walk-forward calibration of outcome distributions (plan §7).

Buckets:
* ``(strategy, side)`` for signal labels, pooled across symbols;
* ``(base_rate, symbol, side)`` for each symbol's unconditional distribution.

For each bucket the published distribution uses every development label (resolved before the
holdout). Its forecasting skill is measured out of sample: for each yearly cutoff T, the win
probability P(excess > 0) learned from labels **resolved before T** predicts labels **decided in
[T, T + 1 year)**; the reference forecast is the pooled base rate for the same side, also learned
before T. Brier skill = 1 - Brier(bucket) / Brier(reference).

Publication rule: a signal bucket's expected values are published (``calibrated``) only with
n >= MIN_N, at least MIN_OOS out-of-sample predictions and Brier skill >= MIN_SKILL; otherwise its status
is ``insufficient`` or ``unreliable`` and the expected values are None. A base-rate bucket with
n >= MIN_N is published as ``base_rate`` — a historical frequency for this symbol, not a forecast.

Labels overlap (decisions every 5 sessions, horizons up to 127 sessions), so ``n`` overstates
the number of independent observations; the report says so.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict

import numpy as np

from .labels import BASE, Label

CALIBRATION_VERSION = "calibration@1"
MIN_N = 100
MIN_OOS = 50
MIN_SKILL = 0.01  # at least a 1% Brier improvement over the base rate; smaller gains are indistinguishable from noise
RESULTS = ("target", "stop", "gap_stop", "timeout", "not_filled")


def _year_cutoffs(labels: list[Label], holdout_start: dt.date) -> list[dt.date]:
    if not labels:
        return []
    first = min(lab.decided for lab in labels).year + 3  # need some history before the first cutoff
    return [dt.date(y, 1, 1) for y in range(first, holdout_start.year + 1) if dt.date(y, 1, 1) < holdout_start]


def _win_rate(xs: list[Label]) -> float | None:
    return float(np.mean([lab.excess > 0 for lab in xs])) if xs else None


def _summary(xs: list[Label]) -> dict:
    ex = np.array([lab.excess for lab in xs])
    net = np.array([lab.net_return for lab in xs])
    held = [lab.sessions_held for lab in xs if lab.sessions_held is not None]
    return {
        "n": len(xs),
        "n_symbols": len({lab.symbol for lab in xs}),
        "first_decided": min(lab.decided for lab in xs).isoformat(),
        "last_decided": max(lab.decided for lab in xs).isoformat(),
        "p": {r: float(np.mean([lab.result == r for lab in xs])) for r in RESULTS},
        "fill_rate": float(np.mean([lab.result != "not_filled" for lab in xs])),
        "p_win": float(np.mean(ex > 0)),
        "mean_excess": float(ex.mean()),
        "mean_net_return": float(net.mean()),
        "p10_excess": float(np.percentile(ex, 10)),
        "p50_excess": float(np.percentile(ex, 50)),
        "p90_excess": float(np.percentile(ex, 90)),
        "mean_sessions_held": float(np.mean(held)) if held else None,
    }


def walk_forward_split(bucket: list[Label], T: dt.date, holdout_start: dt.date) -> tuple[list[Label], list[Label]]:
    """Train: outcomes known before T. Test: decisions made in [T, next Jan 1 or the holdout)."""
    T1 = min(dt.date(T.year + 1, 1, 1), holdout_start)
    return [lab for lab in bucket if lab.resolved < T], [lab for lab in bucket if T <= lab.decided < T1]


def _oos_skill(bucket: list[Label], reference: list[Label], cutoffs: list[dt.date], holdout_start: dt.date) -> dict:
    ys, pm, pr = [], [], []
    for T in cutoffs:
        train, test = walk_forward_split(bucket, T, holdout_start)
        ref = [lab for lab in reference if lab.resolved < T]
        if len(train) < MIN_N or not ref or not test:
            continue
        p_model, p_ref = _win_rate(train), _win_rate(ref)
        for lab in test:
            ys.append(float(lab.excess > 0))
            pm.append(p_model)
            pr.append(p_ref)
    if not ys:
        return {"n_oos": 0, "brier": None, "brier_ref": None, "brier_skill": None}
    y, a, b = np.array(ys), np.array(pm), np.array(pr)
    bm, br = float(np.mean((a - y) ** 2)), float(np.mean((b - y) ** 2))
    return {"n_oos": len(ys), "brier": bm, "brier_ref": br, "brier_skill": (1 - bm / br) if br > 0 else None}


def calibrate(labels: list[Label], holdout_start: dt.date) -> list[dict]:
    dev = [lab for lab in labels if lab.resolved < holdout_start]
    by_key: dict[tuple, list[Label]] = defaultdict(list)
    base_by_side: dict[str, list[Label]] = defaultdict(list)
    for lab in dev:
        if lab.strategy == BASE:
            by_key[(BASE, lab.symbol, lab.side)].append(lab)
            base_by_side[lab.side].append(lab)
        else:
            by_key[(lab.strategy, None, lab.side)].append(lab)
    cutoffs = _year_cutoffs(dev, holdout_start)
    out = []
    for (strategy, symbol, side), xs in sorted(by_key.items(), key=lambda kv: (kv[0][0], kv[0][1] or "", kv[0][2])):
        skill = _oos_skill(xs, base_by_side[side], cutoffs, holdout_start)
        summ = _summary(xs)
        if strategy == BASE:
            status = "base_rate" if summ["n"] >= MIN_N else "insufficient"
        elif summ["n"] < MIN_N:
            status = "insufficient"
        elif skill["n_oos"] < MIN_OOS or skill["brier_skill"] is None or skill["brier_skill"] < MIN_SKILL:
            status = "unreliable"
        else:
            status = "calibrated"
        published = status in ("calibrated", "base_rate")
        bucket = {"strategy": strategy, "symbol": symbol, "side": side, "status": status, **skill, **summ}
        if not published:
            for k in ("mean_excess", "mean_net_return", "p10_excess", "p50_excess", "p90_excess", "p_win"):
                bucket[k] = None  # not published: values without demonstrated skill are withheld
        out.append(bucket)
    return out
