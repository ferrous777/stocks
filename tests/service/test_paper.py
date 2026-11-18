import dataclasses
import datetime as dt

import pytest
from fastapi.testclient import TestClient

from stocks_service.accounts.service import ledger_state
from stocks_service.api.app import create_app
from stocks_service.outlook import build
from stocks_service.paper import baseline, broker
from stocks_service.research import protocol
from stocks_service.research.series import SymbolSeries
from stocks_service.settings import Settings
from stocks_service.sim import ExecutionPolicy, TradePlan, net_trade, simulate_trade

from .conftest import NOW
from .test_research import _load_db
from .test_risk_tickets import PROFILE

UTC = dt.timezone.utc
H = {"X-API-Key": "k"}
ASOF = dt.date(2025, 3, 31)
EVENING = dt.datetime(2025, 3, 31, 23, 0, tzinfo=UTC)     # after the close, before the next open
LATER = dt.datetime(2025, 6, 2, 23, 0, tzinfo=UTC)


def _client(db):
    s = Settings(mongo_url="x", api_keys="k", admin_password="pw", session_secret="s" * 40)
    return TestClient(create_app(s, db=db), base_url="https://testserver")


@pytest.fixture
def world(db):
    """Real bars through 2025-03-31 only, a calibrated outlook as of that close, and the later bars held back."""
    _load_db(db)
    protocol.seal_holdout(db, start=dt.date(2024, 11, 18), end=dt.date(2025, 5, 30), now=NOW)
    later = list(db.bars.find({"session": {"$gt": dt.datetime(2025, 3, 31, tzinfo=UTC)}}))
    db.bars.delete_many({"_id": {"$in": [b["_id"] for b in later]}})
    db.cost_profiles.insert_one({"_id": "market@1", **dataclasses.asdict(protocol.BASE_COST), "profile_id": "market"})
    db.risk_profiles.insert_one({"_id": "default@1", **dataclasses.asdict(PROFILE)})
    cal = build.run_calibration(db, now=NOW)
    o = build.build_outlook(db, now=EVENING, calibration=cal)
    assert o["asof"] == ASOF.isoformat()
    return later


def _restore(db, later):
    db.bars.insert_many(later)


def _row(db, symbol, side):
    return next(r for r in build.latest_outlook(db)["rows"] if r["symbol"] == symbol and r["side"] == side)


def test_paper_orders_follow_the_shared_simulator_and_reconcile_with_net_trade(db, world):
    broker.create_paper_account(db, account_id="agent", name="Agent", starting_cash=100_000.0,
                                risk_profile="default@1", now=EVENING)
    placed = []
    for sym, side in (("NVDA", "long"), ("SPY", "long"), ("INTC", "short"), ("QQQ", "short"), ("QQQM", "short")):
        r = _row(db, sym, side)
        res = broker.place_order(db, "agent", symbol=sym, side=side, qty=5, idempotency_key=f"k-{sym}",
                                 decided_by={"agent_id": "t"}, now=EVENING)
        placed.append((res["order"], r))
    again = broker.place_order(db, "agent", symbol="NVDA", side="long", qty=5, idempotency_key="k-NVDA",
                               decided_by={"agent_id": "t"}, now=EVENING)
    assert again["replayed"] and db.orders.count_documents({}) == 5
    _restore(db, world)
    out = broker.process_account(db, "agent", LATER)
    assert out["stalled"] is None and out["processed"][-1] == "2025-06-02"
    cost = broker._cost(db, db.accounts.find_one({"_id": "agent"}))
    statuses = sorted(db.orders.find_one({"_id": o["_id"]})["status"] for o, _ in placed)
    assert "closed" in statuses  # the reconciliation below must actually run
    assert db.orders.find_one({"side": "short", "status": "closed"})  # ...including a short (borrow fees)
    assert db.ledger_events.count_documents({"kind": "borrow_fee"}) > 0
    for order, row in placed:
        o = db.orders.find_one({"_id": order["_id"]})
        s = SymbolSeries.from_db(db, o["symbol"])
        plan = TradePlan(o["side"], ASOF, o["limit"], o["stop"], o["target"])
        ref = simulate_trade(plan, [b for b in s.bars_after(ASOF, 129) if b.session <= dt.date(2025, 6, 2)],
                             dt.date(2025, 4, 1), ExecutionPolicy())
        if ref.fill_session is None:
            assert o["status"] == "not_filled"
            continue
        assert o["fill_price"] == pytest.approx(ref.fill_price)
        if ref.exit_session is None:
            assert o["status"] == "filled"
            continue
        assert o["status"] == "closed" and o["result"] == ref.result
        # Cash effect of this order's executions and events == net_trade's net P&L.
        execs = list(db.executions.find({"order_id": o["_id"]}))
        flows = sum((-1 if x["side"] in ("buy", "cover") else 1) * x["qty"] * x["price"] - x["fees"] for x in execs)
        flows += sum(e["amount"] for e in db.ledger_events.find({"ref": {"$regex": f":{o['_id']}:"}}))
        nt = net_trade(ref, o["side"], o["qty"], cost, s.dividends_on_basis(ASOF))
        assert flows == pytest.approx(nt.net_return * ref.fill_price * o["qty"], rel=1e-9, abs=1e-6)
    eq = list(db.equity_curve.find({"account_id": "agent"}).sort("session", 1))
    assert eq[0]["session"].date() == dt.date(2025, 4, 1) and eq[-1]["session"].date() == dt.date(2025, 6, 2)
    st = ledger_state(db, "agent", LATER)
    assert eq[-1]["cash"] == pytest.approx(st.cash)
    n_exec = db.executions.count_documents({})
    assert broker.process_account(db, "agent", LATER)["processed"] == []          # idempotent
    assert db.executions.count_documents({}) == n_exec


def test_placement_rules(db, world):
    with _client(db) as c:
        c.post("/api/v1/accounts", json={"account_id": "real", "name": "Real"}, headers=H)
        body = {"symbol": "NVDA", "side": "long", "qty": 1, "idempotency_key": "abcdefgh", "rationale": "test"}
        assert c.post("/api/v1/accounts/real/orders", json=body, headers=H).status_code == 403
    broker.create_paper_account(db, account_id="p", name="P", starting_cash=10_000.0, risk_profile="default@1",
                                now=EVENING)
    with pytest.raises(broker.AccountError, match="risk limit"):
        broker.place_order(db, "p", symbol="NVDA", side="long", qty=10_000, idempotency_key="big-order",
                           decided_by={}, now=EVENING)
    with pytest.raises(broker.AccountError, match="window"):
        broker.place_order(db, "p", symbol="NVDA", side="long", qty=1, idempotency_key="too-late",
                           decided_by={}, now=dt.datetime(2025, 4, 1, 14, tzinfo=UTC))
    broker.place_order(db, "p", symbol="NVDA", side="long", qty=1, idempotency_key="first-one", decided_by={},
                       now=EVENING)
    with pytest.raises(broker.AccountError, match="already has an open order"):
        broker.place_order(db, "p", symbol="NVDA", side="long", qty=1, idempotency_key="second-one",
                           decided_by={}, now=EVENING)
    oid = str(db.orders.find_one({"idempotency_key": "first-one"})["_id"])
    assert broker.cancel_order(db, "p", oid, now=EVENING)["status"] == "cancelled"


def test_missing_bar_stalls_the_cursor(db, world):
    broker.create_paper_account(db, account_id="p", name="P", starting_cash=100_000.0, risk_profile="default@1",
                                now=EVENING)
    broker.place_order(db, "p", symbol="NVDA", side="long", qty=1, idempotency_key="nvda-long", decided_by={},
                       now=EVENING)
    hole = dt.datetime(2025, 4, 1, tzinfo=UTC)
    _restore(db, [b for b in world if not (b["symbol"] == "NVDA" and b["session"] == hole)])
    out = broker.process_account(db, "p", LATER)
    assert out["processed"] == [] and "NVDA has no bar for 2025-04-01" in out["stalled"]
    assert db.accounts.find_one({"_id": "p"})["stalled"]


def test_baseline_is_deterministic_and_respects_limits(db, world):
    broker.create_paper_account(db, account_id="base", name="Baseline", starting_cash=100_000.0,
                                risk_profile="default@1", policy=baseline.POLICY_ID, now=EVENING)
    first = baseline.run_baseline(db, "base", EVENING)
    second = baseline.run_baseline(db, "base", EVENING)
    assert [p["symbol"] for p in first["placed"]] and second["placed"] == []   # slots taken; nothing duplicated
    orders = list(db.orders.find({"account_id": "base"}))
    assert len(orders) <= baseline.MAX_POSITIONS
    for o in orders:
        assert o["qty"] * o["limit"] <= 0.10 * 100_000 + 1e-6 and o["decided_by"] == {"policy": baseline.POLICY_ID}
        r = _row(db, o["symbol"], o["side"])
        assert r["exp_excess_6m"] > 0
    exp = [o["exp_return_6m"] for o in sorted(orders, key=lambda o: o["placed_at"])]
    assert exp == sorted(exp, reverse=True)


# --- review fixes (PR #25) --------------------------------------------------------------------

def test_paper_ledgers_only_take_simulated_fills(db, world):
    from stocks_service.accounts import service
    broker.create_paper_account(db, account_id="p", name="P", starting_cash=10_000.0, risk_profile="default@1",
                                now=EVENING)
    with pytest.raises(service.AccountError, match="simulator"):
        service.add_executions(db, "p", [{"symbol": "SPY", "side": "buy", "qty": 1, "price": 1.0,
                                          "ts": EVENING}], now=EVENING)


def test_cluster_cap_counts_holdings_and_open_orders(db, world):
    db.risk_profiles.insert_one({"_id": "tight@1", **dataclasses.asdict(
        dataclasses.replace(PROFILE, profile_id="tight", max_cluster_pct=0.05))})
    db.symbols.update_many({"_id": {"$in": ["NVDA", "INTC"]}}, {"$set": {"groups": ["semis"]}})
    broker.create_paper_account(db, account_id="p", name="P", starting_cash=100_000.0, risk_profile="tight@1",
                                now=EVENING)
    nvda = _row(db, "NVDA", "long")["plan"]["entry_limit"]
    q = int(4_000 // nvda)
    broker.place_order(db, "p", symbol="NVDA", side="long", qty=q, idempotency_key="nvda-first", decided_by={},
                       now=EVENING)
    intc = _row(db, "INTC", "long")["plan"]["entry_limit"]
    with pytest.raises(broker.AccountError, match="cluster_cap\\(group:semis\\)"):
        broker.place_order(db, "p", symbol="INTC", side="long", qty=int(2_000 // intc) + 1,
                           idempotency_key="intc-second", decided_by={}, now=EVENING)


def test_shorts_need_a_borrow_rate_and_collateral(db, world):
    db.cost_profiles.insert_one({**db.cost_profiles.find_one({"_id": "market@1"}), "_id": "noshort@1",
                                 "profile_id": "noshort", "borrow_rate_annual": None})
    broker.create_paper_account(db, account_id="ns", name="NS", starting_cash=100_000.0, risk_profile="default@1",
                                cost_profile="noshort@1", now=EVENING)
    with pytest.raises(broker.AccountError, match="borrow rate"):
        broker.place_order(db, "ns", symbol="QQQ", side="short", qty=1, idempotency_key="qqq-short",
                           decided_by={}, now=EVENING)
    db.risk_profiles.insert_one({"_id": "wide@1", **dataclasses.asdict(dataclasses.replace(
        PROFILE, profile_id="wide", risk_per_trade=1.0, max_position_pct=1.0, max_short_pct=2.0, max_heat_pct=1.0,
        max_cluster_pct=1.0, max_gross=2.0, min_adv_usd=0.0))})
    broker.create_paper_account(db, account_id="small", name="S", starting_cash=1_000.0, risk_profile="wide@1",
                                now=EVENING)
    broker.place_order(db, "small", symbol="QQQ", side="short", qty=1, idempotency_key="qqq-short-one",
                       decided_by={}, now=EVENING)     # reserves ~$470 of margin (+ entry costs)
    qqqm = _row(db, "INTC", "short")["plan"]["entry_limit"]  # uncorrelated with QQQ: no cluster limit
    free = 1_000.0 - db.orders.find_one({"idempotency_key": "qqq-short-one"})["reservation"]
    too_many = int(free // qqqm) + 1
    assert too_many * qqqm < 1_000.0                  # within the position cap, beyond buying power
    with pytest.raises(broker.AccountError, match="buying power"):
        broker.place_order(db, "small", symbol="INTC", side="short", qty=too_many, idempotency_key="intc-short",
                           decided_by={}, now=EVENING)


def test_cancel_validates_ids_and_refuses_real_accounts(db, world):
    with _client(db) as c:
        c.post("/api/v1/accounts", json={"account_id": "real", "name": "Real"}, headers=H)
        assert c.delete("/api/v1/accounts/real/orders/not-an-id", headers=H).status_code == 422
        assert c.delete("/api/v1/accounts/real/orders/" + "a" * 24, headers=H).status_code == 403
