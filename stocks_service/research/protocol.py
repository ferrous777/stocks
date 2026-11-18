"""Phase-3 validation protocol: development-period evaluation, stress tests, overfitting
diagnostics, the eligibility gate, and a single-use sealed holdout.

Rules enforced here (plan §B):
* Every backtest run is recorded in ``experiments`` (the trial count feeds the Deflated Sharpe).
* The holdout window is fixed when the protocol is frozen; development runs never read it
  (``run_development`` refuses any window overlapping it).
* The holdout can be revealed exactly once, only for a frozen protocol whose hash matches.
  The frozen protocol snapshots the effective configuration (costs, policies, parameters,
  universe, corporate-action versions and a fingerprint of the evaluation code); reveal
  re-derives it and refuses on any difference, and preflights data coverage, *before* the
  irreversible claim. The run then executes the recorded parameters.
* The Deflated Sharpe uses every development trial recorded in ``experiments`` for this
  protocol version, not only the strategies in the current invocation.
* Background runs hold an expiring, heartbeated lease in ``job_locks``; a run whose worker died
  is marked ``abandoned`` by the next run instead of blocking the endpoint forever.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import pathlib
import subprocess

import numpy as np
from pymongo import ReturnDocument
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from .. import sessions
from ..sim import CostProfile, ExecutionPolicy
from ..strategies import all_specs, get_spec
from . import baselines, stats
from .backtest import POLICY_ID, BacktestResult, DataCoverageError, PolicyParams, _irx_rate, run_backtest
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


class JobConflict(RuntimeError):
    pass


_PKG = pathlib.Path(__file__).resolve().parent.parent
_CODE_PATHS = ("strategies", "sim", "research", "levels.py", "sessions.py", "price_basis.py")


def code_fingerprint() -> str:
    """Content hash of the code that determines evaluation results (works without a .git directory)."""
    h = hashlib.sha256()
    for rel in _CODE_PATHS:
        p = _PKG / rel
        files = sorted(p.rglob("*.py")) if p.is_dir() else [p]
        for f in files:
            h.update(str(f.relative_to(_PKG)).encode())
            h.update(f.read_bytes())
    return h.hexdigest()


def _canonical(x):
    return json.loads(json.dumps(x, sort_keys=True, default=str))


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


def check_coverage(uni: dict[str, SymbolSeries], tradable: list[str], start: dt.date, end: dt.date) -> list[str]:
    """Fail before any evaluation if the window needs observations that are not stored.

    Returns interior ^IRX gaps longer than a week (real observations on both sides), during which
    the last known rate is carried; these are listed in the report rather than hidden.
    """
    days = sessions.sessions_between(start, end)
    if not days:
        raise DataCoverageError(f"no sessions between {start} and {end}")
    irx, rate_gaps = uni["^IRX"], []
    for d in days:
        _irx_rate(irx, d)
        i = irx.count_through(d)
        last = irx.sessions[i - 1]
        if (d - last).days > 7 and (not rate_gaps or not rate_gaps[-1].startswith(last.isoformat())):
            rate_gaps.append(f"{last.isoformat()} -> {irx.sessions[i].isoformat()}")
    qqqm_start = uni["QQQM"].sessions[0]
    for sym, rng in (("SPY", days), ("QQQ", [d for d in days if d <= qqqm_start]),
                     ("QQQM", [d for d in days if d >= qqqm_start])):
        missing = [d for d in rng if not uni[sym].has_bar(d)]
        if missing:
            raise DataCoverageError(f"{sym} has no bar on {len(missing)} session(s) in the window, first {missing[0]}")
    if not any(uni[s].has_bar(days[-1]) for s in tradable):
        raise DataCoverageError(f"no tradable symbol has a bar on {days[-1]}")
    return rate_gaps


def _universe_snapshot(db: Database) -> dict:
    syms = list(db.symbols.find({}, {"asset_class": 1, "tradable": 1, "ca_version": 1}).sort("_id", 1))
    have = set(db.bars.distinct("symbol", {"interval": "1d"}))
    return {"symbols": {s["_id"]: {"asset_class": s.get("asset_class"), "tradable": s.get("tradable", True),
                                   "ca_version": s.get("ca_version", 0)} for s in syms if s["_id"] in have}}


def _protocol_doc(db: Database, candidates: list[str], dev_window: tuple[dt.date, dt.date]) -> dict:
    return _canonical({
        "version": PROTOCOL_VERSION, "candidates": sorted(candidates), "gate": GATE,
        "cost_profile": dataclasses.asdict(BASE_COST), "execution_policy": dataclasses.asdict(ExecutionPolicy()),
        "policy": POLICY_ID, "policy_params": dataclasses.asdict(PolicyParams()),
        "dev_window": [dev_window[0].isoformat(), dev_window[1].isoformat()],
        "universe": _universe_snapshot(db), "code": code_fingerprint(),
    })


def _hash(doc: dict) -> str:
    return hashlib.sha256(json.dumps(doc, sort_keys=True).encode()).hexdigest()


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
    for c in candidates:
        get_spec(c)  # unknown candidates fail now, not at reveal
    protocol = _protocol_doc(db, candidates, dev_window)
    digest = _hash(protocol)
    db.holdouts.update_one({"_id": "primary", "status": "sealed"},
                           {"$set": {"protocol": protocol, "protocol_hash": digest, "frozen_at": now,
                                     "frozen_git_sha": git_sha()}})
    return digest


def reveal_holdout(db: Database, *, protocol_hash: str, now: dt.datetime) -> dict:
    """Evaluate the frozen protocol's candidates on the holdout. Single use.

    Everything that can be checked is checked before the holdout is claimed, so a missing
    benchmark or changed configuration does not burn it; once claimed it is never re-run.
    """
    h = db.holdouts.find_one({"_id": "primary"})
    if h is None or h.get("protocol_hash") is None:
        raise HoldoutError("no frozen protocol")
    if h["status"] != "sealed":
        raise HoldoutError("holdout already consumed; any change needs a new prospective window")
    if protocol_hash != h["protocol_hash"]:
        raise HoldoutError("protocol hash mismatch; the protocol changed after freezing")
    frozen = h["protocol"]
    if _hash(_canonical(frozen)) != h["protocol_hash"]:
        raise HoldoutError("stored protocol does not match its hash")
    dev = tuple(dt.date.fromisoformat(x) for x in frozen["dev_window"])
    current = _protocol_doc(db, frozen["candidates"], dev)
    changed = sorted(k for k in set(frozen) | set(current) if frozen.get(k) != current.get(k))
    if changed:
        raise HoldoutError(f"configuration changed since the protocol was frozen: {', '.join(changed)}")
    start, end = h["start"].date(), h["end"].date()
    uni, tradable = load_universe(db)
    check_coverage(uni, tradable, start, end)
    # Execute exactly the recorded configuration.
    cost = CostProfile(**frozen["cost_profile"])
    policy = ExecutionPolicy(**frozen["execution_policy"])
    pp = dict(frozen["policy_params"])
    pp["levels"] = tuple(tuple(x) for x in pp["levels"])
    params = PolicyParams(**pp)

    claimed = db.holdouts.find_one_and_update({"_id": "primary", "status": "sealed"},
                                              {"$set": {"status": "consumed", "consumed_at": now}})
    if claimed is None:
        raise HoldoutError("holdout already consumed")
    results = {}
    try:
        for key in frozen["candidates"]:
            r = run_backtest(uni, tradable, uni["^IRX"], key, start, end, cost, policy, params)
            _record(db, r, kind="holdout", now=now, excess_sharpe=None)
            results[key] = _evaluate(r, uni, tradable, trial_sharpes=None)
    except Exception as e:
        db.holdouts.update_one({"_id": "primary"}, {"$set": {"evaluation": {"error": f"{type(e).__name__}: {e}"}}})
        raise
    db.holdouts.update_one({"_id": "primary"}, {"$set": {"evaluation": results}})
    return results


# --- development evaluation ------------------------------------------------------------

def _excess_sharpe(r: BacktestResult, irx: SymbolSeries) -> float | None:
    x = stats.daily_returns(r.equity) - baselines.cash_daily_returns(irx, r.dates)
    sd = float(x.std(ddof=1)) if len(x) > 1 else 0.0
    return float(x.mean() / sd) if sd > 0 else None


def _record(db: Database, r: BacktestResult, *, kind: str, now: dt.datetime, excess_sharpe: float | None) -> None:
    db.experiments.insert_one({
        "kind": kind, "protocol_version": PROTOCOL_VERSION, "excess_sharpe": excess_sharpe,
        "sessions": len(r.equity), "strategy": r.strategy, "policy": r.policy, "cost_profile": r.cost_profile,
        "execution_policy": r.execution_policy, "start": dt.datetime.combine(r.start, dt.time(), dt.timezone.utc),
        "end": dt.datetime.combine(r.end, dt.time(), dt.timezone.utc), "git_sha": git_sha(),
        "final_equity": r.equity[-1], "trades": len(r.trades), "created_at": now,
    })


def _evaluate(r: BacktestResult, uni, tradable, trial_sharpes: tuple[list[float], int] | None) -> dict:
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
        sharpes, n_trials = trial_sharpes
        out["deflated_sharpe"] = stats.deflated_sharpe(rets - cash_r[: len(rets)], sharpes, n_trials)
    return out


def run_development(db: Database, *, start: dt.date, end: dt.date, now: dt.datetime,
                    strategies: list[str] | None = None) -> dict:
    hw = holdout_window(db)
    if hw is None:
        raise HoldoutError("seal the holdout before development runs so the window can be excluded")
    if end >= hw[0]:
        raise HoldoutError(f"development window must end before the holdout starts ({hw[0]})")
    uni, tradable = load_universe(db)
    rate_gaps = check_coverage(uni, tradable, start, end)
    keys = strategies or [s.key for s in all_specs()]
    runs: dict[str, BacktestResult] = {}
    stress: dict[str, dict[str, BacktestResult]] = {}
    for key in keys:
        runs[key] = run_backtest(uni, tradable, uni["^IRX"], key, start, end, BASE_COST)
        _record(db, runs[key], kind="development", now=now, excess_sharpe=_excess_sharpe(runs[key], uni["^IRX"]))
        stress[key] = {}
        for factor in (2, 3):
            sr = run_backtest(uni, tradable, uni["^IRX"], key, start, end, BASE_COST.scaled(factor, f"_x{factor}"))
            _record(db, sr, kind=f"stress_costs_x{factor}", now=now, excess_sharpe=_excess_sharpe(sr, uni["^IRX"]))
            stress[key][f"costs_x{factor}"] = sr
    # DSR trials: every development configuration ever recorded for this protocol version (this run's
    # included), so re-running only a previous winner cannot lower the multiple-testing hurdle.
    trial_q = {"kind": "development", "protocol_version": PROTOCOL_VERSION}
    trial_count = db.experiments.count_documents(trial_q)
    trial_sharpes = [d["excess_sharpe"] for d in db.experiments.find({**trial_q, "excess_sharpe": {"$ne": None}},
                                                                     {"excess_sharpe": 1})]
    any_run = next(iter(runs.values()))
    cash_r = baselines.cash_daily_returns(uni["^IRX"], any_run.dates)
    excess = {k: stats.daily_returns(r.equity) - cash_r for k, r in runs.items()}
    results = {}
    for key, r in runs.items():
        ev = _evaluate(r, uni, tradable, (trial_sharpes, trial_count))
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
        "created_at": now, "protocol_version": PROTOCOL_VERSION, "git_sha": git_sha(), "code": code_fingerprint(),
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
        ] + [f"^IRX has no stored rate for {g}; the last known rate is carried across this gap." for g in rate_gaps],
        "rate_gaps": rate_gaps,
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


LOCK_NAME = "research_run"
LEASE = dt.timedelta(minutes=5)
HEARTBEAT_SECONDS = 60


def _claim_lock(db: Database, holder: str, now: dt.datetime) -> bool:
    """Atomically take the research lease if it is free or expired (unique _id makes this race-free)."""
    try:
        db.job_locks.find_one_and_update({"_id": LOCK_NAME, "expires_at": {"$lt": now}},
                                         {"$set": {"holder": holder, "expires_at": now + LEASE, "claimed_at": now}},
                                         upsert=True, return_document=ReturnDocument.AFTER)
        return True
    except DuplicateKeyError:
        return False  # held by a live worker


def start_development_job(db: Database, *, dev_start: dt.date, dev_end: dt.date, holdout_start: dt.date,
                          run_in_thread: bool = True) -> str:
    """Run seal + development evaluation in a background thread, tracked in `jobs`.

    Only one run at a time: the worker holds an expiring lease that it renews every minute. If a
    deploy or crash kills the worker, the lease lapses and the next request marks the orphaned job
    ``abandoned`` and proceeds.
    """
    import threading
    import traceback
    from bson import ObjectId
    now = dt.datetime.now(dt.timezone.utc)
    job_id = ObjectId()
    if not _claim_lock(db, str(job_id), now):
        raise JobConflict("a research run is already in progress")
    db.jobs.update_many({"kind": "research", "status": "running"},
                        {"$set": {"status": "abandoned", "finished_at": now,
                                  "error": "worker stopped without finishing (lease expired)"}})
    db.jobs.insert_one({"_id": job_id, "kind": "research", "status": "running", "started_at": now})
    stop = threading.Event()

    def heartbeat():
        while not stop.wait(HEARTBEAT_SECONDS):
            db.job_locks.update_one({"_id": LOCK_NAME, "holder": str(job_id)},
                                    {"$set": {"expires_at": dt.datetime.now(dt.timezone.utc) + LEASE}})

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
            db.jobs.update_one({"_id": job_id}, {"$set": {"status": "failed", "finished_at": dt.datetime.now(dt.timezone.utc),
                                                         "error": f"{type(e).__name__}: {e}",
                                                         "traceback": traceback.format_exc()[-4000:]}})
        finally:
            stop.set()
            db.job_locks.delete_one({"_id": LOCK_NAME, "holder": str(job_id)})

    if run_in_thread:
        threading.Thread(target=heartbeat, daemon=True).start()
        threading.Thread(target=work, daemon=True).start()
    else:
        work()
    return str(job_id)
