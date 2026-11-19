"""Operations behind the MCP tools that go beyond paper trading: the watch list, uploading a real
account's holdings, detailed per-symbol predictions, account read models, and the two-step
confirmation used by the watch-list changes (holdings uploads apply directly, after validation).

Two-step confirmation: a changing tool called without ``confirm_token`` only *previews* — it
validates everything, describes exactly what would happen, and issues a single-use token bound to
those exact arguments (15 minutes). The agent shows the preview to the user and, once they agree,
calls again with the same arguments and the token. Different arguments, an expired or a used
token are refused.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import secrets

from pymongo import ReturnDocument
from pymongo.database import Database

from . import ingestion, sessions
from .models import SYMBOL_PATTERN, AssetClass

UTC = dt.timezone.utc
CONFIRM_TTL = dt.timedelta(minutes=15)
INSTRUMENT_TYPES = {"EQUITY": AssetClass.equity, "ETF": AssetClass.etf, "MUTUALFUND": AssetClass.mutual_fund,
                    "INDEX": AssetClass.index, "FUTURE": AssetClass.future, "CURRENCY": AssetClass.fx}
TRADABLE_CLASSES = (AssetClass.equity, AssetClass.etf)   # the outlook covers equities and ETFs
# Inputs the service itself needs, whatever the watch list: SPY's bars are the session clock for the
# outlook and paper accounts, ^IRX is the cash rate, SPY/QQQ/QQQM are the research benchmarks.
REQUIRED_SYMBOLS = ("SPY", "^IRX", "QQQ", "QQQM")


class OpError(ValueError):
    """A refused operation; the message says why and what to do."""


# --- confirmation ------------------------------------------------------------------------------

def _args_hash(tool: str, args: dict) -> str:
    return hashlib.sha256(json.dumps([tool, args], sort_keys=True, default=str).encode()).hexdigest()


def issue_token(db: Database, tool: str, args: dict, ident: dict, now: dt.datetime) -> dict:
    token = secrets.token_urlsafe(16)
    db.mcp_confirmations.insert_one({"_id": token, "tool": tool, "args_hash": _args_hash(tool, args), "args": args,
                                     **ident, "created_at": now, "expires_at": now + CONFIRM_TTL, "used_at": None})
    return {"confirm_token": token, "expires_at": (now + CONFIRM_TTL).isoformat(),
            "next_step": "Show this preview to the user. Only if they confirm, call the same tool again with the "
                         "same arguments plus confirm_token."}


def redeem_token(db: Database, token: str, tool: str, args: dict, now: dt.datetime) -> dict:
    """Mark the token used (atomically) if it matches this tool and these exact arguments."""
    doc = db.mcp_confirmations.find_one_and_update(
        {"_id": token, "used_at": None, "expires_at": {"$gt": now}},
        {"$set": {"used_at": now}}, return_document=ReturnDocument.AFTER)
    if doc is None:
        raise OpError("confirm_token is unknown, expired or already used; call without it for a new preview")
    if doc["tool"] != tool or doc["args_hash"] != _args_hash(tool, args):
        db.mcp_confirmations.update_one({"_id": token}, {"$set": {"used_at": None}})
        raise OpError("confirm_token was issued for different arguments; call without it for a new preview")
    return doc


def release_token(db: Database, token: str) -> None:
    """The confirmed operation failed: let the user retry with the same token while it is valid."""
    db.mcp_confirmations.update_one({"_id": token}, {"$set": {"used_at": None}})


# --- watch list --------------------------------------------------------------------------------

def normalize_symbol(symbol: str) -> str:
    import re
    s = (symbol or "").strip().upper()
    if not re.fullmatch(SYMBOL_PATTERN, s):
        raise OpError(f"{symbol!r} is not a valid ticker (letters, digits, '.', '-', '=' or a leading '^')")
    return s


def _last_bar(db: Database, symbol: str) -> dict | None:
    return db.bars.find_one({"symbol": symbol, "interval": "1d"}, {"session": 1, "c": 1}, sort=[("session", -1)])


def watchlist(db: Database) -> dict:
    rows, removed = [], []
    for s in db.symbols.find().sort("_id", 1):
        b = _last_bar(db, s["_id"])
        row = {"symbol": s["_id"], "name": s.get("name"), "asset_class": s.get("asset_class"),
               "groups": s.get("groups", []), "tradable": s.get("tradable", True), "shortable": s.get("shortable", False),
               "last_session": b["session"].date().isoformat() if b else None, "last_close": b["c"] if b else None,
               "quarantined": (s.get("quarantine") or {}).get("reason")}
        (rows if s.get("enabled", True) else removed).append(row)
    return {"watched": rows, "removed": removed}


def _lookup(fetcher, symbol: str, now: dt.datetime) -> dict:
    """What Yahoo knows about the ticker (instrument type, name, exchange); refuses unknown tickers."""
    try:
        payload = fetcher.fetch_chart(symbol, "1d", int((now - dt.timedelta(days=10)).timestamp()), int(now.timestamp()))
        meta = payload["chart"]["result"][0]["meta"]
    except Exception as e:
        raise OpError(f"could not find {symbol} at the price source (Yahoo): {e}")
    itype = meta.get("instrumentType")
    if itype not in INSTRUMENT_TYPES:
        raise OpError(f"{symbol} is a {itype or 'unknown instrument type'}; supported: {', '.join(INSTRUMENT_TYPES)}")
    return {"name": meta.get("longName") or meta.get("shortName"), "asset_class": INSTRUMENT_TYPES[itype].value,
            "exchange": meta.get("fullExchangeName") or meta.get("exchangeName"), "currency": meta.get("currency"),
            "last_price": meta.get("regularMarketPrice")}


def preview_add(db: Database, fetcher, symbol: str, now: dt.datetime) -> dict:
    sym = normalize_symbol(symbol)
    existing = db.symbols.find_one({"_id": sym})
    if existing and existing.get("enabled", True):
        raise OpError(f"{sym} is already on the watch list")
    info = _lookup(fetcher, sym, now)
    has_bars = _last_bar(db, sym) is not None
    tradable = AssetClass(info["asset_class"]) in TRADABLE_CLASSES
    return {"symbol": sym, "action": "re-enable" if existing else "add", **info,
            "will": [("Re-enable" if existing else "Add") + f" {sym} ({info['name']}, {info['asset_class']}) to the watch list",
                     "Load its daily history from the price source" if not has_bars else "Bring its stored daily history up to date",
                     ("It appears in the six-month outlook built after the next close; until then get_prediction "
                      "gives live strategy decisions, ATR levels and odds" if tradable
                      else f"As a {info['asset_class']} it is tracked for prices only (the outlook covers equities and ETFs)")]}


def apply_add(db: Database, fetcher, settings, symbol: str, now: dt.datetime) -> dict:
    p = preview_add(db, fetcher, symbol, now)
    sym = p["symbol"]
    tradable = AssetClass(p["asset_class"]) in TRADABLE_CLASSES
    if p["action"] == "re-enable":
        db.symbols.update_one({"_id": sym}, {"$set": {"enabled": True, "re_enabled_at": now}})
    else:
        db.symbols.insert_one({"_id": sym, "name": p["name"], "asset_class": p["asset_class"], "sector": None,
                               "groups": [], "factors": [], "tradable": tradable, "enabled": True, "priority": 1,
                               "shortable": False, "ca_version": 0, "created_at": now, "added_via": "mcp"})
    kw = dict(now=now, buffer=dt.timedelta(minutes=settings.ingest_buffer_minutes),
              overlap_tolerance=settings.overlap_tolerance, gap_threshold=settings.unexplained_gap_log_threshold)
    try:
        if _last_bar(db, sym) is None:
            r = ingestion.ingest(db, fetcher, symbol=sym, interval="1d",
                                 start=dt.datetime(1990, 1, 2, tzinfo=UTC), **kw)
        else:
            r = ingestion.update(db, fetcher, symbol=sym, interval="1d", **kw)
        history = {"status": "loaded", "bars_added": r.upserted, "bars_total": db.bars.count_documents(
            {"symbol": sym, "interval": "1d"})}
    except Exception as e:
        if _last_bar(db, sym) is None:
            # No history at all: the tick only updates symbols that have bars, so undo the addition and fail;
            # the confirmation token is released and the same call can simply be retried.
            if p["action"] == "re-enable":
                db.symbols.update_one({"_id": sym}, {"$set": {"enabled": False}, "$unset": {"re_enabled_at": ""}})
            else:
                db.symbols.delete_one({"_id": sym, "added_via": "mcp", "created_at": now})
            raise OpError(f"could not load {sym}'s price history ({type(e).__name__}: {e}); nothing was changed, "
                          "retry with the same confirm_token")
        # Stored history exists, so the scheduled tick keeps updating it; report the failed refresh.
        history = {"status": "update_failed", "error": f"{type(e).__name__}: {e}",
                   "note": "earlier history is kept and the scheduled update retries"}
    return {"symbol": sym, "action": p["action"], "name": p["name"], "asset_class": p["asset_class"], "history": history}


def _holders(db: Database, sym: str, now: dt.datetime) -> tuple[list[dict], list[dict]]:
    """(paper accounts with open/filled orders in ``sym``, real accounts holding it)."""
    from .accounts.service import ledger_state
    paper = [{"account_id": o["account_id"], "order_id": str(o["_id"]), "status": o["status"]}
             for o in db.orders.find({"symbol": sym, "status": {"$in": ["open", "filled"]}})]
    real = []
    for a in db.accounts.find({"kind": {"$ne": "paper"}}, {"_id": 1}):
        qty = ledger_state(db, a["_id"], now).qty(sym)
        if abs(qty) > 1e-9:
            real.append({"account_id": a["_id"], "qty": qty})
    return paper, real


def preview_remove(db: Database, symbol: str, now: dt.datetime) -> dict:
    sym = normalize_symbol(symbol)
    doc = db.symbols.find_one({"_id": sym})
    if doc is None or not doc.get("enabled", True):
        raise OpError(f"{sym} is not on the watch list")
    if sym in REQUIRED_SYMBOLS:
        raise OpError(f"{sym} cannot be removed: the service needs it ({', '.join(REQUIRED_SYMBOLS)} are the session "
                      "clock, cash rate and research benchmarks)")
    paper, real = _holders(db, sym, now)
    if paper:
        raise OpError(f"{sym} cannot be removed while paper accounts have open orders or positions in it "
                      f"({', '.join(sorted({p['account_id'] for p in paper}))}): their exits need its daily prices")
    warnings = [f"{r['account_id']} holds {r['qty']:g} {sym}; its value will be marked at the last stored close "
                f"and no new prices or protective alerts will arrive" for r in real]
    return {"symbol": sym, "action": "remove", "will": [
        f"Stop tracking {sym}: no new prices, no outlook rows, no paper orders",
        "Keep its stored price history (re-adding it later resumes from there)"], "warnings": warnings}


def apply_remove(db: Database, symbol: str, now: dt.datetime) -> dict:
    """Disable the symbol and check for paper orders in the same transaction. Paper order placement
    writes the symbol document inside its own transaction (``broker.place_order``), so the two
    conflict and serialize: an order either lands first (and blocks the removal) or sees the symbol
    disabled (and is refused)."""
    p = preview_remove(db, symbol, now)
    sym = p["symbol"]

    def txn(session):
        res = db.symbols.update_one({"_id": sym, "enabled": {"$ne": False}},
                                    {"$set": {"enabled": False, "removed_at": now}}, session=session)
        if res.matched_count == 0:
            raise OpError(f"{sym} is not on the watch list")
        held = db.orders.find_one({"symbol": sym, "status": {"$in": ["open", "filled"]}}, {"account_id": 1},
                                  session=session)
        if held:
            raise OpError(f"{sym} cannot be removed: paper account {held['account_id']} now has an open order or "
                          "position in it")

    with db.client.start_session() as s:
        s.with_transaction(txn)
    return {"symbol": sym, "action": "removed", "warnings": p["warnings"]}


# --- real-account holdings ---------------------------------------------------------------------

def parse_as_of(as_of: str) -> dt.datetime:
    """An ISO datetime (UTC if no offset), or a date meaning that day's close (or end of day if closed)."""
    try:
        if len(as_of.strip()) == 10:
            d = dt.date.fromisoformat(as_of.strip())
            return sessions.session_bounds(d)[1] if sessions.is_session(d) else dt.datetime.combine(
                d, dt.time(23, 59, 59), UTC)
        t = dt.datetime.fromisoformat(as_of.strip().replace("Z", "+00:00"))
    except ValueError:
        raise OpError(f"as_of {as_of!r} is not an ISO date or datetime")
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def _clean_positions(positions: list[dict]) -> list[dict]:
    """Validated before any preview token is issued or any account is created."""
    import math
    out = []
    for p in positions:
        sym = normalize_symbol(p["symbol"])
        qty = float(p["qty"])
        cost = float(p["avg_cost"]) if p.get("avg_cost") is not None else None
        if not math.isfinite(qty):
            raise OpError(f"{sym}: qty must be a finite number")
        if cost is not None and not (math.isfinite(cost) and cost > 0):
            raise OpError(f"{sym}: avg_cost must be a positive number")
        out.append({"symbol": sym, "qty": qty, "avg_cost": cost})
    return out


def preview_holdings(db: Database, account_id: str, *, as_of: str, cash: float, positions: list[dict],
                     account_name: str | None, now: dt.datetime) -> dict:
    import math
    import re
    from .accounts.ledger import CASH, reconcile
    from .accounts.service import _has_history, ledger_state
    t = parse_as_of(as_of)
    if t > now + dt.timedelta(minutes=5):
        raise OpError("as_of is in the future")
    if not math.isfinite(cash):
        raise OpError("cash must be a finite number")
    pos = _clean_positions(positions)
    syms = [p["symbol"] for p in pos]
    if len(set(syms)) != len(syms):
        raise OpError("each symbol may appear once (add up the lots)")
    acc = db.accounts.find_one({"_id": account_id})
    will, creates = [], False
    if acc is None:
        if not account_name:
            raise OpError(f"account {account_id} does not exist; pass account_name to create it with this upload")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,40}", account_id):
            raise OpError("account_id: lowercase letters, digits, - or _ (2-41 characters)")
        creates = True
        will.append(f"Create the real account {account_id} ({account_name})")
    elif acc.get("kind") == "paper":
        raise OpError(f"{account_id} is a paper account; holdings are uploaded to real accounts only")
    opening = creates or not _has_history(db, account_id)
    if opening:
        missing = [p["symbol"] for p in pos if p["avg_cost"] is None]
        if missing:
            raise OpError(f"the first upload is the opening balance and needs avg_cost for every position (missing: {missing})")
        will.append(f"Record the opening balance as of {t.isoformat()}: cash {cash:,.2f} and {len(pos)} position(s)")
        differences = []
    else:
        latest = db.portfolio_snapshots.find_one({"account_id": account_id}, sort=[("as_of", -1)])
        st = ledger_state(db, account_id, t)
        differences = [{"symbol": d.symbol, "expected": d.expected, "reported": d.reported,
                        "diff": d.reported - d.expected}
                       for d in reconcile(st, cash, {p["symbol"]: p["qty"] for p in pos})]
        will.append(f"Store the snapshot as of {t.isoformat()} and reconcile it with the ledger")
        will.append(f"{len(differences)} difference(s) would be recorded as breaks to explain (never as trades)"
                    if differences else "It matches the ledger exactly (no breaks)")
        if latest and latest["as_of"] > t:
            will.append(f"Note: a newer snapshot ({latest['as_of'].isoformat()}) is already on file")
        differences = [{**d, "symbol": "cash" if d["symbol"] == CASH else d["symbol"]} for d in differences]
    watched = {s["_id"] for s in db.symbols.find({"enabled": {"$ne": False}}, {"_id": 1})}
    unwatched = sorted(set(syms) - watched)
    return {"account_id": account_id, "as_of": t.isoformat(), "opening_balance": opening, "creates_account": creates,
            "cash": cash, "positions": pos, "will": will, "differences": differences,
            "not_on_watch_list": unwatched,
            **({"note": "positions not on the watch list have no prices: they are valued only once added "
                        "(add_to_watchlist)"} if unwatched else {})}


def apply_holdings(db: Database, account_id: str, *, as_of: str, cash: float, positions: list[dict],
                   account_name: str | None, now: dt.datetime) -> dict:
    from .accounts import service
    p = preview_holdings(db, account_id, as_of=as_of, cash=cash, positions=positions, account_name=account_name, now=now)
    if p["creates_account"]:
        service.create_account(db, account_id=account_id, name=account_name, now=now)
    res = service.upload_snapshot(db, account_id, as_of=dt.datetime.fromisoformat(p["as_of"]), cash=cash,
                                  positions=p["positions"], opening=p["opening_balance"], now=now)
    breaks = [{"symbol": b["symbol"], "expected": b["expected"], "reported": b["reported"], "diff": b["diff"]}
              for b in res["breaks"] if b["status"] == "open"]
    return {"account_id": account_id, "snapshot_id": str(res["snapshot"]["_id"]),
            "opening_balance": res["snapshot"]["opening"], "open_breaks": breaks,
            "holdings": jsonable(service.holdings(db, account_id, now))}


# --- predictions -------------------------------------------------------------------------------

def jsonable(x):
    """JSON-safe copy: dataclasses to dicts, ObjectIds/dates to strings, tuples to lists."""
    from bson import ObjectId
    if dataclasses.is_dataclass(x) and not isinstance(x, type):
        return jsonable(dataclasses.asdict(x))
    if isinstance(x, dict):
        out = {("id" if k == "_id" else k): jsonable(v) for k, v in x.items()}
        return out
    if isinstance(x, (list, tuple)):
        return [jsonable(v) for v in x]
    if isinstance(x, ObjectId):
        return str(x)
    if isinstance(x, (dt.datetime, dt.date)):
        return x.isoformat()
    if isinstance(x, float) and x != x:   # NaN is not JSON
        return None
    return x


def _ret(c, n: int):
    return float(c[-1] / c[-1 - n] - 1) if len(c) > n else None


def prediction(db: Database, symbol: str) -> dict:
    """Everything the service knows about where ``symbol`` may go: its latest outlook rows (both sides,
    with grade, plan and the six-month return distribution), today's strategy decisions, ATR levels
    with time-to-target odds, and recent price context."""
    from .levels import LevelsUnavailable, atr_levels
    from .outlook.build import latest_outlook
    from .strategies import all_specs, decide
    from .strategies.runner import load_view
    from .web.data import yearly_summary
    sym = normalize_symbol(symbol)
    doc = db.symbols.find_one({"_id": sym})
    if doc is None or not doc.get("enabled", True):
        raise OpError(f"{sym} is not on the watch list, so there is no data for it; add it with add_to_watchlist "
                      "(loads its history) and ask again")
    out: dict = {"symbol": sym, "name": doc.get("name"), "asset_class": doc.get("asset_class"),
                 "groups": doc.get("groups", []), "shortable": doc.get("shortable", False)}
    last = _last_bar(db, sym)
    if last is None:
        out["unavailable"] = "no price history loaded yet (it loads when the symbol is added; retry shortly)"
        return out
    asof = last["session"].date()
    full = load_view(db, sym, asof, lookback=0)
    c = full.c
    yr = [float(x) for d, x in zip(full.sessions, c) if d.year == asof.year]
    prev_year = [float(x) for d, x in zip(full.sessions, c) if d.year == asof.year - 1]
    import numpy as np
    hi, lo = np.asarray(full.h[-252:], dtype=float), np.asarray(full.l[-252:], dtype=float)
    out["price"] = {"asof": asof.isoformat(), "last_close": float(c[-1]), "basis": "split-adjusted",
                    "return_1m": _ret(c, 21), "return_3m": _ret(c, 63), "return_6m": _ret(c, 126),
                    "return_1y": _ret(c, 252), "return_ytd": (yr[-1] / prev_year[-1] - 1) if yr and prev_year else None,
                    "high_52w": float(np.nanmax(hi)), "low_52w": float(np.nanmin(lo)),   # intraday range
                    "sessions_on_file": len(c)}
    out["calendar_years"] = jsonable(yearly_summary(full)[:6])
    o = latest_outlook(db)
    if o is None:
        out["outlook"] = {"unavailable": "no outlook has been built yet"}
    else:
        rows = [r for r in o["rows"] if r["symbol"] == sym]
        out["outlook"] = jsonable({
            "asof": o["asof"], "run_id": o["run_id"], "placeable_until": o.get("placeable_until"),
            "horizon_end": o.get("horizon_end"), "cash_return_6m": o["cash_return_6m"], "cost_profile": o["cost_profile"],
            "rows": rows} if rows else {"asof": o["asof"], "unavailable": f"{sym} was not in the outlook built for "
                                        f"{o['asof']}; it is included from the next build"})
    view = load_view(db, sym, asof)
    out["strategy_decisions"] = [
        {"strategy": d.strategy, "direction": d.direction, "strength": d.strength, "reasons": list(d.reasons)}
        for d in (decide(view, spec) for spec in all_specs())]   # too little history -> an explicit hold
    from . import estimation
    sides = {}
    for side in ("long", "short"):
        try:
            lv = atr_levels(view, side)
        except LevelsUnavailable as e:
            sides[side] = {"unavailable": str(e)}
            continue
        est = estimation.ensemble_estimate(view, lv.entry_limit, lv.target, lv.stop, side)
        sides[side] = {"levels": jsonable(lv), "time_estimate": jsonable(est)}
    out["atr_levels_and_odds"] = sides
    out["notes"] = [
        "Outlook grades: A = calibrated signal of a validated strategy, B = calibrated signal of an unvalidated "
        "strategy, C = this symbol's own history for the same plan (a base rate, not a forecast), insufficient = no estimate.",
        "exp_return_6m and the 10th/90th percentiles are per position over 126 sessions after costs; idle capital earns T-bills.",
        "Strategy decisions and ATR odds are research output; no strategy is validated yet, so nothing here is a recommendation.",
    ]
    return out
