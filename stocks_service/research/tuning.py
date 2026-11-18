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


def _metrics(returns: np.ndarray, cash: np.ndarray) -> dict:
    """Metrics of a daily return stream; Sharpe is of the excess over T-bills (as in the research report)."""
    equity = np.cumprod(np.r_[1.0, 1 + returns])
    ex = returns - cash
    sd = ex.std(ddof=1) if len(ex) > 1 else 0.0
    years = len(returns) / stats.TRADING_DAYS
    total = equity[-1] - 1
    return {"sharpe": float(ex.mean() / sd * np.sqrt(stats.TRADING_DAYS)) if sd > 0 else float("-inf"),
            "cagr": float((1 + total) ** (1 / years) - 1) if years > 0 and total > -1 else float("-inf"),
            "max_drawdown": stats.max_drawdown(list(equity))[0]}


def _avg_ranks(vals: np.ndarray, higher_better: bool) -> np.ndarray:
    """0 = best; tied values share the average of their ranks."""
    x = -vals if higher_better else vals
    order = np.argsort(x, kind="mergesort")
    ranks = np.empty(len(x))
    i = 0
    while i < len(x):
        j = i
        while j + 1 < len(x) and x[order[j + 1]] == x[order[i]]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0
        i = j + 1
    return ranks


def rank_scores(metrics: dict[str, dict]) -> dict[str, float]:
    """Rank-normalize each metric across configs (best = 1) and combine with WEIGHTS."""
    keys = sorted(metrics)
    out = {k: 0.0 for k in keys}
    for m, w in WEIGHTS.items():
        ranks = _avg_ranks(np.array([metrics[k][m] for k in keys]), higher_better=(m != "max_drawdown"))
        norm = 1 - ranks / max(1, len(keys) - 1)
        for k, s in zip(keys, norm):
            out[k] += w * float(s)
    return out


MIN_FIRST_FOLD = 60


def folds(dates: list[dt.date]) -> list[tuple[int, int]]:
    """Test windows ``[ts, te)`` as session indices; training for a fold uses sessions ``< ts`` only.

    Expanding training; contiguous test windows through the last session (a short final fold is
    kept once an earlier full fold exists)."""
    y = dates[0].year + FIRST_TRAIN_YEARS
    out = []
    while True:
        ts = next((i for i, d in enumerate(dates) if d.year >= y), None)
        if ts is None or ts == 0:
            break
        te = next((i for i, d in enumerate(dates) if d.year >= y + FOLD_YEARS), len(dates))
        if not out and te - ts < MIN_FIRST_FOLD:
            break
        out.append((ts, te))
        if te >= len(dates):
            break
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
    curves: dict[str, np.ndarray] = {}   # daily returns per config, aligned with dates[1:]
    default_key = None
    dp = dict(PolicyParams().levels)
    for stop, target in itertools.product(GRID["stop_atr"], GRID["target_atr"]):
        key = f"stop={stop},target={target}"
        r = run_backtest(uni, tradable, uni["^IRX"], strategy, start, end, BASE_COST, params=_params(stop, target))
        _record(db, r, kind="development", now=now, excess_sharpe=_excess_sharpe(r, uni["^IRX"]),
                params={"stop_atr": stop, "target_atr": target, "search": "tuning@1"})
        eq = np.asarray(r.equity, dtype=float)
        curves[key] = eq[1:] / eq[:-1] - 1
        dates = r.dates
        if stop == dp["stop_atr"] and target == dp["target_atr"]:
            default_key = key
        if log:
            log(step="tuning", config=key)
    if default_key is None:
        raise ValueError("the default parameters must be part of the grid")
    from . import baselines
    cash = baselines.cash_daily_returns(uni["^IRX"], dates)   # cash[i]: return from dates[i] to dates[i+1]
    chosen_returns, default_returns, oos_cash, picks = [], [], [], []
    for ts, te in folds(dates):
        # Returns *into* sessions < ts are training data (indices 0..ts-2); returns into [ts, te) are the test.
        train_metrics = {k: _metrics(c[: ts - 1], cash[: ts - 1]) for k, c in curves.items()}
        scores = rank_scores(train_metrics)
        best = max(sorted(scores), key=lambda k: (scores[k], k))   # key only breaks exact score ties
        picks.append({"test_from": dates[ts].isoformat(), "test_to": dates[te - 1].isoformat(), "chosen": best,
                      "score": scores[best]})
        chosen_returns += list(curves[best][ts - 1: te - 1])
        default_returns += list(curves[default_key][ts - 1: te - 1])
        oos_cash += list(cash[ts - 1: te - 1])
    diff = np.array(chosen_returns) - np.array(default_returns)
    m, lo, hi = stats.block_bootstrap_mean_ci(diff)
    doc = {"created_at": now, "strategy": strategy, "search": "tuning@1", "grid": {k: list(v) for k, v in GRID.items()},
           "weights": WEIGHTS, "window": [start.isoformat(), end.isoformat()], "folds": picks,
           "default": default_key, "oos": {"tuned": _metrics(np.array(chosen_returns), np.array(oos_cash)),
                                           "default": _metrics(np.array(default_returns), np.array(oos_cash))},
           "paired_excess_annual": {"mean": m, "ci95": [lo, hi]}, "oos_sessions": len(chosen_returns),
           "status": "adopt" if lo > 0 else "research"}
    db.param_sets.insert_one(dict(doc))
    return doc


def start_tuning_job(db: Database, *, strategy: str, start: dt.date, end: dt.date) -> str:
    return jobs.start_job(db, "tuning", lambda log: _summary(tune(db, strategy=strategy, start=start, end=end,
                                                                  now=dt.datetime.now(dt.timezone.utc), log=log)),
                          params={"strategy": strategy})


def _summary(doc: dict) -> dict:
    return {"status": doc["status"], "paired_excess_annual": doc["paired_excess_annual"], "folds": doc["folds"]}
