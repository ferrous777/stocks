"""Order tickets, opportunity actions and protective alerts for real accounts (plan §E, §F).

* **Tickets** — only for rows whose strategy version is ``active`` *now* (rechecked at ticket time,
  not just when the outlook was built), only before the row's placement deadline, sized by the
  account's risk profile with the exact cent prices printed on the ticket. Written in Fidelity's
  terms: Buy / Sell Short, Limit, Day, place before the next open; after the fill, one OCO
  (one-cancels-the-other) GTC pair — the stop and the take-profit — plus the 126-session timeout.
* **Actions** — ``taken`` (with fills of that symbol in the entry direction) or ``skipped`` (with a
  reason). A taken action protects the position: stop, target, timeout.
* **Protection** — levels are stored with the session whose price basis they are expressed in;
  later splits are applied when comparing with raw bars, computing heat and displaying them.
  Levels can only be set on an existing holding of the same direction, and replacing them is
  serialized with the account lock in one transaction.
* **Protective alerts** — run by the tick for every protected holding, whatever the strategy's
  status: every newly stored bar since the last check (from the session the protection became
  effective) is examined in order; the timeout is due from the exchange calendar regardless of
  price data; missing price data is reported explicitly. Alerts are deduplicated.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
from bson import ObjectId
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from .. import sessions
from ..ingestion import load_splits
from ..research.protocol import load_universe
from ..strategies.indicators import atr as atr_of
from .risk import Book, RiskProfile, avg_dollar_volume, cluster_keys, correlation_clusters, size_ticket
from .service import AccountError, NotFound, _lock_account, account_outlook, get_account, holdings, ledger_state

TIMEOUT_SESSIONS = 126
ATR_PERIOD = 14
UTC = dt.timezone.utc


def get_risk_profile(db: Database, key: str | None) -> RiskProfile | None:
    if not key:
        return None
    doc = db.risk_profiles.find_one({"_id": key})
    return RiskProfile.from_doc(doc) if doc else None


def _d(x) -> dt.date:
    return x.date() if isinstance(x, dt.datetime) else x


def split_factor(splits, basis_session: dt.date, session: dt.date) -> float:
    """Price factor from ``basis_session``'s basis to ``session``'s (raw) basis: divide prices by it."""
    f = 1.0
    for sp in splits:
        if basis_session < sp.ex_date <= session:
            f *= sp.ratio
    return f


def levels_on(lv: dict, session: dt.date, splits) -> dict:
    f = split_factor(splits, _d(lv["basis_session"]), session)
    return {"stop": lv["stop"] / f, "target": None if lv.get("target") is None else lv["target"] / f}


def _current_atr(series, asof: dt.date) -> float | None:
    v = series.view_at(asof, lookback=ATR_PERIOD + 1)
    if len(v) < ATR_PERIOD + 1:
        return None
    a = atr_of(np.asarray(v.h), np.asarray(v.l), np.asarray(v.c), ATR_PERIOD)
    return float(a) if a and np.isfinite(a) else None


def build_tickets(db: Database, account_id: str, now: dt.datetime) -> dict:
    acc = get_account(db, account_id)
    o = account_outlook(db, account_id, now)
    h = holdings(db, account_id, now)
    profile = get_risk_profile(db, acc.get("risk_profile"))
    out = {"account_id": account_id, "asof": o["asof"], "risk_profile": profile.key if profile else None,
           "tickets": [], "withheld": [], "informational_rows": sum(1 for r in o["rows"] if r["grade"] in ("B", "C"))}
    statuses = {v["_id"]: v.get("status", "research") for v in db.strategy_versions.find()}
    eligible = []
    for r in o["rows"]:
        if r["grade"] != "A" or r.get("kind") != "new" or not r.get("plan"):
            continue
        key = r["source"].removeprefix("signal:")
        if statuses.get(key) != "active":   # status can change after the outlook was built (e.g. a pause)
            out["withheld"].append({"symbol": r["symbol"], "side": r["side"],
                                    "reason": f"strategy {key} is {statuses.get(key, 'unregistered')}, not active"})
            continue
        deadline = dt.datetime.fromisoformat(r["placeable_until"])
        if now >= deadline:
            out["withheld"].append({"symbol": r["symbol"], "side": r["side"],
                                    "reason": f"placement window closed at {deadline.isoformat()}"})
            continue
        eligible.append(r)
    if not eligible:
        out.setdefault("note", "No row is backed by an active (validated) strategy version within its placement "
                               "window, so no tickets or quantities are produced. Rows graded B or C are "
                               "informational only.")
        return out
    if profile is None:
        out["withheld"] += [{"symbol": r["symbol"], "side": r["side"], "reason": "account has no risk profile"}
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
    marks = {p["symbol"]: (p["mark"], p["mark_session"]) for p in h["positions"]}
    for lv in db.position_levels.find({"account_id": account_id, "active": True}):
        sym, q = lv["symbol"], st.qty(lv["symbol"])
        if not q or sym not in marks or marks[sym][0] is None:
            continue
        series = uni.get(sym)
        a = _current_atr(series, series.sessions[-1]) if series is not None and series.sessions else None
        if a is None:
            raise AccountError(f"cannot compute ATR for held {sym}; portfolio heat (gap stress) is unknown")
        mark_session = dt.date.fromisoformat(marks[sym][1])
        stop = levels_on(lv, mark_session, load_splits(db, sym))["stop"]
        book.heat += abs(q) * (abs(marks[sym][0] - stop) + profile.gap_stress_atr * a)
    for r in sorted(eligible, key=lambda r: -(r.get("exp_return_6m") or -1e9)):
        sym = r["symbol"]
        qty, reasons, _ = size_ticket(r, book, profile, keys=cluster_keys(sym, groups, corr),
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
    exit_action = "Sell" if long else "Buy to Cover"
    t = {
        "symbol": r["symbol"], "action": "Buy" if long else "Sell Short", "order_type": "Limit",
        "limit_price": entry, "quantity": qty, "time_in_force": "Day",
        "place_before": r["placeable_until"], "valid_until": r["valid_until"],
        "after_fill": {
            "type": "OCO", "time_in_force": "Good 'til Canceled",
            "instruction": "Enter both exits as one OCO (one-cancels-the-other) order so that when one fills the "
                           "other is cancelled.",
            "legs": [
                {"action": exit_action, "order_type": "Stop", "stop_price": stop, "quantity": qty},
                {"action": exit_action, "order_type": "Limit", "limit_price": target, "quantity": qty},
            ],
        },
        "timeout": f"If neither exit has filled after {TIMEOUT_SESSIONS} sessions, cancel the OCO and exit at the "
                   "next open.",
        "estimated_cost": notional, "max_loss_at_stop_with_gap": loss,
        "expected_profit_6m_vs_cash": notional * r["exp_excess_6m"],
        "expected_return_6m": r["exp_return_6m"], "grade": r["grade"], "source": r["source"],
        "sizing": reasons, "outlook_asof": o["asof"], "notes": [],
    }
    if not long:
        t["notes"].append("Confirm borrow availability and the borrow rate with Fidelity before placing.")
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
        entry_side = "buy" if side == "long" else "short"
        wrong = [f["exec_id"] for f in fills if f["symbol"] != symbol or f["side"] != entry_side]
        if wrong:
            raise AccountError(f"fills {wrong} are not {entry_side} fills of {symbol}")
        plan = row.get("plan") or {}
        stop = stop if stop is not None else plan.get("stop")
        target = target if target is not None else plan.get("target")
        if stop is None:
            raise AccountError("a stop is required to protect a taken position")
        first = min(f["ts"] for f in fills)
        first = first if first.tzinfo else first.replace(tzinfo=UTC)
        fill_session = sessions.exchange_date(first)
        if not sessions.is_session(fill_session):
            fill_session = sessions.next_session(fill_session)
        set_levels(db, account_id, symbol=symbol, side=side, stop=stop, target=target,
                   basis_session=dt.date.fromisoformat(outlook_asof),  # plan prices are on the decision basis
                   effective_session=fill_session,
                   timeout_session=sessions.session_after_n(fill_session, TIMEOUT_SESSIONS),
                   source=f"action:{doc['_id']}", now=now)
    db.opportunity_actions.insert_one(doc)
    return doc


def _latest_session(db: Database, symbol: str) -> dt.date | None:
    b = db.bars.find_one({"symbol": symbol, "interval": "1d"}, {"session": 1}, sort=[("session", -1)])
    return b["session"].date() if b else None


def set_levels(db: Database, account_id: str, *, symbol: str, side: str, stop: float, target: float | None,
               now: dt.datetime, source: str, basis_session: dt.date | None = None,
               effective_session: dt.date | None = None, timeout_session: dt.date | None = None) -> dict:
    """Protective levels for an existing holding of the same direction (replaces its active levels).

    Prices are on ``basis_session``'s basis (default: the latest stored session, i.e. today's prices).
    Protection is checked from ``effective_session`` (default: the first session after now's close).
    """
    long = side == "long"
    if target is not None and (target <= stop if long else target >= stop):
        raise AccountError("target must be on the profit side of the stop (long: target > stop)")
    basis_session = basis_session or _latest_session(db, symbol)
    if basis_session is None:
        raise AccountError(f"{symbol} has no price history; cannot place levels on a price basis")
    if effective_session is None:
        today = sessions.exchange_date(now)
        effective_session = today if sessions.is_session(today) and now < sessions.session_bounds(today)[1] \
            else sessions.next_session(today)
    doc = {"_id": ObjectId(), "account_id": account_id, "symbol": symbol, "side": side, "stop": stop,
           "target": target, "active": True, "source": source, "created_at": now,
           "basis_session": dt.datetime.combine(basis_session, dt.time(), UTC),
           "effective_session": dt.datetime.combine(effective_session, dt.time(), UTC),
           "checked_through": None,
           "timeout_session": dt.datetime.combine(timeout_session, dt.time(), UTC) if timeout_session else None}

    def txn(session):
        _lock_account(db, account_id, session)
        q = ledger_state(db, account_id, now, session).qty(symbol)
        if not q or (q > 0) != long:
            held = "no position" if not q else f"a {'long' if q > 0 else 'short'} position of {q:g}"
            raise AccountError(f"cannot protect a {side} in {symbol}: the account holds {held}")
        db.position_levels.update_many({"account_id": account_id, "symbol": symbol, "active": True},
                                       {"$set": {"active": False, "replaced_at": now}}, session=session)
        db.position_levels.insert_one(doc, session=session)

    with db.client.start_session() as s:
        s.with_transaction(txn)
    return doc


PRICE_GRACE = dt.timedelta(hours=1)  # a session's bar is expected this long after its close


def last_completed_session(now: dt.datetime) -> dt.date:
    """Most recent session whose close (plus a grace period for ingestion) is before ``now``."""
    d = sessions.exchange_date(now)
    for _ in range(15):
        if sessions.is_session(d) and now >= sessions.session_bounds(d)[1] + PRICE_GRACE:
            return d
        d -= dt.timedelta(days=1)
    raise RuntimeError(f"no completed session in the 15 days before {now}")


def _notify(db: Database, doc: dict, created: list) -> None:
    try:
        db.notifications.insert_one(doc)
        created.append(doc)
    except DuplicateKeyError:
        pass


def check_protective(db: Database, now: dt.datetime) -> list[dict]:
    """Alerts for every protected holding (independent of strategy status). Returns new alerts."""
    created: list[dict] = []
    for lv in db.position_levels.find({"active": True}):
        sym, long = lv["symbol"], lv["side"] == "long"
        q = ledger_state(db, lv["account_id"], now).qty(sym)
        if not q or (q > 0) != long:
            db.position_levels.update_one({"_id": lv["_id"]}, {"$set": {"active": False, "closed_at": now}})
            continue
        base = {"account_id": lv["account_id"], "symbol": sym, "side": lv["side"], "levels_id": lv["_id"],
                "created_at": now, "acknowledged": False}
        # Timeout: from the exchange calendar, independent of price data.
        ts = lv.get("timeout_session")
        if ts is not None and now >= sessions.session_bounds(ts.date())[1]:
            _notify(db, {**base, "type": "timeout_due", "dedupe_key": f"timeout_due:{lv['_id']}",
                         "message": f"{sym} {lv['side']}: the {TIMEOUT_SESSIONS}-session timeout ended at the "
                                    f"{ts.date()} close; exit at the next open."}, created)
        # Every newly stored bar since the last check, from the session protection became effective.
        start = max(lv["effective_session"], lv["checked_through"] + dt.timedelta(days=1)) \
            if lv.get("checked_through") else lv["effective_session"]
        bars = list(db.bars.find({"symbol": sym, "interval": "1d", "session": {"$gte": start}}).sort("session", 1))
        splits = load_splits(db, sym)
        for bar in bars:
            session = bar["session"].date()
            lvl = levels_on(lv, session, splits)
            hits = []
            if (bar["l"] <= lvl["stop"]) if long else (bar["h"] >= lvl["stop"]):
                hits.append(("stop_crossed", lvl["stop"]))
            if lvl["target"] is not None and ((bar["h"] >= lvl["target"]) if long else (bar["l"] <= lvl["target"])):
                hits.append(("target_crossed", lvl["target"]))
            for kind, level in hits:
                _notify(db, {**base, "type": kind, "level": level, "price_session": session.isoformat(),
                             "low": bar["l"], "high": bar["h"], "close": bar["c"], "dedupe_key": f"{kind}:{lv['_id']}",
                             "message": _message(kind, sym, lv["side"], level, bar, session)}, created)
        if bars:
            db.position_levels.update_one({"_id": lv["_id"]}, {"$set": {"checked_through": bars[-1]["session"]}})
        # Missing price data: the last completed session has no stored bar for this holding.
        last_done = last_completed_session(now)
        latest = _latest_session(db, sym)
        if last_done >= lv["effective_session"].date() and (latest is None or latest < last_done):
            _notify(db, {**base, "type": "price_data_missing", "dedupe_key": f"price_data_missing:{lv['_id']}:{last_done}",
                         "message": f"{sym}: no price for the {last_done} session yet (latest {latest or 'none'}); "
                                    "stop and target could not be checked."}, created)
    return created


def _message(kind: str, sym: str, side: str, level: float, bar: dict, session) -> str:
    if kind == "stop_crossed":
        return (f"{sym} {side}: traded through your stop {level:.2f} on {session} (range {bar['l']:.2f}–"
                f"{bar['h']:.2f}, close {bar['c']:.2f}). Check that the stop order filled.")
    return (f"{sym} {side}: reached your target {level:.2f} on {session} (range {bar['l']:.2f}–{bar['h']:.2f}). "
            "Check that the take-profit order filled.")
