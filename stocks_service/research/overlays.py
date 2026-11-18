"""Overlay evaluation (plan §E "overlays need to show added value", phase 9).

An overlay is compared with the same strategy *without* it over the development window (never the
sealed holdout), same universe, costs, execution and portfolio policy. The overlay run is recorded
in ``experiments`` (so it counts toward the Deflated Sharpe trial count). Verdict: ``adds_value``
only if the paired daily-return difference has a 95% block-bootstrap CI lower bound above 0 and the
max drawdown is no worse; otherwise ``no_added_value`` — the overlay stays a research version and
does not change any output.
"""

from __future__ import annotations

import datetime as dt

from pymongo.database import Database

from .. import jobs
from . import baselines, stats
from .backtest import run_backtest
from .protocol import BASE_COST, HoldoutError, _excess_sharpe, _record, check_coverage, holdout_window, load_universe


def evaluate_overlay(db: Database, *, strategy: str, overlay, start: dt.date, end: dt.date, now: dt.datetime) -> dict:
    hw = holdout_window(db)
    if hw is None:
        raise HoldoutError("seal the holdout first so the evaluation window can exclude it")
    if end >= hw[0]:
        raise HoldoutError(f"overlay evaluation must end before the holdout starts ({hw[0]})")
    uni, tradable = load_universe(db)
    check_coverage(uni, tradable, start, end)
    base = run_backtest(uni, tradable, uni["^IRX"], strategy, start, end, BASE_COST)
    with_ = run_backtest(uni, tradable, uni["^IRX"], strategy, start, end, BASE_COST, overlay=overlay)
    _record(db, with_, kind="development", now=now, excess_sharpe=_excess_sharpe(with_, uni["^IRX"]))
    cash = baselines.cash_daily_returns(uni["^IRX"], base.dates)
    diff = stats.daily_returns(with_.equity) - stats.daily_returns(base.equity)
    m, lo, hi = stats.block_bootstrap_mean_ci(diff)
    sb, sw = stats.summarize(base.equity, cash), stats.summarize(with_.equity, cash)
    adds = lo > 0 and sw["max_drawdown"] <= sb["max_drawdown"]
    doc = {"created_at": now, "strategy": strategy, "overlay": overlay.key, "window": [start.isoformat(), end.isoformat()],
           "without": {"metrics": sb, "trades": len(base.trades)}, "with": {"metrics": sw, "trades": len(with_.trades)},
           "paired_excess_annual": {"mean": m, "ci95": [lo, hi]},
           "verdict": "adds_value" if adds else "no_added_value"}
    db.overlay_evaluations.insert_one(dict(doc))
    return doc


def start_overlay_job(db: Database, *, strategy: str, weight: float, start: dt.date, end: dt.date) -> str:
    from ..cross_asset import GroupConsensus

    def work(log):
        groups = {s["_id"]: s.get("groups", []) for s in db.symbols.find({}, {"groups": 1})}
        res = evaluate_overlay(db, strategy=strategy, overlay=GroupConsensus(groups, weight), start=start, end=end,
                               now=dt.datetime.now(dt.timezone.utc))
        return {"verdict": res["verdict"], "paired_excess_annual": res["paired_excess_annual"]}

    return jobs.start_job(db, "overlay", work, params={"strategy": strategy, "weight": weight})
