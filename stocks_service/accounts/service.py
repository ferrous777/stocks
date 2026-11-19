"""Real accounts in MongoDB: opening balances, snapshots, executions, reconciliation (plan §3).

* The first snapshot of an account with no history writes ``opening_balance`` ledger events
  (positions with their cost basis, and cash) — explicit non-trade events, so no breaks.
* Every later snapshot is reconciled against the ledger **as of its ``as_of``**; each
  difference becomes a ``reconciliation_breaks`` row. Snapshots never create trades.
* Confirmed fills (``executions``) are deduplicated by broker exec id (or a content hash); a fill
  at or before a snapshot's ``as_of`` re-reconciles that snapshot, resolving breaks it explains.
* A break is resolved manually by a transfer or adjustment, which writes the matching ledger
  event, so holdings always equal opening balances + executions + ledger events (+ splits).
* **Cash may be unknown.** A snapshot's ``cash`` (the core cash position) may be None — e.g. a
  Plaid feed exposes "available to withdraw" and total value, but no core cash. Unknown is never
  zero: it is not compared, and the account's cash only becomes known from the first snapshot that
  reports it (an opening balance, or a ``cash_baseline`` ledger event anchoring the ledger's cash at
  that snapshot). Valuations that need cash say they are incomplete instead of guessing.
* **Feed delays.** A difference fully explained by fills recorded in the ``FEED_DELAY`` before the
  snapshot (trades the source has not reflected yet) is a ``pending`` break, not an ``open`` one;
  it resolves itself when a later snapshot matches.
* Each snapshot keeps the institution's timestamp (``institution_as_of``, None when unknown)
  separately from when it was retrieved; reconciliation uses the institution's time when known,
  else the retrieval time (``time_basis`` says which).
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

FEED_DELAY = dt.timedelta(days=5)   # settlement (T+1) plus a weekend and a slow feed
UNRESOLVED = ("open", "pending")
CASH_KINDS = ("opening_balance", "cash_baseline")


def cash_known_since(db: Database, account_id: str, session=None) -> dt.datetime | None:
    """When the account's cash became known: its first cash opening balance or cash baseline."""
    ev = db.ledger_events.find_one({"account_id": account_id, "symbol": None, "kind": {"$in": list(CASH_KINDS)}},
                                   sort=[("ts", 1)], session=session)
    return _from_db(ev["ts"]) if ev else None


def _snapshot_cash(snap: dict) -> float | None:
    """The snapshot's core cash, or None when it was not reported (older snapshots always reported it)."""
    return snap.get("cash") if snap.get("cash_known", True) else None


def _recent_fills(db: Database, account_id: str, as_of: dt.datetime, session) -> tuple[dict[str, float], float]:
    """Signed share change per symbol and the cash change of fills in (as_of - FEED_DELAY, as_of]."""
    from .ledger import SIDES
    qty: dict[str, float] = {}
    cash = 0.0
    for x in db.executions.find({"account_id": account_id, "ts": {"$gt": as_of - FEED_DELAY, "$lte": as_of}},
                                session=session):
        sign = SIDES[x["side"]]
        qty[x["symbol"]] = qty.get(x["symbol"], 0.0) + sign * x["qty"]
        cash += -sign * x["qty"] * x["price"] - x.get("fees", 0.0)
    return qty, cash


def _reconcile_snapshot(db: Database, snap: dict, now: dt.datetime, session, resolved_by: str) -> list[dict]:
    as_of = _from_db(snap["as_of"])
    state = ledger_state(db, snap["account_id"], as_of, session)
    reported = {p["symbol"]: p["qty"] for p in snap["positions"]}
    since = cash_known_since(db, snap["account_id"], session)
    cash = _snapshot_cash(snap) if since is not None and since <= as_of else None   # unknown cash is not compared
    diffs = {d.symbol: d for d in reconcile(state, cash, reported)}
    recent_qty, recent_cash = _recent_fills(db, snap["account_id"], as_of, session)
    for d in diffs.values():
        recent = recent_cash if d.symbol == CASH else recent_qty.get(d.symbol, 0.0)
        tol = 0.005 if d.symbol == CASH else QTY_TOL
        lagging = abs(recent) > tol and abs((d.expected - recent) - d.reported) <= tol
        extra = ({"status": "pending", "reason": "recent fills not reflected by the source yet (settlement or feed "
                  "delay); resolves when a later snapshot includes them", "pending_fills": recent}
                 if lagging else {"status": "open"})
        db.reconciliation_breaks.update_one(
            {"snapshot_id": snap["_id"], "symbol": d.symbol},
            {"$set": {"account_id": snap["account_id"], "as_of": snap["as_of"], "expected": d.expected,
                      "reported": d.reported, "diff": d.diff, "updated_at": now, **extra},
             "$unset": {"resolution": "", **({} if lagging else {"reason": "", "pending_fills": ""})},
             "$setOnInsert": {"created_at": now}},
            upsert=True, session=session)
    db.reconciliation_breaks.update_many(
        {"snapshot_id": snap["_id"], "status": {"$in": list(UNRESOLVED)}, "symbol": {"$nin": list(diffs)}},
        {"$set": {"status": "resolved", "diff": 0.0, "updated_at": now, "resolution": {"type": resolved_by, "at": now}}},
        session=session)
    return list(db.reconciliation_breaks.find({"snapshot_id": snap["_id"]}, session=session).sort("symbol", 1))


def upload_snapshot(db: Database, account_id: str, *, as_of: dt.datetime | None, cash: float | None,
                    positions: list[dict], opening: bool, now: dt.datetime, retrieved_at: dt.datetime | None = None,
                    source: str | None = None, cash_as_of: dt.datetime | None = None,
                    available_to_withdraw: float | None = None) -> dict:
    """Store a broker snapshot. ``as_of`` is the institution's timestamp (None when unknown);
    ``retrieved_at`` when it was pulled from the source (default: now). ``cash`` None = unknown core
    cash (never zero). ``available_to_withdraw`` is stored as reported, with its meaning; it is not cash."""
    retrieved = _utc(retrieved_at) if retrieved_at is not None else now
    inst = _utc(as_of) if as_of is not None else None
    effective = inst or retrieved
    if cash is not None:
        _finite("cash", cash)
    if available_to_withdraw is not None:
        _finite("available_to_withdraw", available_to_withdraw)
    for p in positions:
        _finite(f"{p['symbol']} qty", p["qty"])
        for k in ("avg_cost", "institution_price", "institution_value"):
            _finite(f"{p['symbol']} {k}", p.get(k))
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
        snap = {"_id": ObjectId(), "account_id": account_id, "as_of": effective, "uploaded_at": now,
                "institution_as_of": inst, "retrieved_at": retrieved, "time_basis": "institution" if inst else "retrieval",
                "source": source, "cash": cash, "cash_known": cash is not None,
                "cash_as_of": _utc(cash_as_of) if cash_as_of is not None else None,
                "available_to_withdraw": None if available_to_withdraw is None else {
                    "amount": available_to_withdraw, "source": source,
                    "meaning": "cash available to withdraw as reported by the source; not core cash, settled cash "
                               "or buying power"},
                "positions": positions, "opening": is_opening}
        db.portfolio_snapshots.insert_one(snap, session=session)
        ref = str(snap["_id"])
        if is_opening:
            events = ([{"account_id": account_id, "ts": effective, "kind": "opening_balance", "symbol": None,
                        "amount": cash, "ref": f"{ref}:{CASH}"}] if cash is not None else [])
            events += [{"account_id": account_id, "ts": effective, "kind": "opening_balance", "symbol": p["symbol"],
                        "qty": p["qty"], "cost_basis": p["qty"] * p["avg_cost"], "ref": f"{ref}:{p['symbol']}"}
                       for p in positions if abs(p["qty"]) > QTY_TOL]
            if events:
                db.ledger_events.insert_many(events, session=session)
            breaks = []
        else:
            if cash is not None and cash_known_since(db, account_id, session) is None:
                # First reported cash: anchor the ledger's cash here (flows recorded earlier are kept).
                held = ledger_state(db, account_id, effective, session).cash
                db.ledger_events.insert_one({"account_id": account_id, "ts": effective, "kind": "cash_baseline",
                                             "symbol": None, "amount": cash - held, "ref": f"{ref}:{CASH}",
                                             "reason": "first snapshot that reported core cash"}, session=session)
            breaks = _reconcile_snapshot(db, snap, now, session, resolved_by="none")
            # A later snapshot that matches catches up earlier pending (feed-delayed) differences.
            still = {b["symbol"] for b in breaks if b["status"] in UNRESOLVED} | ({CASH} if cash is None else set())
            db.reconciliation_breaks.update_many(
                {"account_id": account_id, "status": "pending", "symbol": {"$nin": sorted(still)},
                 "as_of": {"$lte": effective}, "snapshot_id": {"$ne": snap["_id"]}},
                {"$set": {"status": "resolved", "updated_at": now,
                          "resolution": {"type": "caught_up", "at": now, "snapshot_id": snap["_id"]}}},
                session=session)
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
        if db.accounts.find_one({"_id": account_id}, {"kind": 1}, session=session).get("kind") == "paper":
            raise AccountError("paper accounts only get fills from the simulator; manual executions are refused")
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
        if br["status"] not in UNRESOLVED:
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
    pending_breaks = db.reconciliation_breaks.count_documents({"account_id": account_id, "status": "pending"})
    # Cash: known from the ledger only once some snapshot reported it, and current only if the latest
    # snapshot reported it too; otherwise the last report is shown as history, never as today's cash.
    known_since = cash_known_since(db, account_id)
    last_cash_snap = db.portfolio_snapshots.find_one(
        {"account_id": account_id, "$or": [{"cash_known": True}, {"cash_known": {"$exists": False}}]},
        sort=[("as_of", -1)])
    last_reported = ({"amount": last_cash_snap["cash"], "as_of": last_cash_snap["as_of"],
                      "cash_as_of": last_cash_snap.get("cash_as_of"), "source": last_cash_snap.get("source")}
                     if last_cash_snap else None)
    if known_since is None:
        cash, cash_status = None, "unknown"
    elif latest is not None and _snapshot_cash(latest) is None:
        cash, cash_status = None, "historical"
    else:
        cash, cash_status = st.cash, "reported"
    positions_value = long_mv + short_mv if not unmarked else None
    missing = ([f"core cash ({cash_status})"] if cash is None else []) + ([f"prices for {unmarked}"] if unmarked else [])
    atw = next((s_["available_to_withdraw"] | {"as_of": s_["as_of"]} for s_ in db.portfolio_snapshots.find(
        {"account_id": account_id, "available_to_withdraw": {"$ne": None}}).sort("as_of", -1).limit(1)), None)
    return {
        "account_id": account_id, "as_of": now, "cash": cash, "cash_status": cash_status,
        "last_reported_cash": last_reported, "available_to_withdraw": atw,
        "positions": rows, "closed": closed,
        "long_market_value": long_mv, "short_market_value": short_mv, "positions_value": positions_value,
        "equity": cash + positions_value if cash is not None and positions_value is not None else None,
        "valuation": {"complete": not missing, "missing": missing},
        "unmarked": unmarked, "realized": sum(h.realized for h in st.holdings.values()),
        "latest_snapshot": latest["as_of"] if latest else None,
        "latest_snapshot_info": None if latest is None else {
            "as_of": latest["as_of"], "time_basis": latest.get("time_basis", "institution"),
            "institution_as_of": latest.get("institution_as_of", latest["as_of"]),
            "retrieved_at": latest.get("retrieved_at", latest.get("uploaded_at")), "source": latest.get("source"),
            "cash_known": latest.get("cash_known", True)},
        "open_breaks": open_breaks, "pending_breaks": pending_breaks,
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
