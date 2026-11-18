"""Walk-forward grid search of ATR level multiples (plan §9 "tuning"; idea from abu).

For one strategy, every configuration in the grid is backtested over the development window
(never the holdout) and **recorded as a trial** in ``experiments`` (so the Deflated Sharpe hurdle
reflects the search). Folds: expanding training windows, then ``FOLD_YEARS``-year test windows.
In each fold the configuration with the best rank-normalized weighted score on the *training*
part only — Sharpe (0.5), CAGR (0.3), max drawdown (0.2, lower is better) — is used for the test
part. The stitched out-of-sample daily returns are compared with the default parameters over the
same test sessions (paired bootstrap CI). The resulting ``param_sets`` entry is ``adopt`` only if the
CI lower bound is above 0; otherwise it stays ``research`` and nothing uses it.

Each configuration is one continuous backtest, so positions carry across fold boundaries; the
selection itself only ever sees data before its test window.
"""

from __future__ import annotations

import datetime as dt
import itertools

import numpy as np
from pymongo.database import Database

from .. import jobs
from . import stats
from .backtest import PolicyParams, run_backtest
from .protocol import BASE_COST, HoldoutError, _excess_sharpe, _record, check_coverage, holdout_window, load_universe

GRID = {"stop_atr": (1.5, 2.0, 3.0), "target_atr": (3.0, 4.0, 6.0)}
WEIGHTS = {"sharpe": 0.5, "cagr": 0.3, "max_drawdown": 0.2}
FOLD_YEARS = 3
FIRST_TRAIN_YEARS = 6


def _params(stop_atr: float, target_atr: float) -> PolicyParams:
    base = dict(PolicyParams().levels)
    base.update(stop_atr=stop_atr, target_atr=target_atr)
    return PolicyParams(levels=tuple(base.items()))


def _metrics(equity: np.ndarray) -> dict:
    r = equity[1:] / equity[:-1] - 1
    sd = r.std(ddof=1) if len(r) > 1 else 0.0
    years = len(r) / stats.TRADING_DAYS
    total = equity[-1] / equity[0] - 1
    return {"sharpe": float(r.mean() / sd * np.sqrt(stats.TRADING_DAYS)) if sd > 0 else float("-inf"),
            "cagr": float((1 + total) ** (1 / years) - 1) if years > 0 and total > -1 else float("-inf"),
            "max_drawdown": stats.max_drawdown(list(equity))[0]}


def rank_scores(metrics: dict[str, dict]) -> dict[str, float]:
    """Rank-normalize each metric across configs (best = 1) and combine with WEIGHTS."""
    keys = sorted(metrics)
    out = {k: 0.0 for k in keys}
    for m, w in WEIGHTS.items():
        vals = np.array([metrics[k][m] for k in keys])
        order = np.argsort(-vals if m != "max_drawdown" else vals, kind="mergesort")
        ranks = np.empty(len(keys))
        ranks[order] = np.arange(len(keys))
        norm = 1 - ranks / max(1, len(keys) - 1)
        for k, s in zip(keys, norm):
            out[k] += w * float(s)
    return out


def folds(dates: list[dt.date]) -> list[tuple[int, int, int]]:
    """(train_end_idx, test_start_idx, test_end_idx) with expanding training windows."""
    first = dates[0].year + FIRST_TRAIN_YEARS
    out = []
    y = first
    while True:
        ts = next((i for i, d in enumerate(dates) if d.year >= y), None)
        if ts is None:
            break
        te = next((i for i, d in enumerate(dates) if d.year >= y + FOLD_YEARS), len(dates))
        if te - ts < 60:
            break
        out.append((ts, ts, te))
        y += FOLD_YEARS
    return out


def tune(db: Database, *, strategy: str, start: dt.date, end: dt.date, now: dt.datetime, log=None) -> dict:
    hw = holdout_window(db)
    if hw is None or end >= hw[0]:
        raise HoldoutError("tuning must end before the sealed holdout starts")
    from .. import sessions
    if not folds(sessions.sessions_between(start, end)):   # fail before running (and recording) any trial
        raise ValueError(f"window {start}..{end} is too short for a {FIRST_TRAIN_YEARS}-year first training "
                         f"period plus a {FOLD_YEARS}-year test fold")
    uni, tradable = load_universe(db)
    check_coverage(uni, tradable, start, end)
    curves: dict[str, np.ndarray] = {}
    default_key = None
    dp = dict(PolicyParams().levels)
    for stop, target in itertools.product(GRID["stop_atr"], GRID["target_atr"]):
        key = f"stop={stop},target={target}"
        r = run_backtest(uni, tradable, uni["^IRX"], strategy, start, end, BASE_COST, params=_params(stop, target))
        _record(db, r, kind="development", now=now, excess_sharpe=_excess_sharpe(r, uni["^IRX"]),
                params={"stop_atr": stop, "target_atr": target, "search": "tuning@1"})
        curves[key] = np.asarray(r.equity, dtype=float)
        dates = r.dates
        if stop == dp["stop_atr"] and target == dp["target_atr"]:
            default_key = key
        if log:
            log(step="tuning", config=key)
    if default_key is None:
        raise ValueError("the default parameters must be part of the grid")
    chosen_returns, default_returns, picks = [], [], []
    for train_end, ts, te in folds(dates):
        train_metrics = {k: _metrics(c[: train_end + 1]) for k, c in curves.items()}
        scores = rank_scores(train_metrics)
        best = max(sorted(scores), key=lambda k: scores[k])
        picks.append({"test_from": dates[ts].isoformat(), "test_to": dates[te - 1].isoformat(), "chosen": best,
                      "score": scores[best]})
        c, d = curves[best], curves[default_key]
        chosen_returns += list(c[ts + 1: te] / c[ts: te - 1] - 1)
        default_returns += list(d[ts + 1: te] / d[ts: te - 1] - 1)
    diff = np.array(chosen_returns) - np.array(default_returns)
    m, lo, hi = stats.block_bootstrap_mean_ci(diff)
    oos_c = np.cumprod(np.r_[1.0, 1 + np.array(chosen_returns)])
    oos_d = np.cumprod(np.r_[1.0, 1 + np.array(default_returns)])
    doc = {"created_at": now, "strategy": strategy, "search": "tuning@1", "grid": {k: list(v) for k, v in GRID.items()},
           "weights": WEIGHTS, "window": [start.isoformat(), end.isoformat()], "folds": picks,
           "default": default_key, "oos": {"tuned": _metrics(oos_c), "default": _metrics(oos_d)},
           "paired_excess_annual": {"mean": m, "ci95": [lo, hi]},
           "status": "adopt" if lo > 0 else "research"}
    db.param_sets.insert_one(dict(doc))
    return doc


def start_tuning_job(db: Database, *, strategy: str, start: dt.date, end: dt.date) -> str:
    return jobs.start_job(db, "tuning", lambda log: _summary(tune(db, strategy=strategy, start=start, end=end,
                                                                  now=dt.datetime.now(dt.timezone.utc), log=log)),
                          params={"strategy": strategy})


def _summary(doc: dict) -> dict:
    return {"status": doc["status"], "paired_excess_annual": doc["paired_excess_annual"], "folds": doc["folds"]}
