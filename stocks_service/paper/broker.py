"""Paper broker (plan §2, §4, §D): simulated accounts that trade the outlook under ``exec_daily_v1``.

* **Orders** come from the latest outlook row (its entry limit, stop and target, cent-rounded) for
  the next session only, placed before that session's open. Risk limits are enforced server-side
  with the account's risk profile; buying power must cover the reservation (notional + entry costs
  for a buy; 100% margin for a short, whose proceeds also stay locked). Each order carries an
  idempotency key and who decided it (agent identity + rationale, or ``baseline_v1``).
* **Processing** (the tick) walks sessions in order from the account's cursor. For every order, the
  **shared simulator** (``simulate_trade``, the same one used by research and outcome labels) is run
  on decision-basis bars up to the session being processed; the outcome's fill and exit are applied
  when their sessions arrive. Fills and exits become ``executions`` (raw shares and prices, with
  spread/slippage/commission as fees); short borrow accrues nightly and dividends on the ex-date as
  ledger events; an equity snapshot is stored per session. Each session commits in one transaction
  with deterministic ids, so re-running is idempotent. A missing bar for a symbol with an open order
  or position stops the cursor (contiguity) instead of skipping it.
"""

from __future__ import annotations

import datetime as dt
import hashlib

from bson import ObjectId
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from .. import sessions
from ..accounts.ledger import QTY_TOL
from ..accounts.risk import Book, RiskProfile, avg_dollar_volume, size_ticket  # noqa: F401
from ..accounts.service import AccountError, NotFound, _lock_account, ledger_state
from ..outlook.build import cost_profile_from_doc, latest_outlook
from ..research.series import SymbolSeries
from ..sim import CostProfile, ExecutionPolicy, TradePlan, entry_costs, exit_costs, simulate_trade
from ..sim.costs import borrow_cost

UTC = dt.timezone.utc
POLICY = ExecutionPolicy()
OPEN_STATUSES = ("open", "filled")


class PaperOnly(AccountError):
    """Orders can only be placed on paper accounts."""


def _dt(d: dt.date) -> dt.datetime:
    return dt.datetime.combine(d, dt.time(), UTC)


def _date(x) -> dt.date:
    return x.date() if isinstance(x, dt.datetime) else x


# --- accounts --------------------------------------------------------------------------------

def create_paper_account(db: Database, *, account_id: str, name: str, starting_cash: float, risk_profile: str,
                         cost_profile: str = "market@1", policy: str = "agent", now: dt.datetime,
                         paired_baseline: str | None = None) -> dict:
    if not starting_cash > 0:
        raise AccountError("starting_cash must be positive")
    if db.risk_profiles.find_one({"_id": risk_profile}) is None:
        raise NotFound(f"risk profile {risk_profile} not found")
    if db.cost_profiles.find_one({"_id": cost_profile}) is None:
        raise NotFound(f"cost profile {cost_profile} not found")
    if paired_baseline is not None:
        b = db.accounts.find_one({"_id": paired_baseline})
        if b is None or b.get("kind") != "paper" or b.get("policy") != "baseline_v1@1":
            raise NotFound(f"baseline paper account {paired_baseline} not found")
        if (b["starting_cash"], b["risk_profile"], b["cost_profile"]) != (starting_cash, risk_profile, cost_profile):
            raise AccountError("the paired baseline must have the same starting cash, risk profile and cost profile")
    from ..accounts.tickets import last_completed_session
    start = last_completed_session(now)   # trading starts with the next session
    doc = {"_id": account_id, "name": name, "kind": "paper", "policy": policy, "starting_cash": starting_cash,
           "risk_profile": risk_profile, "cost_profile": cost_profile, "execution_policy": POLICY.key,
           "last_session_executed": _dt(start), "created_at": now, "ledger_version": 0,
           **({"paired_baseline": paired_baseline} if paired_baseline else {})}

    def txn(session):
        db.accounts.insert_one(doc, session=session)
        db.ledger_events.insert_one({"account_id": account_id, "ts": sessions.session_bounds(start)[1],
                                     "kind": "opening_balance", "symbol": None, "amount": starting_cash,
                                     "ref": "opening:cash"}, session=session)

    try:
        with db.client.start_session() as s:
            s.with_transaction(txn)
    except DuplicateKeyError:
        raise AccountError(f"account {account_id} already exists")
    return doc


def _paper_account(db: Database, account_id: str, session=None) -> dict:
    acc = db.accounts.find_one({"_id": account_id}, session=session)
    if acc is None:
        raise NotFound(f"account {account_id} not found")
    if acc.get("kind") != "paper":
        raise PaperOnly(f"{account_id} is a real account; orders can only be placed on paper accounts")
    return acc


def _cost(db: Database, acc: dict) -> CostProfile:
    return cost_profile_from_doc(db.cost_profiles.find_one({"_id": acc["cost_profile"]}))


# --- buying power and placement ----------------------------------------------------------------

def _marks(db: Database, symbols, session=None) -> dict[str, float]:
    out = {}
    for s in symbols:
        b = db.bars.find_one({"symbol": s, "interval": "1d"}, {"c": 1}, sort=[("session", -1)], session=session)
        if b:
            out[s] = b["c"]
    return out


def account_book(db: Database, acc: dict, now: dt.datetime, session=None,
                 profile: RiskProfile | None = None, clusters: tuple[dict, dict] | None = None) -> tuple[Book, dict]:
    """Equity, free cash and committed exposure of a paper account (holdings + open orders).

    Fully collateralized: a short's proceeds stay locked and the same amount again is held as
    margin, so free cash = cash - 2 x short market value - open-order reservations.
    """
    st = ledger_state(db, acc["_id"], now, session)
    pos = st.open_positions()
    marks = _marks(db, pos, session)
    missing = [s for s in pos if s not in marks]
    if missing:
        raise AccountError(f"no price for held {missing}; cannot value the account")
    mv = {s: h.qty * marks[s] for s, h in pos.items()}
    equity = st.cash + sum(mv.values())
    short_mv = sum(-v for v in mv.values() if v < 0)
    orders = list(db.orders.find({"account_id": acc["_id"], "status": "open"}, session=session))
    reserved = sum(o["reservation"] for o in orders)
    free = st.cash - 2 * short_mv - reserved
    book = Book(equity=equity, cash=free)
    book.gross = sum(abs(v) for v in mv.values()) + sum(o["qty"] * o["limit"] for o in orders)
    book.short = short_mv + sum(o["qty"] * o["limit"] for o in orders if o["side"] == "short")
    if clusters is not None:  # |exposure| per cluster: holdings at market + open orders at their limit
        from .clusters import keys_for
        groups, corr = clusters
        for sym, v in mv.items():
            for k in keys_for(sym, groups, corr):
                book.clusters[k] = book.clusters.get(k, 0.0) + abs(v)
        for o in orders:
            for k in keys_for(o["symbol"], groups, corr):
                book.clusters[k] = book.clusters.get(k, 0.0) + o["qty"] * o["limit"]
    if profile is not None:  # heat: loss to the stop incl. gap stress, open orders and filled positions
        for o in db.orders.find({"account_id": acc["_id"], "status": {"$in": list(OPEN_STATUSES)}}, session=session):
            if o["status"] == "open":
                ref = o["limit"]
            else:  # current price on the order's decision basis (stop is on that basis; splits handled)
                s_ = SymbolSeries.from_db(db, o["symbol"])
                ref = s_.close_on_basis(o["decided"].date(), s_.sessions[-1])
            book.heat += o["qty"] * (abs(ref - o["stop"]) + profile.gap_stress_atr * o["atr"])
    return book, {"cash": st.cash, "reserved": reserved, "equity": equity, "free_cash": free, "positions": mv}


def place_order(db: Database, account_id: str, *, symbol: str, side: str, qty: int, idempotency_key: str,
                decided_by: dict, now: dt.datetime) -> dict:
    """Place a DAY limit order for the next session from the latest outlook row (paper accounts only)."""
    if not isinstance(qty, int) or qty < 1:
        raise AccountError("qty must be a whole number of shares >= 1")
    out: dict = {}

    def txn(session):
        acc = _paper_account(db, account_id, session)
        _lock_account(db, account_id, session)
        dup = db.orders.find_one({"account_id": account_id, "idempotency_key": idempotency_key}, session=session)
        if dup:
            out.update(order=dup, replayed=True)
            return
        o = latest_outlook(db)
        if o is None:
            raise NotFound("no outlook yet")
        row = next((r for r in o["rows"] if r["symbol"] == symbol and r["side"] == side), None)
        if row is None or not row.get("plan"):
            raise AccountError(f"{symbol} {side} has no plan in the {o['asof']} outlook")
        if row["source"].startswith("signal:"):  # latest_outlook already demotes paused sources; re-check here
            v = db.strategy_versions.find_one({"_id": row["source"].removeprefix("signal:")}, {"status": 1},
                                              session=session)
            if v and v.get("status") in ("paused", "retired"):
                raise AccountError(f"{row['source']} is {v['status']}; it supplies no new entries")
        deadline = dt.datetime.fromisoformat(row["placeable_until"])
        if now >= deadline:
            raise AccountError(f"placement window for the {o['asof']} outlook closed at {deadline.isoformat()}")
        if _date(acc["last_session_executed"]) < dt.date.fromisoformat(o["asof"]):
            raise AccountError("the account has not been processed through the outlook session yet; retry after the tick")
        held = ledger_state(db, account_id, now, session).qty(symbol)
        if abs(held) > QTY_TOL or db.orders.find_one({"account_id": account_id, "symbol": symbol,
                                                       "status": {"$in": list(OPEN_STATUSES)}}, session=session):
            raise AccountError(f"{symbol} already has an open order or position in this account")
        p = row["plan"]
        limit, stop, target = round(p["entry_limit"], 2), round(p["stop"], 2), round(p["target"], 2)
        plan = TradePlan(side, dt.date.fromisoformat(o["asof"]), limit, stop, target)  # validates ordering
        cost = _cost(db, acc)
        if side == "short" and cost.borrow_rate_annual is None:
            raise AccountError(f"cost profile {cost.key} has no borrow rate, so this account cannot short")
        profile = RiskProfile.from_doc(db.risk_profiles.find_one({"_id": acc["risk_profile"]}))
        from .clusters import cluster_map, keys_for
        cmap = cluster_map(db, o["asof"], profile.corr_threshold)
        book, _ = account_book(db, acc, now, session, profile, cmap)
        allowed, why = max_order_qty(row, book, profile, cost, keys_for(symbol, *cmap),
                                     SymbolSeries.from_db(db, symbol), plan.decided)
        if qty > allowed:
            raise AccountError(f"qty {qty} exceeds the risk limit of {allowed} ({why})")
        # Reservation: notional + entry costs (a buy's cash, or a short's 100% margin); <= free cash by construction.
        reservation = qty * limit + entry_costs(cost, limit, qty)
        doc = {"_id": ObjectId(), "account_id": account_id, "idempotency_key": idempotency_key, "symbol": symbol,
               "side": side, "qty": qty, "limit": limit, "stop": stop, "target": target, "atr": p["atr"],
               "decided": _dt(plan.decided), "eligible_session": _dt(sessions.next_session(plan.decided)),
               "outlook_asof": o["asof"], "grade": row["grade"], "source": row["source"],
               "exp_return_6m": row.get("exp_return_6m"), "placed_at": now, "placeable_until": deadline,
               "status": "open", "reservation": reservation, "decided_by": decided_by, "events": []}
        db.orders.insert_one(doc, session=session)
        out.update(order=doc, replayed=False)

    with db.client.start_session() as s:
        s.with_transaction(txn)
    return out


def max_order_qty(row: dict, book: Book, profile: RiskProfile, cost: CostProfile, keys: set[str],
                  series: SymbolSeries, asof: dt.date) -> tuple[int, str]:
    """Largest order the account may place: risk limits, then buying power including entry costs."""
    allowed, why, _ = size_ticket(row, Book(book.equity, book.cash, book.gross, book.short, book.heat,
                                            dict(book.clusters)),
                                  profile, keys=keys, adv_usd=avg_dollar_volume(series, asof), shortable=True)
    reason = why[0] if why else "risk limits"
    limit = round(row["plan"]["entry_limit"], 2)
    per_share = limit * (1 + (cost.half_spread_bps + cost.slippage_bps) / 10_000) + cost.commission_per_share
    cash_cap = int(max(0.0, book.cash - cost.min_commission) // per_share)
    if cash_cap < allowed:
        return cash_cap, "buying power incl. entry costs"
    return allowed, reason


def cancel_order(db: Database, account_id: str, order_id: str, *, now: dt.datetime) -> dict:
    out = {}

    def txn(session):
        _paper_account(db, account_id, session)
        _lock_account(db, account_id, session)
        o = db.orders.find_one({"_id": ObjectId(order_id), "account_id": account_id}, session=session)
        if o is None:
            raise NotFound("order not found")
        if o["status"] != "open":
            raise AccountError(f"order is {o['status']}; only open orders can be cancelled")
        if now >= sessions.session_bounds(o["eligible_session"].date())[0]:
            raise AccountError("the order's session has opened; it can no longer be cancelled")
        db.orders.update_one({"_id": o["_id"]}, {"$set": {"status": "cancelled", "cancelled_at": now}}, session=session)
        out.update(db.orders.find_one({"_id": o["_id"]}, session=session))

    with db.client.start_session() as s:
        s.with_transaction(txn)
    return out


# --- processing ---------------------------------------------------------------------------------

def _exec_id(order_id, event: str) -> str:
    return "p:" + hashlib.sha256(f"{order_id}|{event}".encode()).hexdigest()[:32]


def _factor(series: SymbolSeries, decided: dt.date, d: dt.date) -> float:
    return series._factor_since(decided, d)


def _process_session(db: Database, acc: dict, d: dt.date, cost: CostProfile, cache: dict, now: dt.datetime,
                     session) -> str | None:
    """Apply session ``d`` to the account. Returns a stall reason, or None when processed."""
    aid = acc["_id"]
    orders = list(db.orders.find({"account_id": aid, "status": {"$in": list(OPEN_STATUSES)},
                                  "eligible_session": {"$lte": _dt(d)}}, session=session))
    open_, close = sessions.session_bounds(d)
    nxt = sessions.next_session(d)

    def series(sym):
        if sym not in cache:
            cache[sym] = SymbolSeries.from_db(db, sym)
        return cache[sym]

    for o in orders:
        s = series(o["symbol"])
        if not s.has_bar(d):
            return f"{o['symbol']} has no bar for {d}"
    for o in orders:
        s = series(o["symbol"])
        decided = o["decided"].date()
        plan = TradePlan(o["side"], decided, o["limit"], o["stop"], o["target"])
        bars = [b for b in s.bars_after(decided, POLICY.timeout_sessions + 3) if b.session <= d]
        oc = simulate_trade(plan, bars, o["eligible_session"].date(), POLICY)
        f = _factor(s, decided, d)
        long = o["side"] == "long"
        if o["status"] == "open":
            if oc.fill_session is None:
                db.orders.update_one({"_id": o["_id"]}, {"$set": {"status": "not_filled", "result": oc.result,
                                                                 "note": oc.note, "resolved_session": _dt(d)}},
                                     session=session)
                continue
            q, px = o["qty"] * f, oc.fill_price / f
            _insert_exec(db, aid, o, "entry", "buy" if long else "short", q, px, entry_costs(cost, px, q),
                         open_ if oc.gap_fill else open_ + dt.timedelta(minutes=1), session)
            db.orders.update_one({"_id": o["_id"]}, {"$set": {"status": "filled", "fill_session": _dt(d),
                                                             "fill_price": oc.fill_price}}, session=session)
            o["status"], o["fill_session"], o["fill_price"] = "filled", _dt(d), oc.fill_price
        if o["status"] == "filled":
            fill_d = o["fill_session"].date()
            for ex, amt in s.dividends:
                if ex == d and fill_d < d:
                    q = o["qty"] * f
                    _event(db, aid, f"dividend:{o['_id']}:{d}", ("dividend" if long else "dividend_charge"),
                           (1 if long else -1) * amt * q, open_, session)
            if oc.exit_session == d:
                q, px = o["qty"] * f, oc.exit_price / f
                at_open = abs(oc.exit_price - next(b.o for b in bars if b.session == d)) < 1e-12
                _insert_exec(db, aid, o, "exit", "sell" if long else "cover", q, px, exit_costs(cost, px, q),
                             open_ + dt.timedelta(seconds=1) if at_open else close - dt.timedelta(minutes=1), session)
                db.orders.update_one({"_id": o["_id"]}, {"$set": {"status": "closed", "result": oc.result,
                                                                 "exit_session": _dt(d), "exit_price": oc.exit_price,
                                                                 "ambiguous": oc.ambiguous}}, session=session)
            elif not long:
                fee = borrow_cost(cost, o["qty"] * o["fill_price"], (nxt - d).days)
                _event(db, aid, f"borrow:{o['_id']}:{d}", "borrow_fee", -fee, close, session)
    # Equity at the close of d (raw marks).
    st = ledger_state(db, aid, close, session)
    mv = 0.0
    for sym, h in st.open_positions().items():
        s = series(sym)
        if not s.has_bar(d):
            return f"{sym} has no bar for {d}"
        mv += h.qty * s.raw[s.count_through(d) - 1]["c"]
    reserved = sum(o["reservation"] for o in db.orders.find({"account_id": aid, "status": "open"}, session=session))
    db.equity_curve.update_one({"account_id": aid, "session": _dt(d)},
                               {"$set": {"cash": st.cash, "market_value": mv, "equity": st.cash + mv,
                                         "reserved": reserved, "at": now}}, upsert=True, session=session)
    db.accounts.update_one({"_id": aid}, {"$set": {"last_session_executed": _dt(d)}}, session=session)
    return None


def _insert_exec(db, aid, o, event, side, qty, price, fees, ts, session):
    try:
        db.executions.insert_one({"account_id": aid, "exec_id": _exec_id(o["_id"], event), "order_id": o["_id"],
                                  "symbol": o["symbol"], "side": side, "qty": qty, "price": price, "fees": fees,
                                  "ts": ts, "source": "paper_sim"}, session=session)
    except DuplicateKeyError:
        pass


def _event(db, aid, ref, kind, amount, ts, session):
    try:
        db.ledger_events.insert_one({"account_id": aid, "ts": ts, "kind": kind, "symbol": None, "amount": amount,
                                     "ref": ref}, session=session)
    except DuplicateKeyError:
        pass


def process_account(db: Database, account_id: str, now: dt.datetime) -> dict:
    """Advance the account's cursor through every completed session that has data."""
    from ..accounts.tickets import last_completed_session
    acc = _paper_account(db, account_id)
    cost = _cost(db, acc)
    spy = db.bars.find_one({"symbol": "SPY", "interval": "1d"}, {"session": 1}, sort=[("session", -1)])
    end = min(last_completed_session(now), spy["session"].date()) if spy else None
    cache: dict = {}
    done, stalled = [], None
    d = sessions.next_session(acc["last_session_executed"].date())
    while end and d <= end:
        result = {}

        def txn(session):
            _lock_account(db, account_id, session)
            fresh = db.accounts.find_one({"_id": account_id}, session=session)
            if fresh["last_session_executed"].date() >= d:
                result["skip"] = True
                return
            result["stall"] = _process_session(db, fresh, d, cost, cache, now, session)

        with db.client.start_session() as s:
            s.with_transaction(txn)
        if result.get("stall"):
            stalled = result["stall"]
            break
        done.append(d.isoformat())
        d = sessions.next_session(d)
    if stalled:
        db.accounts.update_one({"_id": account_id}, {"$set": {"stalled": stalled}})
    else:
        db.accounts.update_one({"_id": account_id}, {"$unset": {"stalled": ""}})
    return {"account_id": account_id, "processed": done, "stalled": stalled}
