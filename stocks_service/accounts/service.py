"""Real accounts in MongoDB: opening balances, snapshots, executions, reconciliation (plan §3).

* The first snapshot of an account with no history writes ``opening_balance`` ledger events
  (positions with their cost basis, and cash) — explicit non-trade events, so no breaks.
* Every later snapshot is reconciled against the ledger **as of its ``as_of``**; each
  difference becomes a ``reconciliation_breaks`` row. Snapshots never create trades.
* Confirmed fills (``executions``) are deduplicated by broker exec id (or a content hash); a fill
  at or before a snapshot's ``as_of`` re-reconciles that snapshot, resolving breaks it explains.
* A break is resolved manually by a transfer or adjustment, which writes the matching ledger
  event, so holdings always equal opening balances + executions + ledger events (+ splits).
Every write that changes an account runs in one transaction.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import math

from bson import ObjectId
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from ..ingestion import load_splits
from .ledger import CASH, QTY_TOL, Execution, LedgerEvent, LedgerState, reconcile, split_time, state_as_of

UTC = dt.timezone.utc


class AccountError(ValueError):
    """Invalid request against an account (maps to HTTP 409/422)."""


class NotFound(LookupError):
    pass


def _utc(t: dt.datetime) -> dt.datetime:
    if t.tzinfo is None:
        raise AccountError("timestamps must include a timezone (e.g. 2026-11-17T21:00:00Z)")
    return t.astimezone(UTC)


def _finite(name: str, v) -> None:
    if v is not None and not math.isfinite(v):
        raise AccountError(f"{name} must be a finite number")


def _lock_account(db: Database, account_id: str, session) -> None:
    """Write the account document first in every mutating transaction, so concurrent mutations of the
    same account conflict and the loser retries against committed state (no double opening balances)."""
    res = db.accounts.update_one({"_id": account_id}, {"$inc": {"ledger_version": 1}}, session=session)
    if res.matched_count == 0:
        raise NotFound(f"account {account_id} not found")


def _reconcile_after(db: Database, account_id: str, ts: dt.datetime, now: dt.datetime, session, resolved_by: str) -> int:
    """Re-reconcile every non-opening snapshot at or after ``ts`` (history before them changed)."""
    n = 0
    for snap in db.portfolio_snapshots.find({"account_id": account_id, "opening": False, "as_of": {"$gte": ts}},
                                            session=session):
        _reconcile_snapshot(db, snap, now, session, resolved_by=resolved_by)
        n += 1
    return n


def _from_db(t: dt.datetime) -> dt.datetime:
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def get_account(db: Database, account_id: str, session=None) -> dict:
    acc = db.accounts.find_one({"_id": account_id}, session=session)
    if acc is None:
        raise NotFound(f"account {account_id} not found")
    return acc


def create_account(db: Database, *, account_id: str, name: str, now: dt.datetime) -> dict:
    doc = {"_id": account_id, "name": name, "kind": "real", "created_at": now}
    try:
        db.accounts.insert_one(doc)
    except DuplicateKeyError:
        raise AccountError(f"account {account_id} already exists")
    return doc


# --- history -----------------------------------------------------------------------------

def _history(db: Database, account_id: str, session=None):
    events = [LedgerEvent(_from_db(e["ts"]), e["kind"], e.get("symbol"), e.get("qty", 0.0), e.get("cost_basis", 0.0),
                          e.get("amount", 0.0))
              for e in db.ledger_events.find({"account_id": account_id}, session=session)]
    execs = [Execution(_from_db(x["ts"]), x["symbol"], x["side"], x["qty"], x["price"], x.get("fees", 0.0))
             for x in db.executions.find({"account_id": account_id}, session=session)]
    symbols = {e.symbol for e in events if e.symbol} | {x.symbol for x in execs}
    splits = {s: [(sp.ex_date, sp.ratio) for sp in load_splits(db, s, session=session)] for s in symbols}
    return events, execs, splits


def ledger_state(db: Database, account_id: str, as_of: dt.datetime, session=None) -> LedgerState:
    events, execs, splits = _history(db, account_id, session)
    return state_as_of(as_of, events, execs, splits)


def _has_history(db: Database, account_id: str, session=None) -> bool:
    return bool(db.ledger_events.find_one({"account_id": account_id}, session=session)
                or db.executions.find_one({"account_id": account_id}, session=session))


# --- reconciliation ------------------------------------------------------------------------

def _reconcile_snapshot(db: Database, snap: dict, now: dt.datetime, session, resolved_by: str) -> list[dict]:
    state = ledger_state(db, snap["account_id"], _from_db(snap["as_of"]), session)
    reported = {p["symbol"]: p["qty"] for p in snap["positions"]}
    diffs = {d.symbol: d for d in reconcile(state, snap["cash"], reported)}
    for d in diffs.values():
        db.reconciliation_breaks.update_one(
            {"snapshot_id": snap["_id"], "symbol": d.symbol},
            {"$set": {"account_id": snap["account_id"], "as_of": snap["as_of"], "expected": d.expected,
                      "reported": d.reported, "diff": d.diff, "status": "open", "updated_at": now},
             "$unset": {"resolution": ""}, "$setOnInsert": {"created_at": now}},
            upsert=True, session=session)
    db.reconciliation_breaks.update_many(
        {"snapshot_id": snap["_id"], "status": "open", "symbol": {"$nin": list(diffs)}},
        {"$set": {"status": "resolved", "diff": 0.0, "updated_at": now, "resolution": {"type": resolved_by, "at": now}}},
        session=session)
    return list(db.reconciliation_breaks.find({"snapshot_id": snap["_id"]}, session=session).sort("symbol", 1))


def upload_snapshot(db: Database, account_id: str, *, as_of: dt.datetime, cash: float, positions: list[dict],
                    opening: bool, now: dt.datetime) -> dict:
    as_of = _utc(as_of)
    _finite("cash", cash)
    for p in positions:
        _finite(f"{p['symbol']} qty", p["qty"])
        _finite(f"{p['symbol']} avg_cost", p.get("avg_cost"))
    syms = [p["symbol"] for p in positions]
    if len(set(syms)) != len(syms):
        raise AccountError("each symbol may appear once per snapshot (net the lots)")
    out: dict = {}

    def txn(session):
        _lock_account(db, account_id, session)
        history = _has_history(db, account_id, session)
        is_opening = opening or not history
        if is_opening and history:
            raise AccountError("this account already has history; only its first snapshot can be the opening balance")
        if is_opening:
            missing = [p["symbol"] for p in positions if p.get("avg_cost") is None]
            if missing:
                raise AccountError(f"the opening snapshot needs avg_cost for every position (missing: {missing})")
        snap = {"_id": ObjectId(), "account_id": account_id, "as_of": as_of, "uploaded_at": now, "cash": cash,
                "positions": positions, "opening": is_opening}
        db.portfolio_snapshots.insert_one(snap, session=session)
        if is_opening:
            ref = str(snap["_id"])
            events = [{"account_id": account_id, "ts": as_of, "kind": "opening_balance", "symbol": None,
                       "amount": cash, "ref": f"{ref}:{CASH}"}]
            events += [{"account_id": account_id, "ts": as_of, "kind": "opening_balance", "symbol": p["symbol"],
                        "qty": p["qty"], "cost_basis": p["qty"] * p["avg_cost"], "ref": f"{ref}:{p['symbol']}"}
                       for p in positions if abs(p["qty"]) > QTY_TOL]
            db.ledger_events.insert_many(events, session=session)
            breaks = []
        else:
            breaks = _reconcile_snapshot(db, snap, now, session, resolved_by="none")
        out.update(snapshot=snap, breaks=breaks)

    with db.client.start_session() as s:
        s.with_transaction(txn)
    return out


def _exec_id(x: dict) -> str:
    if x.get("exec_id"):
        return str(x["exec_id"])
    key = (f"{x['symbol']}|{x['side']}|{x['qty']!r}|{x['price']!r}|{x.get('fees', 0.0)!r}|"
           f"{_utc(x['ts']).isoformat()}")
    return "h:" + hashlib.sha256(key.encode()).hexdigest()[:32]


def _legacy_exec_id(x: dict) -> str | None:
    """Fallback id used before fees were part of the hash (PR #21). Matched only together with equal fees."""
    if x.get("exec_id"):
        return None
    key = f"{x['symbol']}|{x['side']}|{x['qty']!r}|{x['price']!r}|{_utc(x['ts']).isoformat()}"
    return "h:" + hashlib.sha256(key.encode()).hexdigest()[:32]


def add_executions(db: Database, account_id: str, items: list[dict], *, now: dt.datetime) -> dict:
    out = {"inserted": 0, "duplicates": 0, "reconciled_snapshots": 0}

    def txn(session):
        out.update(inserted=0, duplicates=0, reconciled_snapshots=0)
        _lock_account(db, account_id, session)
        opening = db.portfolio_snapshots.find_one({"account_id": account_id, "opening": True}, session=session)
        earliest = None
        for x in items:
            ts = _utc(x["ts"])
            Execution(ts, x["symbol"], x["side"], x["qty"], x["price"], x.get("fees", 0.0))  # validates
            if opening and ts <= _from_db(opening["as_of"]):
                raise AccountError(f"execution at {ts.isoformat()} is not after the opening balance "
                                   f"({_from_db(opening['as_of']).isoformat()}), which already includes it")
            doc = {"account_id": account_id, "exec_id": _exec_id(x), "symbol": x["symbol"], "side": x["side"],
                   "qty": x["qty"], "price": x["price"], "fees": x.get("fees", 0.0), "ts": ts,
                   "source": x.get("source", "manual"), "recorded_at": now}
            legacy = _legacy_exec_id(x)
            dup = db.executions.find_one({"account_id": account_id, "exec_id": doc["exec_id"]}, session=session) or (
                legacy and db.executions.find_one({"account_id": account_id, "exec_id": legacy, "fees": doc["fees"]},
                                                  session=session))
            if dup:
                out["duplicates"] += 1
                continue
            db.executions.insert_one(doc, session=session)
            out["inserted"] += 1
            earliest = ts if earliest is None or ts < earliest else earliest
        if earliest is not None:
            out["reconciled_snapshots"] = _reconcile_after(db, account_id, earliest, now, session, "executions")

    with db.client.start_session() as s:
        s.with_transaction(txn)
    return out


RESOLUTION_KINDS = ("transfer_in", "transfer_out", "manual_adjustment")


def resolve_break(db: Database, break_id: str, *, kind: str, note: str, now: dt.datetime,
                  cost_basis: float | None = None) -> dict:
    """Resolve a break by recording the non-trade change that explains it (writes a ledger event)."""
    if kind not in RESOLUTION_KINDS:
        raise AccountError(f"kind must be one of {RESOLUTION_KINDS}")
    out: dict = {}

    def txn(session):
        try:
            br = db.reconciliation_breaks.find_one({"_id": ObjectId(break_id)}, session=session)
        except Exception:
            br = None
        if br is None:
            raise NotFound("break not found")
        _lock_account(db, br["account_id"], session)
        br = db.reconciliation_breaks.find_one({"_id": br["_id"]}, session=session)  # re-read under the lock
        if br["status"] != "open":
            raise AccountError("break is already resolved")
        snap = db.portfolio_snapshots.find_one({"_id": br["snapshot_id"]}, session=session)
        diff = br["diff"]
        if kind == "transfer_in" and diff < 0 or kind == "transfer_out" and diff > 0:
            raise AccountError(f"{kind} does not match a difference of {diff:+g}")
        ev = {"account_id": br["account_id"], "ts": _from_db(snap["as_of"]), "kind": kind,
              "ref": f"break:{break_id}:{ObjectId()}", "break_id": br["_id"], "reason": note, "created_at": now}
        if br["symbol"] == CASH:
            ev.update(symbol=None, amount=diff)
        else:
            exp = br["expected"]
            if abs(exp) > QTY_TOL and (exp > 0) != (exp + diff > 0) and abs(exp + diff) > QTY_TOL:
                raise AccountError("this difference flips the position through zero; record it as two adjustments")
            adding = (exp >= 0 and diff > 0) or (exp <= 0 and diff < 0)
            basis = cost_basis
            if adding and basis is not None and (not math.isfinite(basis) or basis == 0 or (basis > 0) != (diff > 0)):
                raise AccountError("cost_basis must be a finite, non-zero total with the same sign as the shares "
                                   f"coming in ({diff:+g})")
            if adding and basis is None:
                reported = {p["symbol"]: p for p in snap["positions"]}.get(br["symbol"], {})
                if reported.get("avg_cost") is None:
                    raise AccountError("cost_basis is required for shares coming in (the snapshot has no avg_cost)")
                basis = diff * reported["avg_cost"]
            ev.update(symbol=br["symbol"], qty=diff, cost_basis=basis if adding else 0.0)
        db.ledger_events.insert_one(ev, session=session)
        _reconcile_after(db, br["account_id"], ev["ts"], now, session, resolved_by=kind)
        breaks = list(db.reconciliation_breaks.find({"snapshot_id": snap["_id"]}, session=session).sort("symbol", 1))
        out.update(event=ev, breaks=breaks)

    with db.client.start_session() as s:
        s.with_transaction(txn)
    return out


# --- read models -------------------------------------------------------------------------

def _last_close(db: Database, symbol: str, now: dt.datetime) -> tuple[float, dt.date] | None:
    """Latest raw close, restated for splits effective by ``now`` (the ledger applies a split at the
    ex-date open, possibly before the first post-split close is stored)."""
    b = db.bars.find_one({"symbol": symbol, "interval": "1d"}, {"c": 1, "session": 1}, sort=[("session", -1)])
    if not b:
        return None
    session = b["session"].date()
    price = b["c"]
    for sp in load_splits(db, symbol):
        if sp.ex_date > session and split_time(sp.ex_date) <= now:
            price /= sp.ratio
    return price, session


def holdings(db: Database, account_id: str, now: dt.datetime) -> dict:
    get_account(db, account_id)
    st = ledger_state(db, account_id, now)
    rows, long_mv, short_mv = [], 0.0, 0.0
    for sym, h in sorted(st.open_positions().items()):
        mark = _last_close(db, sym, now)
        mv = h.qty * mark[0] if mark else None
        if mv is not None:
            long_mv += max(mv, 0.0)
            short_mv += min(mv, 0.0)
        rows.append({"symbol": sym, "qty": h.qty, "avg_cost": h.avg_cost, "cost_basis": h.basis,
                     "mark": mark[0] if mark else None, "mark_session": mark[1].isoformat() if mark else None,
                     "market_value": mv, "unrealized": (mv - h.basis) if mv is not None else None,
                     "realized": h.realized, "fees": h.fees})
    closed = [{"symbol": s, "realized": h.realized, "fees": h.fees} for s, h in sorted(st.holdings.items())
              if abs(h.qty) <= QTY_TOL and (h.realized or h.fees)]
    unmarked = [r["symbol"] for r in rows if r["mark"] is None]
    latest = db.portfolio_snapshots.find_one({"account_id": account_id}, sort=[("as_of", -1)])
    open_breaks = db.reconciliation_breaks.count_documents({"account_id": account_id, "status": "open"})
    return {
        "account_id": account_id, "as_of": now, "cash": st.cash, "positions": rows, "closed": closed,
        "long_market_value": long_mv, "short_market_value": short_mv,
        "equity": st.cash + long_mv + short_mv if not unmarked else None,
        "unmarked": unmarked, "realized": sum(h.realized for h in st.holdings.values()),
        "latest_snapshot": latest["as_of"] if latest else None, "open_breaks": open_breaks,
    }


def account_outlook(db: Database, account_id: str, now: dt.datetime) -> dict:
    """The latest market outlook, annotated with this account's positions (manage vs. new)."""
    from ..outlook.build import latest_outlook
    h = holdings(db, account_id, now)
    o = latest_outlook(db)
    if o is None:
        raise NotFound("no outlook yet; run POST /api/v1/outlook/run")
    held = {p["symbol"]: p for p in h["positions"]}
    for r in o["rows"]:
        p = held.get(r["symbol"])
        if p is None:
            r["kind"] = "new"
        else:
            same = (p["qty"] > 0) == (r["side"] == "long")
            r["kind"] = "manage_existing" if same else "opposes_holding"
            r["holding"] = {k: p[k] for k in ("qty", "avg_cost", "market_value", "unrealized")}
    o["account"] = {k: h[k] for k in ("account_id", "cash", "equity", "open_breaks", "latest_snapshot")}
    o["unrecognized_holdings"] = sorted(set(held) - {r["symbol"] for r in o["rows"]})
    return o
