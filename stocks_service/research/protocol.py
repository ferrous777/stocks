"""Phase-3 validation protocol: development-period evaluation, stress tests, overfitting
diagnostics, the eligibility gate, and a single-use sealed holdout.

Rules enforced here (plan §B):
* Every backtest run is recorded in ``experiments`` (the trial count feeds the Deflated Sharpe).
* The holdout window is fixed when the protocol is frozen; development runs never read it
  (``run_development`` refuses any window overlapping it).
* The holdout can be revealed exactly once, only for a frozen protocol whose hash matches.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import subprocess

import numpy as np
from pymongo.database import Database

from .. import sessions
from ..sim import CostProfile, ExecutionPolicy
from ..strategies import all_specs
from . import baselines, stats
from .backtest import POLICY_ID, BacktestResult, PolicyParams, run_backtest
from .series import SymbolSeries

PROTOCOL_VERSION = "phase3_protocol@1"
GATE = {
    "excess_vs_cash_ci_lower_gt": 0.0,   # annualized excess over T-bills, bootstrap 95% CI lower bound
    "deflated_sharpe_ge": 0.95,
    "max_drawdown_le": 0.35,
    "excess_vs_cash_at_2x_costs_gt": 0.0,
}
# Explicit cost assumptions (labelled in the report). Fidelity charges $0 commission on online US
# stock/ETF trades; spread, slippage and borrow are assumptions, not measured data.
BASE_COST = CostProfile("us_equity_baseline", 1, commission_per_share=0.0, min_commission=0.0,
                        half_spread_bps=2.0, slippage_bps=3.0, borrow_rate_annual=0.005)


class HoldoutError(RuntimeError):
    pass


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "unknown"


def load_universe(db: Database) -> tuple[dict[str, SymbolSeries], list[str]]:
    syms = list(db.symbols.find({}, {"asset_class": 1, "tradable": 1}))
    uni = {s["_id"]: SymbolSeries.from_db(db, s["_id"]) for s in syms}
    # Mutual funds trade once a day at NAV (no intraday range), so limit fills cannot be simulated.
    tradable = sorted(s["_id"] for s in syms if s.get("tradable", True) and s.get("asset_class") in ("equity", "etf")
                      and uni[s["_id"]].sessions)
    for need in ("^IRX", "SPY", "QQQ", "QQQM"):
        if need not in uni or not uni[need].sessions:
            raise ValueError(f"{need} has no data; load it before running the protocol")
    return uni, tradable


# --- holdout --------------------------------------------------------------------------

def seal_holdout(db: Database, *, start: dt.date, end: dt.date, now: dt.datetime) -> dict:
    """Fix the holdout window once. Refuses to change an existing one."""
    existing = db.holdouts.find_one({"_id": "primary"})
    if existing:
        return existing
    doc = {"_id": "primary", "start": dt.datetime.combine(start, dt.time(), dt.timezone.utc),
           "end": dt.datetime.combine(end, dt.time(), dt.timezone.utc), "status": "sealed", "sealed_at": now,
           "protocol": None, "evaluation": None}
    db.holdouts.insert_one(doc)
    return doc


def holdout_window(db: Database) -> tuple[dt.date, dt.date] | None:
    h = db.holdouts.find_one({"_id": "primary"})
    return (h["start"].date(), h["end"].date()) if h else None


def freeze_protocol(db: Database, *, candidates: list[str], dev_window: tuple[dt.date, dt.date], now: dt.datetime) -> str:
    """Pre-register the selection rule before any holdout evaluation; returns its content hash."""
    h = db.holdouts.find_one({"_id": "primary"})
    if h is None:
        raise HoldoutError("seal the holdout first")
    if h["status"] != "sealed":
        raise HoldoutError(f"holdout is {h['status']}; a new prospective window is required")
    protocol = {"version": PROTOCOL_VERSION, "candidates": sorted(candidates), "gate": GATE,
                "cost_profile": dataclasses.asdict(BASE_COST), "execution_policy": dataclasses.asdict(ExecutionPolicy()),
                "policy": POLICY_ID, "policy_params": dataclasses.asdict(PolicyParams()),
                "dev_window": [dev_window[0].isoformat(), dev_window[1].isoformat()], "git_sha": git_sha()}
    digest = hashlib.sha256(json.dumps(protocol, sort_keys=True, default=str).encode()).hexdigest()
    db.holdouts.update_one({"_id": "primary", "status": "sealed"},
                           {"$set": {"protocol": protocol, "protocol_hash": digest, "frozen_at": now}})
    return digest


def reveal_holdout(db: Database, *, protocol_hash: str, now: dt.datetime) -> dict:
    """Evaluate the frozen protocol's eligible strategies on the holdout. Single use."""
    h = db.holdouts.find_one({"_id": "primary"})
    if h is None or h.get("protocol_hash") is None:
        raise HoldoutError("no frozen protocol")
    if h["status"] != "sealed":
        raise HoldoutError("holdout already consumed; any change needs a new prospective window")
    if protocol_hash != h["protocol_hash"]:
        raise HoldoutError("protocol hash mismatch; the protocol changed after freezing")
    claimed = db.holdouts.find_one_and_update({"_id": "primary", "status": "sealed"},
                                              {"$set": {"status": "consumed", "consumed_at": now}})
    if claimed is None:
        raise HoldoutError("holdout already consumed")
    uni, tradable = load_universe(db)
    start, end = h["start"].date(), h["end"].date()
    results = {}
    for key in h["protocol"]["candidates"]:
        r = run_backtest(uni, tradable, uni["^IRX"], key, start, end, BASE_COST)
        _record(db, r, kind="holdout", now=now)
        results[key] = _evaluate(r, uni, tradable, trial_sharpes=None)
    db.holdouts.update_one({"_id": "primary"}, {"$set": {"evaluation": results}})
    return results


# --- development evaluation ------------------------------------------------------------

def _record(db: Database, r: BacktestResult, *, kind: str, now: dt.datetime) -> None:
    db.experiments.insert_one({
        "kind": kind, "strategy": r.strategy, "policy": r.policy, "cost_profile": r.cost_profile,
        "execution_policy": r.execution_policy, "start": dt.datetime.combine(r.start, dt.time(), dt.timezone.utc),
        "end": dt.datetime.combine(r.end, dt.time(), dt.timezone.utc), "git_sha": git_sha(),
        "final_equity": r.equity[-1], "trades": len(r.trades), "created_at": now,
    })


def _evaluate(r: BacktestResult, uni, tradable, trial_sharpes: list[float] | None) -> dict:
    irx = uni["^IRX"]
    cash_r = baselines.cash_daily_returns(irx, r.dates)
    s = stats.summarize(r.equity, cash_r)
    rets = stats.daily_returns(r.equity)
    base_curves = {
        "cash": baselines.cash_curve(irx, r.dates, r.initial),
        "SPY": baselines.buy_and_hold(uni["SPY"], r.dates, irx, r.initial),
        "QQQM (QQQ before 2020-10-13)": baselines.spliced_buy_and_hold(
            uni["QQQM"], uni["QQQ"], uni["QQQM"].sessions[0], r.dates, irx, r.initial),
    }
    ew, members = baselines.equal_weight(uni, tradable, r.dates, irx, r.initial)
    base_curves["equal_weight_universe"] = ew
    comparisons = {}
    for name, curve in base_curves.items():
        diff = rets - stats.daily_returns(curve)
        mean, lo, hi = stats.block_bootstrap_mean_ci(diff)
        comparisons[name] = {"baseline": stats.summarize(curve, cash_r), "excess_annual": mean,
                             "excess_ci95": [lo, hi]}
    closed = r.trades
    out = {
        "metrics": s,
        "trades": len(closed),
        "win_rate": float(np.mean([t.net_return > 0 for t in closed])) if closed else None,
        "avg_net_return_per_trade": float(np.mean([t.net_return for t in closed])) if closed else None,
        "ambiguous_exits": int(sum(t.ambiguous for t in closed)),
        "not_filled": r.not_filled,
        "open_at_end": r.open_at_end,
        "avg_exposure": float(np.mean(r.exposure)),
        "turnover_annual": r.traded_notional / float(np.mean(r.equity)) / max(s["years"], 1e-9),
        "comparisons": comparisons,
        "equal_weight_members": members,
    }
    if trial_sharpes is not None:
        out["deflated_sharpe"] = stats.deflated_sharpe(rets - cash_r[: len(rets)], trial_sharpes)
    return out


def run_development(db: Database, *, start: dt.date, end: dt.date, now: dt.datetime,
                    strategies: list[str] | None = None) -> dict:
    hw = holdout_window(db)
    if hw is None:
        raise HoldoutError("seal the holdout before development runs so the window can be excluded")
    if end >= hw[0]:
        raise HoldoutError(f"development window must end before the holdout starts ({hw[0]})")
    uni, tradable = load_universe(db)
    keys = strategies or [s.key for s in all_specs()]
    runs: dict[str, BacktestResult] = {}
    stress: dict[str, dict[str, BacktestResult]] = {}
    for key in keys:
        runs[key] = run_backtest(uni, tradable, uni["^IRX"], key, start, end, BASE_COST)
        _record(db, runs[key], kind="development", now=now)
        stress[key] = {}
        for factor in (2, 3):
            sr = run_backtest(uni, tradable, uni["^IRX"], key, start, end, BASE_COST.scaled(factor, f"_x{factor}"))
            _record(db, sr, kind=f"stress_costs_x{factor}", now=now)
            stress[key][f"costs_x{factor}"] = sr
    # Trial Sharpe ratios for the DSR: every development configuration ever recorded for this protocol.
    trial_count = db.experiments.count_documents({"kind": "development"})
    any_run = next(iter(runs.values()))
    cash_r = baselines.cash_daily_returns(uni["^IRX"], any_run.dates)
    excess = {k: stats.daily_returns(r.equity) - cash_r for k, r in runs.items()}
    trial_sharpes = [float(x.mean() / x.std(ddof=1)) for x in excess.values() if x.std(ddof=1) > 0]
    results = {}
    for key, r in runs.items():
        ev = _evaluate(r, uni, tradable, trial_sharpes)
        ev["stress"] = {}
        for name, sr in stress[key].items():
            sc = baselines.cash_daily_returns(uni["^IRX"], sr.dates)
            m, lo, hi = stats.block_bootstrap_mean_ci(stats.daily_returns(sr.equity) - sc)
            ev["stress"][name] = {"metrics": stats.summarize(sr.equity, sc), "excess_vs_cash": m,
                                  "excess_vs_cash_ci95": [lo, hi]}
        cash_cmp = ev["comparisons"]["cash"]
        checks = {
            "excess_vs_cash_ci_lower_gt": cash_cmp["excess_ci95"][0] > GATE["excess_vs_cash_ci_lower_gt"],
            "deflated_sharpe_ge": (ev.get("deflated_sharpe") or 0) >= GATE["deflated_sharpe_ge"],
            "max_drawdown_le": ev["metrics"]["max_drawdown"] <= GATE["max_drawdown_le"],
            "excess_vs_cash_at_2x_costs_gt": ev["stress"]["costs_x2"]["excess_vs_cash"] > GATE["excess_vs_cash_at_2x_costs_gt"],
        }
        ev["gate"] = {"checks": checks, "eligible": all(checks.values())}
        results[key] = ev
    pbo = stats.probability_of_backtest_overfitting(np.column_stack(list(excess.values()))) if len(excess) > 1 else None
    report = {
        "created_at": now, "protocol_version": PROTOCOL_VERSION, "git_sha": git_sha(),
        "dev_window": [start.isoformat(), end.isoformat()],
        "holdout_window": [hw[0].isoformat(), hw[1].isoformat()],
        "cost_profile": dataclasses.asdict(BASE_COST), "execution_policy": dataclasses.asdict(ExecutionPolicy()),
        "policy": POLICY_ID, "policy_params": dataclasses.asdict(PolicyParams()), "gate": GATE,
        "trial_count": trial_count, "pbo": pbo, "tradable": tradable, "results": results,
        "eligible": [k for k, v in results.items() if v["gate"]["eligible"]],
        "caveats": [
            "Universe is today's hand-picked symbols (survivorship/selection bias); compare with the equal-weight baseline.",
            "Spread, slippage and borrow costs are assumptions; Yahoo provides no historical quotes.",
            "Fills use daily bars only (exec_daily_v1); intraday order of highs and lows is unknown (stop assumed first).",
            "Mutual funds are excluded from trading (no intraday range).",
        ],
    }
    db.research_reports.insert_one(dict(report))
    return report


def _finite(x):
    """Undefined statistics (e.g. the Sharpe ratio of riskless cash) become None, not NaN."""
    if isinstance(x, float) and not np.isfinite(x):
        return None
    if isinstance(x, dict):
        return {k: _finite(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_finite(v) for v in x]
    return x


def latest_report(db: Database) -> dict | None:
    doc = db.research_reports.find_one(sort=[("created_at", -1)])
    if doc:
        doc.pop("_id", None)
        doc = _finite(doc)
    return doc


def start_development_job(db: Database, *, dev_start: dt.date, dev_end: dt.date, holdout_start: dt.date) -> str:
    """Run seal + development evaluation in a background thread, tracked in `jobs`."""
    import threading
    import traceback
    if db.jobs.find_one({"kind": "research", "status": "running"}):
        raise RuntimeError("a research run is already in progress")
    now = dt.datetime.now(dt.timezone.utc)
    job_id = db.jobs.insert_one({"kind": "research", "status": "running", "started_at": now}).inserted_id

    def work():
        try:
            last = db.bars.find_one({"symbol": "SPY", "interval": "1d"}, sort=[("session", -1)])
            if last is None:
                raise ValueError("SPY has no data; load the universe first")
            seal_holdout(db, start=holdout_start, end=last["session"].date(), now=now)
            rep = run_development(db, start=dev_start, end=dev_end, now=now)
            db.jobs.update_one({"_id": job_id}, {"$set": {"status": "completed", "finished_at": dt.datetime.now(dt.timezone.utc),
                                                         "eligible": rep["eligible"]}})
        except Exception as e:
            db.jobs.update_one({"_id": job_id}, {"$set": {"status": "failed", "error": f"{type(e).__name__}: {e}",
                                                         "traceback": traceback.format_exc()[-4000:]}})

    threading.Thread(target=work, daemon=True).start()
    return str(job_id)
