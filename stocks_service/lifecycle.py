"""Strategy lifecycle (plan §E): live tracking, automatic pause, promotion workflow.

* **Parity** — every outlook persists its decisions as immutable ``live`` signals; the tick replays
  each one through ``run_decision`` (``check_parity``). A mismatch records a violation and pauses the
  version.
* **Forecast tracking** — each outlook row with an estimate is scored once its outcome is known,
  with the same simulator, cost profile and T-bill adjustment as the calibration labels:
  ``forecast_outcomes`` holds predicted vs realized excess and the win forecast.
* **Monitors** — per source (strategy version or base rate), over the last ``WINDOW`` resolved
  forecasts: the realized mean must stay above the predicted mean's lower 95% band, and the Brier
  score of the win forecast must not exceed that of the pooled base rate. A breach pauses an
  ``active``/``candidate`` version (research versions are flagged only).
* **Pause blocks new entries only**: the version's outlook rows lose their estimate (also in an
  outlook built before the pause), tickets and new paper orders from it are refused, open paper
  *entry* orders whose session has not opened are cancelled; filled positions keep their exits and
  protective alerts. Parity violations go through the same pause.
* **Transitions** are explicit and recorded in ``lifecycle_events``:
  research -> candidate (passed the development gate), candidate -> active (passed the holdout and a
  live shadow period without breaches), active|candidate -> paused, paused -> candidate (must earn
  ``active`` again), any -> retired.
"""

from __future__ import annotations

import datetime as dt
import math

import numpy as np
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from . import sessions
from .outlook.build import cost_profile_from_doc
from .research.backtest import _irx_rate
from .research.series import SymbolSeries
from .sim import DataGapError, ExecutionPolicy, TradePlan, net_trade, simulate_trade
from .strategies.runner import LIVE, check_parity

WINDOW = 30
SHADOW_MIN = 30
POLICY = ExecutionPolicy()
TRANSITIONS = {
    ("research", "candidate"), ("research", "paused"), ("candidate", "active"), ("active", "paused"), ("candidate", "paused"),
    ("paused", "candidate"), ("research", "retired"), ("candidate", "retired"), ("active", "retired"),
    ("paused", "retired"),
}


class LifecycleError(ValueError):
    pass


# --- parity ------------------------------------------------------------------------------------

def run_parity(db: Database, now: dt.datetime, limit: int = 2000) -> dict:
    """Replay unchecked live decisions; mismatches pause their version (inside ``check_parity``)."""
    checked = violations = 0
    for s in db.signals.find({"source": LIVE, "parity_checked_at": {"$exists": False}}).limit(limit):
        ok = check_parity(db, s["strategy"], s["symbol"], s["asof"].date(), now=now, pause=False)
        if not ok:
            v = db.strategy_versions.find_one({"_id": s["strategy"]})
            if v and v.get("status") not in ("paused", "retired"):
                pause(db, s["strategy"], reason="parity_violation", now=now, by="parity",
                      evidence={"symbol": s["symbol"], "asof": s["asof"].date().isoformat()})
        db.signals.update_one({"_id": s["_id"]}, {"$set": {"parity_checked_at": now, "parity_ok": ok}})
        checked += 1
        violations += 0 if ok else 1
    return {"checked": checked, "violations": violations}


# --- forecast tracking ---------------------------------------------------------------------------

def track_forecasts(db: Database, now: dt.datetime) -> dict:
    """Score every outlook row whose outcome has resolved (latest build per session, once per row)."""
    cache: dict[str, SymbolSeries] = {}
    irx = SymbolSeries.from_db(db, "^IRX")
    resolved = pending = gaps = 0
    runs = {}
    for r in db.outlook_runs.find({}, {"asof": 1, "created_at": 1, "cost": 1}).sort([("created_at", 1), ("_id", 1)]):
        runs[r["asof"]] = r  # latest build per session wins
    for asof, run_meta in sorted(runs.items()):
        done = {(f["symbol"], f["side"]) for f in db.forecast_outcomes.find({"asof": asof}, {"symbol": 1, "side": 1})}
        run = db.outlook_runs.find_one({"_id": run_meta["_id"]}, {"rows": 1, "cost": 1})
        cost = cost_profile_from_doc(run["cost"])
        d = dt.date.fromisoformat(asof)
        for row in run["rows"]:
            est = row.get("estimate")
            if (row["symbol"], row["side"]) in done or not row.get("plan") or not est or est.get("mean_excess") is None:
                continue
            s = cache.get(row["symbol"]) or cache.setdefault(row["symbol"], SymbolSeries.from_db(db, row["symbol"]))
            p = row["plan"]
            plan = TradePlan(row["side"], d, p["entry_limit"], p["stop"], p["target"])  # as the labels do
            bars = s.bars_after(d, POLICY.timeout_sessions + 3)
            if not bars:
                pending += 1
                continue
            try:
                oc = simulate_trade(plan, bars, sessions.next_session(d), POLICY)
            except DataGapError:
                gaps += 1
                continue
            if oc.result == "unresolved":
                pending += 1
                continue
            if oc.result == "not_filled":
                net, excess = 0.0, 0.0
            else:
                nt = net_trade(oc, row["side"], 10_000.0 / oc.fill_price, cost, s.dividends_on_basis(d))
                net = nt.net_return
                excess = net - _irx_rate(irx, d) * (oc.exit_session - oc.fill_session).days / 360
            try:
                db.forecast_outcomes.insert_one({
                    "asof": asof, "symbol": row["symbol"], "side": row["side"], "source": row["source"],
                    "grade": row["grade"], "predicted_mean_excess": est["mean_excess"], "p_win": est["p_win"],
                    "p10_excess": est["p10_excess"], "p90_excess": est["p90_excess"], "result": oc.result,
                    "net_return": net, "realized_excess": excess, "win": excess > 0,
                    "resolved_session": (oc.exit_session or sessions.next_session(d)).isoformat(), "recorded_at": now})
                resolved += 1
            except DuplicateKeyError:
                pass
    return {"resolved": resolved, "pending": pending, "data_gaps": gaps}


# --- monitors ------------------------------------------------------------------------------------

def monitor(db: Database, source: str) -> dict:
    """Rolling checks over the last WINDOW resolved forecasts of one source."""
    xs = list(db.forecast_outcomes.find({"source": source}).sort([("resolved_session", -1), ("asof", -1)]).limit(WINDOW))
    n = len(xs)
    out = {"source": source, "n": n, "window": WINDOW}
    if n < WINDOW:
        out["status"] = "insufficient"
        return out
    realized = np.array([x["realized_excess"] for x in xs])
    pred = np.array([x["predicted_mean_excess"] for x in xs])
    sd = np.array([(x["p90_excess"] - x["p10_excess"]) / 2.563 for x in xs])   # normal-equivalent spread
    lower = float(pred.mean() - 1.96 * math.sqrt(float(np.mean(sd ** 2)) / n))
    wins = np.array([1.0 if x["win"] else 0.0 for x in xs])
    brier = float(np.mean((np.array([x["p_win"] for x in xs]) - wins) ** 2))
    base = float(np.mean((wins.mean() - wins) ** 2))  # climatology over the same window
    out.update(realized_mean=float(realized.mean()), predicted_mean=float(pred.mean()), lower_band=lower,
               brier=brier, brier_climatology=base)
    breaches = []
    if realized.mean() < lower:
        breaches.append("realized mean below the forecast's lower 95% band")
    if brier > base:
        breaches.append("win forecasts score worse than the base rate (Brier deterioration)")
    out["breaches"] = breaches
    out["status"] = "breach" if breaches else "ok"
    return out


def run_monitors(db: Database, now: dt.datetime) -> list[dict]:
    out = []
    for source in db.forecast_outcomes.distinct("source"):
        m = monitor(db, source)
        out.append(m)
        if m["status"] == "breach" and source.startswith("signal:"):
            key = source.removeprefix("signal:")
            v = db.strategy_versions.find_one({"_id": key})
            if v and v.get("status") in ("active", "candidate"):
                pause(db, key, reason="; ".join(m["breaches"]), now=now, by="monitor", evidence=m)
    return out


# --- transitions ---------------------------------------------------------------------------------

def _event(db, key, frm, to, reason, now, by, evidence=None):
    db.lifecycle_events.insert_one({"strategy": key, "from": frm, "to": to, "reason": reason, "by": by,
                                    "evidence": evidence, "at": now})


def pause(db: Database, key: str, *, reason: str, now: dt.datetime, by: str, evidence=None) -> dict:
    """Block new entries from ``key``: status paused, open paper entry orders from it cancelled."""
    v = db.strategy_versions.find_one({"_id": key})
    if v is None:
        raise LifecycleError(f"unknown strategy version {key}")
    frm = v.get("status", "research")
    if frm not in ("active", "candidate", "research"):
        raise LifecycleError(f"{key} is {frm}; only research, candidate or active versions can be paused")
    res = db.strategy_versions.update_one({"_id": key, "status": v.get("status")},
                                          {"$set": {"status": "paused", "paused_reason": reason, "paused_at": now,
                                                    "paused_from": frm}})
    if res.matched_count == 0:
        raise LifecycleError(f"{key} changed status concurrently; retry")
    # Only orders whose session has not opened: earlier ones are settled by the broker as usual.
    cancelled = 0
    for o in db.orders.find({"status": "open", "source": f"signal:{key}"}, {"eligible_session": 1}):
        if now < sessions.session_bounds(o["eligible_session"].date())[0]:
            cancelled += db.orders.update_one({"_id": o["_id"], "status": "open"},
                                              {"$set": {"status": "cancelled", "cancelled_at": now,
                                                        "cancel_reason": f"strategy {key} paused"}}).modified_count
    _event(db, key, frm, "paused", reason, now, by, {**(evidence or {}), "cancelled_entry_orders": cancelled})
    return {"strategy": key, "status": "paused", "cancelled_entry_orders": cancelled}


def _research_eligible(db: Database, key: str) -> tuple[bool, str]:
    rep = db.research_reports.find_one(sort=[("created_at", -1), ("_id", -1)])
    if rep is None or key not in rep.get("results", {}):
        return False, "no development research result for this version"
    if not rep["results"][key]["gate"]["eligible"]:
        failed = [k for k, ok in rep["results"][key]["gate"]["checks"].items() if not ok]
        return False, f"development gate failed: {', '.join(failed)}"
    return True, "passed the development gate"


def _holdout_and_shadow(db: Database, key: str) -> tuple[bool, str, dict]:
    from .research.protocol import GATE
    h = db.holdouts.find_one({"_id": "primary"})
    ev = (h or {}).get("evaluation") or {}
    res = ev.get(key)
    if not res:
        return False, "no holdout evaluation for this version (freeze and reveal the protocol first)", {}
    ci_lo = res["comparisons"]["cash"]["excess_ci95"][0]
    mdd = res["metrics"]["max_drawdown"]
    if not (ci_lo > GATE["excess_vs_cash_ci_lower_gt"] and mdd <= GATE["max_drawdown_le"]):
        return False, f"holdout failed (excess CI lower {ci_lo:.4f}, max drawdown {mdd:.2%})", {}
    m = monitor(db, f"signal:{key}")
    n = db.forecast_outcomes.count_documents({"source": f"signal:{key}"})
    if n < SHADOW_MIN:
        return False, f"shadow period: {n} of {SHADOW_MIN} live forecasts resolved", m
    if m["status"] == "breach":
        return False, f"shadow period breached: {'; '.join(m['breaches'])}", m
    return True, "passed the holdout and the live shadow period", m


def transition(db: Database, key: str, to: str, *, reason: str, now: dt.datetime, by: str = "api") -> dict:
    v = db.strategy_versions.find_one({"_id": key})
    if v is None:
        raise LifecycleError(f"unknown strategy version {key}")
    frm = v.get("status", "research")
    if (frm, to) not in TRANSITIONS:
        raise LifecycleError(f"{frm} -> {to} is not an allowed transition")
    if to == "paused":
        return pause(db, key, reason=reason, now=now, by=by)
    evidence = {}
    if to == "candidate":
        ok, why = _research_eligible(db, key)
        if not ok:
            raise LifecycleError(why)
        evidence["research"] = why
    if to == "active":
        ok, why, m = _holdout_and_shadow(db, key)
        if not ok:
            raise LifecycleError(why)
        evidence.update(holdout_and_shadow=why, monitor=m)
    update = {"$set": {"status": to, f"{to}_at": now}}
    if to != "retired":
        update["$unset"] = {"paused_reason": ""}
    if db.strategy_versions.update_one({"_id": key, "status": v.get("status")}, update).matched_count == 0:
        raise LifecycleError(f"{key} changed status concurrently; retry")
    _event(db, key, frm, to, reason, now, by, evidence)
    return {"strategy": key, "from": frm, "to": to, "evidence": evidence}
