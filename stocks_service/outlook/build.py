"""Six-month outlook rows (plan §C): every watched symbol x {long, short}.

Each row has the plan (entry limit, stop, target from the ATR levels, placeable until the next
open), the strategies signalling that side today, and an estimate from calibrated outcome
distributions. The estimate is the best published one:

* grade **A**: a calibrated signal bucket of an ``active`` strategy version;
* grade **B**: a calibrated signal bucket of a strategy that is not (yet) active — shown,
  labelled "not validated";
* grade **C**: no calibrated signal — the symbol's own historical base rate for this plan;
* ``insufficient``: none of the above (reasons listed).

Expected six-month return = expected excess over T-bills + the T-bill return over the horizon
(the ^IRX rate today, accrued to the open of session 127 after the next session).
"""

from __future__ import annotations

import dataclasses
import datetime as dt

from pymongo.database import Database

from .. import jobs, sessions
from ..levels import LevelsUnavailable, atr_levels
from ..research.backtest import PolicyParams, _irx_rate
from ..research.protocol import holdout_window, load_universe
from ..sim import CostProfile, ExecutionPolicy
from ..strategies import all_specs, decide
from ..strategies.runner import LIVE, persist_decision
from .. import umpires
from .calibration import CALIBRATION_VERSION, calibrate
from .labels import BASE, LABEL_VERSION, STRIDE, build_labels

OUTLOOK_VERSION = "outlook@1"
LABEL_START = dt.date(1990, 1, 2)
GRADE_ORDER = {"A": 0, "B": 1, "C": 2, "insufficient": 3}


class OutlookUnavailable(RuntimeError):
    pass


# --- cost profiles (explicit, versioned, immutable) -------------------------------------------

def cost_profile_from_doc(doc: dict) -> CostProfile:
    return CostProfile(doc["profile_id"], doc["version"], doc["commission_per_share"], doc["min_commission"],
                       doc["half_spread_bps"], doc["slippage_bps"], doc["borrow_rate_annual"])


def latest_cost_profile(db: Database, profile_id: str) -> CostProfile | None:
    doc = db.cost_profiles.find_one({"profile_id": profile_id}, sort=[("version", -1)])
    return cost_profile_from_doc(doc) if doc else None


# --- calibration + outlook --------------------------------------------------------------------

def run_calibration(db: Database, *, now: dt.datetime, log=None, symbols: list[str] | None = None,
                    strategies: list[str] | None = None) -> dict:
    cost = latest_cost_profile(db, "market")
    if cost is None:
        raise OutlookUnavailable("no 'market' cost profile; create one with POST /api/v1/cost-profiles")
    hw = holdout_window(db)
    if hw is None:
        raise OutlookUnavailable("the research holdout is not sealed; run POST /api/v1/research/run first")
    uni, tradable = load_universe(db)
    syms = [s for s in tradable if symbols is None or s in symbols]
    keys = strategies or [s.key for s in all_specs()]
    labels, stats = build_labels(uni, syms, uni["^IRX"], keys, LABEL_START, hw[0], cost, resolved_before=hw[0], log=log)
    buckets = calibrate(labels, hw[0])
    doc = {"created_at": now, "version": CALIBRATION_VERSION, "label_version": LABEL_VERSION, "stride": STRIDE,
           "cost_profile": cost.key, "execution_policy": ExecutionPolicy().key,
           "levels": PolicyParams().levels_dict, "resolved_before": hw[0].isoformat(),
           "symbols": syms, "strategies": keys, "label_stats": stats, "buckets": buckets}
    doc["_id"] = db.calibrations.insert_one(doc).inserted_id
    return doc


def build_outlook(db: Database, *, now: dt.datetime, calibration: dict | None = None) -> dict:
    cal = calibration or db.calibrations.find_one(sort=[("created_at", -1), ("_id", -1)])
    if cal is None:
        raise OutlookUnavailable("no calibration yet; run the outlook job with the calibrate step")
    cost = latest_cost_profile(db, "market")
    if cost is None or cost.key != cal["cost_profile"]:
        raise OutlookUnavailable(f"calibration used {cal['cost_profile']} but the market profile is now "
                                 f"{cost.key if cost else 'missing'}; recalibrate")
    uni, _ = load_universe(db)
    # Every watched symbol gets rows, including ones whose history has not been loaded yet.
    watched = sorted(s["_id"] for s in db.symbols.find(
        {"enabled": {"$ne": False}, "tradable": {"$ne": False}, "asset_class": {"$in": ["equity", "etf"]}}, {"_id": 1}))
    irx = uni["^IRX"]
    asof = uni["SPY"].sessions[-1]
    nxt = sessions.next_session(asof)
    horizon_end = sessions.session_after_n(nxt, 127)
    cash_6m = _irx_rate(irx, asof) * (horizon_end - nxt).days / 360
    open_, close = sessions.session_bounds(nxt)
    statuses = {v["_id"]: v.get("status", "research") for v in db.strategy_versions.find()}
    sig_buckets = {(b["strategy"], b["side"]): b for b in cal["buckets"] if b["strategy"] != BASE}
    base_buckets = {(b["symbol"], b["side"]): b for b in cal["buckets"] if b["strategy"] == BASE}
    params = PolicyParams()
    shorts_ok = cost.borrow_rate_annual is not None
    common = {"asof": asof.isoformat(), "placeable_until": open_.isoformat(), "valid_until": close.isoformat()}

    def empty_row(sym: str, side: str, reason: str) -> dict:
        return {"symbol": sym, "side": side, **common, "last_close": None, "plan": None, "signals": [],
                "grade": "insufficient", "source": "none", "reasons": [reason], "validated": False,
                "base_rate": None, "estimate": None}

    rows = []
    feats: dict = {}
    for sym in watched:
        series = uni.get(sym)
        if series is None or not series.sessions:
            rows += [empty_row(sym, side, "no price history loaded yet") for side in ("long", "short")]
            continue
        if not series.has_bar(asof):
            rows += [empty_row(sym, side, f"no bar on {asof} (last {series.sessions[-1]})") for side in ("long", "short")]
            continue
        view = series.view_at(asof)
        feats[sym] = umpires.features(view)
        decisions = {spec.key: decide(view, spec) for spec in all_specs() if len(view) >= spec.min_bars}
        for dec in decisions.values():  # immutable live record; the nightly parity check replays it
            persist_decision(db, dec, source=LIVE, now=now)
        for side in ("long", "short"):
            if side == "short" and not shorts_ok:
                rows.append(empty_row(sym, side, f"cost profile {cost.key} has no borrow rate, so shorts are disabled"))
                continue
            reasons = []
            try:
                lv = atr_levels(view, side, params.levels_dict)
                plan = {"entry_limit": lv.entry_limit, "stop": lv.stop, "target": lv.target, "atr": lv.atr,
                        "risk_pct": lv.risk_pct, "reward_pct": lv.reward_pct}
            except LevelsUnavailable as e:
                plan, lv = None, None
                reasons.append(str(e))
            signals = [{"strategy": k, "strength": d.strength, "status": statuses.get(k, "research"),
                        "bucket_status": sig_buckets.get((k, side), {}).get("status", "none")}
                       for k, d in decisions.items() if d.direction == side]
            base = base_buckets.get((sym, side))
            options = []
            for sg in signals:
                bk = sig_buckets.get((sg["strategy"], side))
                if bk and bk["status"] == "calibrated" and sg["status"] not in ("paused", "retired"):
                    options.append(("A" if sg["status"] == "active" else "B", bk, f"signal:{sg['strategy']}"))
            if not options and base and base["status"] == "base_rate":
                options.append(("C", base, "base_rate"))
            if plan is not None and options:
                grade, est, source = min(options, key=lambda o: (GRADE_ORDER[o[0]], -o[1]["mean_excess"]))
            else:
                grade, est, source = "insufficient", None, "none"
            if grade == "insufficient" and not reasons:
                reasons.append("no calibrated signal and fewer than the minimum base-rate labels for this symbol")
            if signals and grade == "C":
                reasons.append("signals present but none has demonstrated out-of-sample skill; showing the base rate")
            row = {
                "symbol": sym, "side": side, **common, "last_close": float(view.c[-1]), "plan": plan,
                "signals": signals, "grade": grade, "source": source, "reasons": reasons,
                "validated": grade == "A",
                "base_rate": _brief(base),
                "estimate": _brief(est),
            }
            _set_estimate(row, est, cash_6m)
            rows.append(row)
    _annotate_umpires(db, rows, feats)
    rows.sort(key=lambda r: (GRADE_ORDER[r["grade"]] == 3, -(r.get("exp_return_6m") or -1e9), r["symbol"], r["side"]))
    doc = {"created_at": now, "version": OUTLOOK_VERSION, "asof": asof.isoformat(), "calibration_id": cal["_id"],
           "cost_profile": cost.key, "cost": dataclasses.asdict(cost), "execution_policy": cal["execution_policy"],
           "reference_notional": 10_000.0, "shorts_enabled": shorts_ok, **common, "cash_return_6m": cash_6m, "horizon_end": horizon_end.isoformat(),
           "rows": rows,
           # Symbols without a bar on asof when this outlook was built; the tick rebuilds the same
           # session's outlook once any of them arrives.
           "missing_inputs": sorted({r["symbol"] for r in rows if r.get("last_close") is None})}
    db.outlook_runs.insert_one(doc)
    return doc


def _annotate_umpires(db: Database, rows: list[dict], feats: dict) -> None:
    """Umpire annotations (never filtering): kNN vote and loss-cluster flag per row, or why not."""
    model_id, models, evaluation = umpires.latest_models(db)
    for side in ("long", "short"):
        todo = [r for r in rows if r["side"] == side and r.get("plan") and feats.get(r["symbol"]) is not None]
        m = models.get(side)
        if m is None or not todo:
            for r in todo:
                r["umpires"] = {"status": "untrained"}
            continue
        import numpy as _np
        verdict = evaluation.get(side, {}).get("verdict", "unevaluated")
        for r, a in zip(todo, m.annotate(_np.vstack([feats[r["symbol"]] for r in todo]))):
            # The side's walk-forward verdict travels with every vote: a veto from a "not_useful"
            # umpire is shown but should not be relied on.
            r["umpires"] = {"status": "annotated", "model": model_id, "side_verdict": verdict, **a}
    for r in rows:
        r.setdefault("umpires", {"status": "unavailable"})


EST_FIELDS = ("exp_excess_6m", "exp_return_6m", "p10_return_6m", "p90_return_6m", "exp_return_per_session")


def _set_estimate(row: dict, est: dict | None, cash_6m: float) -> None:
    for k in EST_FIELDS:
        row.pop(k, None)
    if est and est.get("mean_excess") is not None:
        row["exp_excess_6m"] = est["mean_excess"]
        row["exp_return_6m"] = est["mean_excess"] + cash_6m
        row["p10_return_6m"] = est["p10_excess"] + cash_6m
        row["p90_return_6m"] = est["p90_excess"] + cash_6m
        held = est.get("mean_sessions_held")
        row["exp_return_per_session"] = (est["mean_excess"] / held) if held else None


def apply_current_status(doc: dict, statuses: dict[str, str]) -> dict:
    """Rows sourced from a version that is now paused or retired fall back to the base rate (or
    insufficient) — a paused version supplies no estimates or entries even from an earlier build."""
    for r in doc["rows"]:
        src = r.get("source", "")
        if not src.startswith("signal:") or statuses.get(src.removeprefix("signal:")) not in ("paused", "retired"):
            continue
        base = r.get("base_rate")
        if base and base.get("status") == "base_rate" and base.get("mean_excess") is not None:
            r.update(grade="C", source="base_rate", estimate=base, validated=False)
        else:
            r.update(grade="insufficient", source="none", estimate=None, validated=False)
        r["reasons"] = r.get("reasons", []) + [f"{src.removeprefix('signal:')} is paused; its estimate is withheld"]
        _set_estimate(r, r["estimate"], doc["cash_return_6m"])
    return doc


def _brief(b: dict | None) -> dict | None:
    if not b:
        return None
    keep = ("strategy", "symbol", "side", "status", "n", "n_symbols", "p", "fill_rate", "p_win", "mean_excess",
            "p10_excess", "p50_excess", "p90_excess", "mean_sessions_held", "brier_skill", "n_oos",
            "first_decided", "last_decided")
    return {k: b.get(k) for k in keep}


def latest_outlook(db: Database) -> dict | None:
    doc = db.outlook_runs.find_one(sort=[("created_at", -1), ("_id", -1)])
    if doc:
        doc["run_id"] = str(doc.pop("_id"))   # immutable id of exactly this outlook build
        doc["calibration_id"] = str(doc["calibration_id"])
        apply_current_status(doc, {v["_id"]: v.get("status") for v in db.strategy_versions.find({}, {"status": 1})})
    return doc


def start_outlook_job(db: Database, *, steps: list[str], run_in_thread: bool = True) -> str:
    bad = [s for s in steps if s not in ("calibrate", "outlook")]
    if bad or not steps:
        raise ValueError(f"steps must be a non-empty subset of ['calibrate', 'outlook'], got {steps}")

    def work(log):
        now = dt.datetime.now(dt.timezone.utc)
        out = {}
        cal = None
        if "calibrate" in steps:
            cal = run_calibration(db, now=now, log=log)
            out["calibration"] = {"label_stats": cal["label_stats"],
                                  "calibrated": [b["strategy"] + ":" + b["side"] for b in cal["buckets"]
                                                 if b["status"] == "calibrated"]}
            log(step="calibrate", **out["calibration"]["label_stats"])
        if "outlook" in steps:
            o = build_outlook(db, now=now, calibration=cal)
            out["outlook"] = {"asof": o["asof"], "rows": len(o["rows"])}
            log(step="outlook", **out["outlook"])
        return out

    return jobs.start_job(db, "outlook", work, params={"steps": steps}, run_in_thread=run_in_thread)
