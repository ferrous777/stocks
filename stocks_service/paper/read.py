"""Read models for accounts, shared by the website and the MCP tools: account summaries, performance,
and the transaction history (every fill and every non-trade ledger entry). Everything is computed
from stored executions, ledger events and the equity curve; nothing is estimated.
"""

from __future__ import annotations

import datetime as dt

from pymongo.database import Database

from ..research import stats
from . import report

UTC = dt.timezone.utc
BUY_SIDES = ("buy", "cover")


def kind_label(a: dict) -> str:
    if a.get("kind") != "paper":
        return "real account"
    if a.get("policy") == "agent":
        return "AI agent"
    if str(a.get("policy", "")).startswith("baseline"):
        return "baseline"
    if a.get("strategy"):
        return f"strategy {a['strategy']}"
    return a.get("policy", "")


def summary(db: Database, a: dict) -> dict:
    """Headline figures of a paper account (equity from its latest processed session)."""
    last = db.equity_curve.find_one({"account_id": a["_id"]}, sort=[("session", -1)])
    equity = last["equity"] if last else a["starting_cash"]
    return {
        "account_id": a["_id"], "name": a.get("name", a["_id"]), "kind": "paper", "trades_for": kind_label(a),
        "policy": a.get("policy"), "strategy": a.get("strategy"),
        "starting_cash": a["starting_cash"], "equity": equity, "return": equity / a["starting_cash"] - 1,
        "sessions": db.equity_curve.count_documents({"account_id": a["_id"]}),
        "open_orders": db.orders.count_documents({"account_id": a["_id"], "status": "open"}),
        "open_positions": db.orders.count_documents({"account_id": a["_id"], "status": "filled"}),
        "closed_orders": db.orders.count_documents({"account_id": a["_id"], "status": "closed"}),
        "processed_through": a["last_session_executed"].date().isoformat(),
        "stalled": a.get("stalled"),
        "created_at": a.get("created_at"),
    }


def summaries(db: Database) -> list[dict]:
    """Every paper account, best return first (ties, e.g. no sessions yet, by id)."""
    rows = [summary(db, a) for a in db.accounts.find({"kind": "paper"})]
    return sorted(rows, key=lambda r: (-r["return"], r["account_id"]))


def performance(db: Database, account_id: str, *, points: int | None = None) -> dict:
    """Equity curve, total return, max drawdown and closed-order statistics of a paper account.
    ``points`` keeps only the most recent points of the returned curve (the figures use all of it)."""
    acc = db.accounts.find_one({"_id": account_id})
    curve = [(e["session"].date(), e["equity"]) for e in db.equity_curve.find({"account_id": account_id}).sort("session", 1)]
    values = [acc["starting_cash"]] + [v for _, v in curve]
    dd, dd_len = stats.max_drawdown(values) if len(values) > 1 else (0.0, 0)
    closed = report._closed(db, account_id)
    wins = [r for r in closed if r > 0]
    out = {
        "account_id": account_id, "starting_cash": acc["starting_cash"], "sessions": len(curve),
        "first_session": curve[0][0].isoformat() if curve else None,
        "last_session": curve[-1][0].isoformat() if curve else None,
        "equity": values[-1], "total_return": values[-1] / values[0] - 1,
        "max_drawdown": dd, "longest_drawdown_sessions": dd_len,
        "closed_orders": len(closed),
        "win_rate": len(wins) / len(closed) if closed else None,
        "avg_net_return_per_order": sum(closed) / len(closed) if closed else None,
        "best_order": max(closed) if closed else None, "worst_order": min(closed) if closed else None,
        "curve": [{"session": d.isoformat(), "equity": v} for d, v in (curve[-points:] if points else curve)],
    }
    return out


def comparison(db: Database, acc: dict) -> dict | None:
    """The paired comparison with this account's baseline (None for a baseline account itself)."""
    if acc.get("kind") != "paper" or str(acc.get("policy", "")).startswith("baseline"):
        return None
    base, why = report.matching_baseline(db, acc)
    if base is None:
        return {"agent_account": acc["_id"], "baseline_account": None, "unavailable": why}
    return {**report.compare(db, acc["_id"], base), "pairing": why}


def _iso(t) -> str | None:
    if t is None:
        return None
    if isinstance(t, dt.datetime) and t.tzinfo is None:
        t = t.replace(tzinfo=UTC)
    return t.isoformat()


def _page_query(account_id: str, coll: str, cursor: tuple | None) -> dict:
    """Rows strictly after ``cursor`` in the order (ts desc, source desc, _id desc); sources are
    x = executions, s = splits, e = ledger events."""
    q: dict = {"account_id": account_id}
    if cursor is None:
        return q
    ts, c, oid = cursor
    same_ts = ({} if coll < c else {"_id": {"$lt": oid}} if coll == c else None)
    q["$or"] = [{"ts": {"$lt": ts}}] + ([{"ts": ts, **same_ts}] if same_ts is not None else [])
    return q


def _parse_cursor(cursor: str | None) -> tuple | None:
    if not cursor:
        return None
    from bson import ObjectId
    try:
        ts, c, oid = cursor.split("|")
        t = dt.datetime.fromisoformat(ts)
        return (t if t.tzinfo else t.replace(tzinfo=UTC)), c, ObjectId(oid)
    except Exception:
        raise ValueError("invalid cursor; pass the next_cursor value from the previous page")


def _split_rows(db: Database, account_id: str, now: dt.datetime) -> list[dict]:
    """Splits that changed this account's holdings. The ledger applies them from ``corporate_actions``
    at the ex-date's session open (before anything else at that instant), so they are not stored as
    ledger events; derive them the same way: shares held just before x (ratio - 1)."""
    from ..accounts.ledger import QTY_TOL, split_time, state_as_of
    from ..accounts.service import _history
    events, execs, splits = _history(db, account_id)
    rows = []
    for sym, ss in splits.items():
        for ex_date, ratio in ss:
            t = split_time(ex_date)
            if t > now:
                continue
            before = state_as_of(t - dt.timedelta(microseconds=1), events, execs, splits).qty(sym)
            if abs(before) <= QTY_TOL:
                continue
            ca = db.corporate_actions.find_one({"symbol": sym, "type": "split",
                                                "ex_date": dt.datetime.combine(ex_date, dt.time(), UTC)}, {"_id": 1})
            rows.append({"_key": (t, "s", ca["_id"]), "ts": t, "type": "split", "symbol": sym,
                         "qty": before * (ratio - 1), "price": None, "fees": None, "cash": None,
                         "ratio": ratio, "ex_date": ex_date.isoformat()})
    return rows


def transactions(db: Database, account_id: str, *, limit: int = 100, cursor: str | None = None,
                 now: dt.datetime | None = None) -> dict:
    """Fills, splits and ledger entries (opening balances, dividends, borrow fees, transfers, ...),
    newest first. ``cash`` is the entry's effect on cash (None for entries that move shares only).
    Page with ``cursor`` = the previous page's ``next_cursor``."""
    limit = max(1, min(limit, 500))
    cur = _parse_cursor(cursor)
    rows = [r for r in _split_rows(db, account_id, now or dt.datetime.now(UTC)) if cur is None or r["_key"] < cur]
    for x in db.executions.find(_page_query(account_id, "x", cur)).sort([("ts", -1), ("_id", -1)]).limit(limit + 1):
        sign = -1 if x["side"] in BUY_SIDES else 1
        rows.append({"_key": (x["ts"], "x", x["_id"]), "ts": x["ts"], "type": x["side"], "symbol": x["symbol"],
                     "qty": x["qty"], "price": x["price"], "fees": x.get("fees", 0.0),
                     "cash": sign * x["qty"] * x["price"] - x.get("fees", 0.0),
                     "order_id": str(x["order_id"]) if x.get("order_id") else None, "source": x.get("source")})
    for e in db.ledger_events.find(_page_query(account_id, "e", cur)).sort([("ts", -1), ("_id", -1)]).limit(limit + 1):
        rows.append({"_key": (e["ts"], "e", e["_id"]), "ts": e["ts"], "type": e["kind"], "symbol": e.get("symbol"),
                     "qty": e.get("qty"), "price": None, "fees": None, "cash": e.get("amount"),
                     "cost_basis": e.get("cost_basis"), "ref": e.get("ref"), "reason": e.get("reason")})
    rows.sort(key=lambda r: r["_key"], reverse=True)
    more = len(rows) > limit
    rows = rows[:limit]
    nxt = None
    if more:
        ts, c, oid = rows[-1]["_key"]
        nxt = f"{_iso(ts)}|{c}|{oid}"
    for r in rows:
        del r["_key"]
        r["ts"] = _iso(r["ts"])
    return {"account_id": account_id, "transactions": rows, "next_cursor": nxt}
