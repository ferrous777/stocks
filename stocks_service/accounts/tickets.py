"""Order tickets, opportunity actions and protective alerts for real accounts (plan §E, §F).

* **Tickets** — only for rows backed by an ``active`` strategy version (grade A), sized by the
  account's risk profile. Written in Fidelity's terms: Buy / Sell Short, Limit, DAY, place before
  the next open; the stop and take-profit orders to enter after the fill. Rows from research or
  candidate versions never get a ticket or a quantity.
* **Actions** — ``taken`` (with the fills) or ``skipped`` (with a reason) for an outlook row; a
  taken action records the position's protective levels and its 126-session timeout.
* **Protective alerts** — run by the tick for every protected holding, whatever the status of
  the strategy that suggested it: stop crossed, target crossed, timeout due. Each alert is stored
  once (dedupe key) with the price and the session it is based on.
"""

from __future__ import annotations

import datetime as dt

from bson import ObjectId
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from .. import sessions
from ..research.protocol import load_universe
from .risk import Book, RiskProfile, avg_dollar_volume, cluster_keys, correlation_clusters, size_ticket
from .service import AccountError, NotFound, account_outlook, get_account, holdings, ledger_state

TIMEOUT_SESSIONS = 126


def get_risk_profile(db: Database, key: str | None) -> RiskProfile | None:
    if not key:
        return None
    doc = db.risk_profiles.find_one({"_id": key})
    return RiskProfile.from_doc(doc) if doc else None


def _protected(db: Database, account_id: str) -> list[dict]:
    return list(db.position_levels.find({"account_id": account_id, "active": True}))


def build_tickets(db: Database, account_id: str, now: dt.datetime) -> dict:
    acc = get_account(db, account_id)
    o = account_outlook(db, account_id, now)
    h = holdings(db, account_id, now)
    profile = get_risk_profile(db, acc.get("risk_profile"))
    out = {"account_id": account_id, "asof": o["asof"], "risk_profile": profile.key if profile else None,
           "tickets": [], "withheld": [], "informational_rows": 0}
    eligible = [r for r in o["rows"] if r["grade"] == "A" and r.get("kind") == "new" and r.get("plan")]
    out["informational_rows"] = sum(1 for r in o["rows"] if r["grade"] in ("B", "C"))
    if not eligible:
        out["note"] = ("No row is backed by an active (validated) strategy version, so no tickets or quantities "
                       "are produced. Rows graded B or C are informational only.")
        return out
    if profile is None:
        out["withheld"] = [{"symbol": r["symbol"], "side": r["side"], "reason": "account has no risk profile"}
                           for r in eligible]
        return out
    if h["equity"] is None or h["equity"] <= 0:
        raise AccountError(f"account equity is unavailable (unpriced: {h['unmarked']}); cannot size tickets")
    uni, tradable = load_universe(db)
    asof = dt.date.fromisoformat(o["asof"])
    corr = correlation_clusters(uni, [s for s in tradable if uni[s].has_bar(asof)], asof, profile.corr_threshold)
    sym_docs = {d["_id"]: d for d in db.symbols.find({}, {"groups": 1, "shortable": 1})}
    groups = {s: d.get("groups", []) for s, d in sym_docs.items()}
    book = Book(equity=h["equity"], cash=h["cash"])
    for p in h["positions"]:
        mv = abs(p["market_value"] or 0.0)
        book.gross += mv
        if p["qty"] < 0:
            book.short += mv
        for k in cluster_keys(p["symbol"], groups, corr):
            book.clusters[k] = book.clusters.get(k, 0.0) + mv
    st = ledger_state(db, account_id, now)
    marks = {p["symbol"]: p["mark"] for p in h["positions"]}
    for lv in _protected(db, account_id):
        q = st.qty(lv["symbol"])
        if q and marks.get(lv["symbol"]):
            book.heat += abs(q) * (abs(marks[lv["symbol"]] - lv["stop"]) + profile.gap_stress_atr * lv.get("atr", 0.0))
    for r in sorted(eligible, key=lambda r: -(r.get("exp_return_6m") or -1e9)):
        sym = r["symbol"]
        qty, reasons, limits = size_ticket(r, book, profile, keys=cluster_keys(sym, groups, corr),
                                           adv_usd=avg_dollar_volume(uni[sym], asof),
                                           shortable=bool(sym_docs.get(sym, {}).get("shortable")))
        if qty < 1:
            out["withheld"].append({"symbol": sym, "side": r["side"], "reason": reasons[0]})
            continue
        out["tickets"].append(_ticket(r, qty, reasons, profile, o))
    return out


def _ticket(r: dict, qty: int, reasons: list[str], profile: RiskProfile, o: dict) -> dict:
    p = r["plan"]
    long = r["side"] == "long"
    entry, stop, target = round(p["entry_limit"], 2), round(p["stop"], 2), round(p["target"], 2)
    notional = qty * entry
    loss = qty * (abs(entry - stop) + profile.gap_stress_atr * p["atr"])
    t = {
        "symbol": r["symbol"], "action": "Buy" if long else "Sell Short", "order_type": "Limit",
        "limit_price": entry, "quantity": qty, "time_in_force": "Day",
        "place_before": r["placeable_until"], "valid_until": r["valid_until"],
        "after_fill": [
            {"action": "Sell" if long else "Buy to Cover", "order_type": "Stop", "stop_price": stop,
             "time_in_force": "Good 'til Canceled"},
            {"action": "Sell" if long else "Buy to Cover", "order_type": "Limit", "limit_price": target,
             "time_in_force": "Good 'til Canceled"},
        ],
        "timeout": f"exit at the open after {TIMEOUT_SESSIONS} sessions if neither order has filled",
        "estimated_cost": notional, "max_loss_at_stop_with_gap": loss,
        "expected_profit_6m_vs_cash": notional * r["exp_excess_6m"],
        "expected_return_6m": r["exp_return_6m"], "grade": r["grade"], "source": r["source"],
        "sizing": reasons, "outlook_asof": o["asof"],
    }
    if not long:
        t["notes"] = ["Confirm borrow availability and the borrow rate with Fidelity before placing."]
    return t


# --- actions and protective levels -----------------------------------------------------------

def record_action(db: Database, account_id: str, *, outlook_asof: str, symbol: str, side: str, action: str,
                  reason: str | None, exec_ids: list[str], stop: float | None, target: float | None,
                  now: dt.datetime) -> dict:
    get_account(db, account_id)
    run = db.outlook_runs.find_one({"asof": outlook_asof}, sort=[("created_at", -1), ("_id", -1)])
    if run is None:
        raise NotFound(f"no outlook for {outlook_asof}")
    row = next((r for r in run["rows"] if r["symbol"] == symbol and r["side"] == side), None)
    if row is None:
        raise NotFound(f"{symbol} {side} is not in the {outlook_asof} outlook")
    if action == "skipped" and not reason:
        raise AccountError("a skipped action needs a reason")
    doc = {"_id": ObjectId(), "account_id": account_id, "outlook_asof": outlook_asof, "outlook_run": run["_id"],
           "symbol": symbol, "side": side, "action": action, "reason": reason, "exec_ids": exec_ids,
           "row": {k: row.get(k) for k in ("grade", "source", "plan", "exp_return_6m", "estimate")},
           "created_at": now}
    if action == "taken":
        if not exec_ids:
            raise AccountError("a taken action needs the exec_ids of its fills (record the fills first)")
        fills = list(db.executions.find({"account_id": account_id, "exec_id": {"$in": exec_ids}}))
        if len(fills) != len(set(exec_ids)):
            raise AccountError("unknown exec_ids; record the fills first")
        plan = row.get("plan") or {}
        stop = stop if stop is not None else plan.get("stop")
        target = target if target is not None else plan.get("target")
        if stop is None:
            raise AccountError("a stop is required to protect a taken position")
        first = min(f["ts"] for f in fills)
        fill_session = sessions.exchange_date(first if first.tzinfo else first.replace(tzinfo=dt.timezone.utc))
        if not sessions.is_session(fill_session):
            fill_session = sessions.next_session(fill_session)
        set_levels(db, account_id, symbol=symbol, side=side, stop=stop, target=target, atr=plan.get("atr", 0.0),
                   timeout_session=sessions.session_after_n(fill_session, TIMEOUT_SESSIONS),
                   source=f"action:{doc['_id']}", now=now)
    db.opportunity_actions.insert_one(doc)
    return doc


def set_levels(db: Database, account_id: str, *, symbol: str, side: str, stop: float, target: float | None,
               atr: float = 0.0, timeout_session: dt.date | None = None, source: str, now: dt.datetime) -> dict:
    """Protective levels for a holding (replaces any active ones for the same symbol)."""
    long = side == "long"
    if target is not None and (target <= stop if long else target >= stop):
        raise AccountError("target must be beyond the entry side of the stop (long: target > stop)")
    db.position_levels.update_many({"account_id": account_id, "symbol": symbol, "active": True},
                                   {"$set": {"active": False, "replaced_at": now}})
    doc = {"_id": ObjectId(), "account_id": account_id, "symbol": symbol, "side": side, "stop": stop,
           "target": target, "atr": atr, "active": True, "source": source, "created_at": now,
           "timeout_session": (dt.datetime.combine(timeout_session, dt.time(), dt.timezone.utc)
                               if timeout_session else None)}
    db.position_levels.insert_one(doc)
    return doc


def check_protective(db: Database, now: dt.datetime) -> list[dict]:
    """Alerts for every protected holding (independent of strategy status). Returns new alerts."""
    created = []
    for lv in db.position_levels.find({"active": True}):
        st = ledger_state(db, lv["account_id"], now)
        q = st.qty(lv["symbol"])
        long = lv["side"] == "long"
        if not q or (q > 0) != long:
            db.position_levels.update_one({"_id": lv["_id"]}, {"$set": {"active": False, "closed_at": now}})
            continue
        bar = db.bars.find_one({"symbol": lv["symbol"], "interval": "1d"}, sort=[("session", -1)])
        if bar is None:
            continue
        session = bar["session"].date()
        hits = []
        if (bar["l"] <= lv["stop"]) if long else (bar["h"] >= lv["stop"]):
            hits.append(("stop_crossed", lv["stop"]))
        if lv.get("target") is not None and ((bar["h"] >= lv["target"]) if long else (bar["l"] <= lv["target"])):
            hits.append(("target_crossed", lv["target"]))
        ts = lv.get("timeout_session")
        if ts is not None and session >= ts.date():
            hits.append(("timeout_due", None))
        for kind, level in hits:
            doc = {"type": kind, "account_id": lv["account_id"], "symbol": lv["symbol"], "side": lv["side"],
                   "level": level, "levels_id": lv["_id"], "price_session": session.isoformat(),
                   "low": bar["l"], "high": bar["h"], "close": bar["c"], "created_at": now,
                   "dedupe_key": f"{kind}:{lv['_id']}", "acknowledged": False,
                   "message": _message(kind, lv, bar, session)}
            try:
                db.notifications.insert_one(doc)
                created.append(doc)
            except DuplicateKeyError:
                pass
    return created


def _message(kind: str, lv: dict, bar: dict, session) -> str:
    s, side = lv["symbol"], lv["side"]
    if kind == "stop_crossed":
        return (f"{s} {side}: traded through your stop {lv['stop']:.2f} on {session} (range {bar['l']:.2f}–"
                f"{bar['h']:.2f}, close {bar['c']:.2f}). Check that the stop order filled.")
    if kind == "target_crossed":
        return (f"{s} {side}: reached your target {lv['target']:.2f} on {session} (range {bar['l']:.2f}–"
                f"{bar['h']:.2f}). Check that the take-profit order filled.")
    return f"{s} {side}: the {TIMEOUT_SESSIONS}-session timeout is due; exit at the next open."
