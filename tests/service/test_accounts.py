import datetime as dt

import pytest
from fastapi.testclient import TestClient

from stocks_service.accounts.ledger import CASH, Execution, LedgerEvent, state_as_of
from stocks_service.api.app import create_app
from stocks_service.settings import Settings

from .conftest import NOW
from .test_research import _load_db

UTC = dt.timezone.utc
T = lambda *a: dt.datetime(*a, tzinfo=UTC)  # noqa: E731


# --- pure ledger -------------------------------------------------------------------------

def test_average_cost_realized_pnl_fees_and_cash():
    ev = [LedgerEvent(T(2024, 1, 2), "opening_balance", None, amount=10_000.0)]
    xs = [Execution(T(2024, 1, 3, 15), "AAA", "buy", 10, 100.0, 1.0),
          Execution(T(2024, 1, 4, 15), "AAA", "buy", 10, 110.0, 1.0),
          Execution(T(2024, 1, 5, 15), "AAA", "sell", 5, 120.0, 1.0)]
    st = state_as_of(T(2024, 2, 1), ev, xs, {})
    h = st.holdings["AAA"]
    assert h.qty == 15 and h.avg_cost == pytest.approx(105.0)
    assert h.realized == pytest.approx(5 * (120 - 105)) and h.fees == 3.0
    assert st.cash == pytest.approx(10_000 - 1000 - 1100 + 600 - 3)
    assert state_as_of(T(2024, 1, 4), ev, xs, {}).qty("AAA") == 10  # as-of excludes later fills


def test_short_cover_and_flip_through_zero():
    xs = [Execution(T(2024, 1, 3, 15), "BBB", "short", 10, 50.0),
          Execution(T(2024, 1, 4, 15), "BBB", "cover", 4, 40.0),
          Execution(T(2024, 1, 5, 15), "BBB", "buy", 10, 45.0)]   # covers 6, then long 4
    st = state_as_of(T(2024, 2, 1), [], xs, {})
    h = st.holdings["BBB"]
    assert h.realized == pytest.approx(4 * 10 + 6 * 5)
    assert h.qty == pytest.approx(4) and h.avg_cost == pytest.approx(45.0)
    assert st.cash == pytest.approx(500 - 160 - 450)


def test_split_scales_quantity_at_the_ex_date_open_and_keeps_cost():
    ev = [LedgerEvent(T(2024, 6, 7, 21), "opening_balance", "NVDA", qty=10, cost_basis=12_000.0)]
    splits = {"NVDA": [(dt.date(2024, 6, 10), 10.0)]}
    assert state_as_of(T(2024, 6, 10, 13), ev, [], splits).qty("NVDA") == 10        # before the open
    after = state_as_of(T(2024, 6, 10, 20), ev, [], splits).holdings["NVDA"]
    assert after.qty == 100 and after.basis == 12_000.0 and after.avg_cost == pytest.approx(120.0)


def test_transfer_out_leaves_at_average_cost():
    ev = [LedgerEvent(T(2024, 1, 2), "opening_balance", "AAA", qty=10, cost_basis=1000.0),
          LedgerEvent(T(2024, 1, 3), "transfer_out", "AAA", qty=-4, cost_basis=0.0)]
    h = state_as_of(T(2024, 2, 1), ev, [], {}).holdings["AAA"]
    assert h.qty == 6 and h.avg_cost == pytest.approx(100.0) and h.realized == 0


def test_execution_validation():
    with pytest.raises(ValueError):
        Execution(T(2024, 1, 3), "AAA", "hold", 1, 1.0)
    with pytest.raises(ValueError):
        Execution(T(2024, 1, 3), "AAA", "buy", 0, 1.0)


# --- API flow --------------------------------------------------------------------------------

def _client(db):
    s = Settings(mongo_url="x", api_keys="k", admin_password="pw", session_secret="s" * 40)
    return TestClient(create_app(s, db=db), base_url="https://testserver")


H = {"X-API-Key": "k"}


def test_real_account_lifecycle(db):
    _load_db(db)  # real bars and the NVDA 10:1 split (2024-06-10)
    with _client(db) as c:
        assert c.post("/api/v1/accounts", json={"account_id": "fidelity", "name": "Fidelity"}, headers=H).status_code == 201
        assert c.post("/api/v1/accounts", json={"account_id": "fidelity", "name": "x"}, headers=H).status_code == 409
        # Opening snapshot needs a cost basis.
        bad = c.post("/api/v1/accounts/fidelity/snapshots", headers=H,
                     json={"as_of": "2024-06-07T21:00:00Z", "cash": 5000, "positions": [{"symbol": "NVDA", "qty": 10}]})
        assert bad.status_code == 409 and "avg_cost" in bad.text
        r = c.post("/api/v1/accounts/fidelity/snapshots", headers=H, json={
            "as_of": "2024-06-07T21:00:00Z", "cash": 5000,
            "positions": [{"symbol": "NVDA", "qty": 10, "avg_cost": 900.0}, {"symbol": "INTC", "qty": 100, "avg_cost": 30.0}]})
        assert r.status_code == 201
        out = r.json()
        assert out["snapshot"]["opening"] and out["breaks"] == []
        assert db.ledger_events.count_documents({"account_id": "fidelity", "kind": "opening_balance"}) == 3
        # Fills after the opening balance; a fill at/before it is refused (it is already in the balance).
        early = [{"symbol": "INTC", "side": "sell", "qty": 10, "price": 31.0, "ts": "2024-06-07T15:00:00Z"}]
        assert c.post("/api/v1/accounts/fidelity/executions", json=early, headers=H).status_code == 409
        fills = [{"exec_id": "F1", "symbol": "INTC", "side": "sell", "qty": 40, "price": 31.0, "fees": 0.05,
                  "ts": "2024-06-11T15:00:00Z"}]
        assert c.post("/api/v1/accounts/fidelity/executions", json=fills, headers=H).json()["inserted"] == 1
        assert c.post("/api/v1/accounts/fidelity/executions", json=fills, headers=H).json()["duplicates"] == 1
        # Snapshot after the split and the sale: matches the ledger exactly -> no breaks.
        cash = 5000 + 40 * 31.0 - 0.05
        ok = c.post("/api/v1/accounts/fidelity/snapshots", headers=H, json={
            "as_of": "2024-06-12T21:00:00Z", "cash": cash,
            "positions": [{"symbol": "NVDA", "qty": 100}, {"symbol": "INTC", "qty": 60}]}).json()
        assert ok["breaks"] == [] and not ok["snapshot"]["opening"]
        # A snapshot with an unrecorded sale and a cash deposit -> breaks, not trades.
        r = c.post("/api/v1/accounts/fidelity/snapshots", headers=H, json={
            "as_of": "2024-06-14T21:00:00Z", "cash": cash + 500 + 20 * 32.0,
            "positions": [{"symbol": "NVDA", "qty": 100}, {"symbol": "INTC", "qty": 40}]}).json()
        brk = {b["symbol"]: b for b in r["breaks"]}
        assert set(brk) == {"INTC", CASH} and brk["INTC"]["diff"] == -20
        assert db.executions.count_documents({"account_id": "fidelity"}) == 1
        # The missing fill arrives later: it explains the INTC break and part of the cash.
        c.post("/api/v1/accounts/fidelity/executions", headers=H,
               json=[{"exec_id": "F2", "symbol": "INTC", "side": "sell", "qty": 20, "price": 32.0, "ts": "2024-06-13T15:00:00Z"}])
        brk = {b["symbol"]: b for b in c.get("/api/v1/accounts/fidelity/breaks", headers=H).json()}
        assert brk["INTC"]["status"] == "resolved" and brk["INTC"]["resolution"]["type"] == "executions"
        assert brk[CASH]["status"] == "open" and brk[CASH]["diff"] == pytest.approx(500)
        # The deposit is resolved explicitly; it writes a ledger event and closes the break.
        res = c.post(f"/api/v1/breaks/{brk[CASH]['id']}/resolve", headers=H,
                     json={"kind": "transfer_in", "note": "deposit from checking"}).json()
        assert res["event"]["amount"] == pytest.approx(500)
        assert c.get("/api/v1/accounts/fidelity/breaks?status=open", headers=H).json() == []
        assert c.post(f"/api/v1/breaks/{brk[CASH]['id']}/resolve", headers=H,
                      json={"kind": "transfer_in", "note": "again"}).status_code == 409
        # Holdings: split-adjusted quantity, average cost, marks from the stored closes.
        pos = c.get("/api/v1/accounts/fidelity/positions", headers=H).json()
        p = {x["symbol"]: x for x in pos["positions"]}
        assert p["NVDA"]["qty"] == 100 and p["NVDA"]["avg_cost"] == pytest.approx(90.0)
        assert p["INTC"]["qty"] == 40 and p["INTC"]["realized"] == pytest.approx(40 * 1.0 + 20 * 2.0)
        last = db.bars.find_one({"symbol": "NVDA", "interval": "1d"}, sort=[("session", -1)])["c"]
        assert p["NVDA"]["market_value"] == pytest.approx(100 * last)
        assert pos["cash"] == pytest.approx(cash + 500 + 640) and pos["open_breaks"] == 0
        # Outlook needs a market outlook first.
        assert c.get("/api/v1/accounts/fidelity/outlook", headers=H).status_code == 404
        assert c.post("/api/v1/accounts/nope/snapshots", headers=H,
                      json={"as_of": "2024-06-14T21:00:00Z", "cash": 1}).status_code == 404


def test_position_transfer_in_uses_snapshot_cost_and_naive_timestamps_are_rejected(db):
    _load_db(db)
    with _client(db) as c:
        c.post("/api/v1/accounts", json={"account_id": "ira", "name": "IRA"}, headers=H)
        c.post("/api/v1/accounts/ira/snapshots", headers=H, json={"as_of": "2024-06-03T21:00:00Z", "cash": 100})
        r = c.post("/api/v1/accounts/ira/snapshots", headers=H, json={
            "as_of": "2024-06-05T21:00:00Z", "cash": 100, "positions": [{"symbol": "SPY", "qty": 5, "avg_cost": 400.0}]}).json()
        b = r["breaks"][0]
        assert (b["symbol"], b["diff"]) == ("SPY", 5)
        c.post(f"/api/v1/breaks/{b['id']}/resolve", headers=H, json={"kind": "transfer_in", "note": "ACAT from old broker"})
        p = c.get("/api/v1/accounts/ira/positions", headers=H).json()["positions"][0]
        assert p["qty"] == 5 and p["avg_cost"] == pytest.approx(400.0)
        naive = c.post("/api/v1/accounts/ira/executions", headers=H,
                       json=[{"symbol": "SPY", "side": "buy", "qty": 1, "price": 500, "ts": "2024-06-06T15:00:00"}])
        assert naive.status_code == 409 and "timezone" in naive.text


def test_account_pages_and_pasted_json_upload(db):
    _load_db(db)
    with _client(db) as c:
        c.post("/login", data={"password": "pw"})
        assert "No accounts yet" in c.get("/accounts").text
        r = c.post("/accounts", data={"account_id": "brokerage", "name": "Brokerage"}, follow_redirects=False)
        assert r.headers["location"] == "/accounts/brokerage"
        page = c.post("/accounts/brokerage/upload", data={"kind": "snapshot", "payload": '{"as_of": "2024-06-03T21:00:00Z", '
                      '"cash": 1000, "positions": [{"symbol": "SPY", "qty": 2, "avg_cost": 500}]}'}).text
        assert "Opening balance recorded" in page and "SPY" in page
        bad = c.post("/accounts/brokerage/upload", data={"kind": "executions", "payload": "[{not json"}).text
        assert "Not saved" in bad and "{not json" in bad  # the draft is kept for correction
        ok = c.post("/accounts/brokerage/upload", data={"kind": "executions", "payload":
                    '[{"symbol": "SPY", "side": "sell", "qty": 1, "price": 530, "ts": "2024-06-05T15:00:00Z"}]'}).text
        assert "1 fill(s) recorded" in ok
        assert c.get("/accounts/missing").status_code == 404
        assert c.post("/accounts/missing/upload", data={"kind": "snapshot", "payload":
                      '{"as_of": "2024-06-03T21:00:00Z", "cash": 1}'}).status_code == 404
