import dataclasses
import datetime as dt

import pytest
from fastapi.testclient import TestClient

from stocks_service.accounts import tickets
from stocks_service.accounts.risk import Book, RiskProfile, correlation_clusters, size_ticket
from stocks_service.api.app import create_app
from stocks_service.outlook import build, calibration
from stocks_service.research import protocol
from stocks_service.settings import Settings

from .conftest import NOW
from .test_research import _load_db, _universe

UTC = dt.timezone.utc
H = {"X-API-Key": "k"}
PROFILE = RiskProfile("default", 1, risk_per_trade=0.01, max_position_pct=0.10, max_cluster_pct=0.25,
                      max_heat_pct=0.06, gap_stress_atr=1.0, max_gross=1.0, max_short_pct=0.2, corr_threshold=0.8,
                      min_adv_usd=1e6, max_adv_pct=0.01)


def _row(side="long", entry=100.0, stop=96.0, target=108.0, atr=2.0):
    return {"side": side, "plan": {"entry_limit": entry, "stop": stop, "target": target, "atr": atr}}


def test_each_constraint_can_bind():
    big = 1e12
    # risk per trade: loss/share = 4 + 1x2 = 6 -> 1% of 100k / 6 = 166
    q, why, _ = size_ticket(_row(), Book(100_000, 100_000), PROFILE, keys=set(), adv_usd=big, shortable=True)
    assert (q, why) == (100, ["sized by position_cap"])          # 10% / $100 = 100 < 166
    wide = dataclasses.replace(PROFILE, max_position_pct=1.0)
    assert size_ticket(_row(), Book(100_000, 100_000), wide, keys=set(), adv_usd=big, shortable=True)[:2] == (
        166, ["sized by risk_per_trade"])
    assert size_ticket(_row(), Book(100_000, 3_000), wide, keys=set(), adv_usd=big, shortable=True)[:2] == (
        30, ["sized by cash"])
    # A third correlated position: the cluster already holds 24k of the 25k cap.
    b = Book(100_000, 100_000, clusters={"corr:0": 24_000.0})
    assert size_ticket(_row(), b, wide, keys={"corr:0"}, adv_usd=big, shortable=True)[:2] == (
        10, ["sized by cluster_cap(corr:0)"])
    full = Book(100_000, 100_000, heat=6_000.0)
    q, why, _ = size_ticket(_row(), full, wide, keys=set(), adv_usd=big, shortable=True)
    assert q == 0 and "heat_cap" in why[0]
    assert size_ticket(_row("short", 100, 104, 92), Book(100_000, 0), wide, keys=set(), adv_usd=big,
                       shortable=False)[1] == ["symbol is not marked shortable"]
    assert "below" in size_ticket(_row(), Book(100_000, 100_000), wide, keys=set(), adv_usd=5e5, shortable=True)[1][0]
    b = Book(100_000, 100_000)
    size_ticket(_row(), b, PROFILE, keys={"g"}, adv_usd=big, shortable=True)
    assert (b.gross, b.cash, b.clusters["g"], b.heat) == (10_000.0, 90_000.0, 10_000.0, 600.0)  # book updated


def test_correlation_clusters_on_real_returns():
    uni = _universe()
    c = correlation_clusters(uni, ["SPY", "QQQ", "QQQM", "NVDA", "INTC"], dt.date(2024, 11, 15), 0.8)
    assert c["SPY"] == c["QQQ"] == c["QQQM"]
    assert c["INTC"] != c["SPY"]


def _client(db):
    s = Settings(mongo_url="x", api_keys="k", admin_password="pw", session_secret="s" * 40)
    return TestClient(create_app(s, db=db), base_url="https://testserver")


def _setup(db, c, monkeypatch, skill):
    _load_db(db)
    protocol.seal_holdout(db, start=dt.date(2024, 11, 18), end=dt.date(2025, 5, 30), now=NOW)
    db.cost_profiles.insert_one({"_id": "market@1", **dataclasses.asdict(protocol.BASE_COST), "profile_id": "market"})
    monkeypatch.setattr(calibration, "MIN_SKILL", skill)
    cal = build.run_calibration(db, now=NOW)
    build.build_outlook(db, now=NOW, calibration=cal)
    c.post("/api/v1/accounts", json={"account_id": "acct", "name": "A"}, headers=H)
    c.post("/api/v1/accounts/acct/snapshots", headers=H,
           json={"as_of": "2025-06-02T21:00:00Z", "cash": 100_000, "positions": []})


def test_activation_gate_no_tickets_without_an_active_strategy(db, monkeypatch):
    with _client(db) as c:
        _setup(db, c, monkeypatch, calibration.MIN_SKILL)
        t = c.get("/api/v1/accounts/acct/tickets", headers=H).json()
        assert t["tickets"] == [] and "active" in t["note"]


def test_active_strategy_produces_sized_fidelity_tickets(db, monkeypatch):
    with _client(db) as c:
        # Test configuration: accept any skill so buckets publish, then mark their strategies active.
        _setup(db, c, monkeypatch, -1.0)
        o = build.latest_outlook(db)
        signalled = {s["strategy"] for r in o["rows"] for s in r["signals"]}
        assert signalled
        db.strategy_versions.update_many({"_id": {"$in": list(signalled)}}, {"$set": {"status": "active"}},
                                         upsert=False)
        for k in signalled:
            db.strategy_versions.update_one({"_id": k}, {"$set": {"status": "active"}}, upsert=True)
        build.build_outlook(db, now=NOW + dt.timedelta(seconds=1))
        t = c.get("/api/v1/accounts/acct/tickets", headers=H).json()
        assert t["tickets"] == [] and t["withheld"] and t["withheld"][0]["reason"] == "account has no risk profile"
        body = {**{k: v for k, v in dataclasses.asdict(PROFILE).items()}, "note": "test limits"}
        assert c.post("/api/v1/risk-profiles", json=body, headers=H).status_code == 201
        assert c.put("/api/v1/accounts/acct/risk-profile", json={"risk_profile": "default@1"}, headers=H).status_code == 200
        t = c.get("/api/v1/accounts/acct/tickets", headers=H).json()
        shorts_withheld = [w for w in t["withheld"] if w["side"] == "short"]
        assert shorts_withheld and all(w["reason"] == "symbol is not marked shortable" for w in shorts_withheld)
        db.symbols.update_many({}, {"$set": {"shortable": True}})
        t = c.get("/api/v1/accounts/acct/tickets", headers=H).json()
        assert t["tickets"], t["withheld"]
        for tk in t["tickets"]:
            assert tk["action"] in ("Buy", "Sell Short") and tk["order_type"] == "Limit" and tk["time_in_force"] == "Day"
            assert tk["quantity"] >= 1 and tk["estimated_cost"] <= 0.10 * 100_000 + 1e-6
            assert tk["max_loss_at_stop_with_gap"] <= 0.01 * 100_000 + 1e-6
            assert len(tk["after_fill"]) == 2 and tk["grade"] == "A"
            if tk["action"] == "Sell Short":
                assert "borrow" in tk["notes"][0] and tk["after_fill"][0]["action"] == "Buy to Cover"
        assert sum(tk["estimated_cost"] for tk in t["tickets"] if tk["action"] == "Sell Short") <= 0.2 * 100_000 + 1e-6


def test_actions_levels_and_protective_alerts_survive_strategy_pause(db, monkeypatch):
    with _client(db) as c:
        _setup(db, c, monkeypatch, calibration.MIN_SKILL)
        asof = build.latest_outlook(db)["asof"]
        row = next(r for r in build.latest_outlook(db)["rows"] if r["symbol"] == "NVDA" and r["side"] == "long")
        skip = c.post("/api/v1/accounts/acct/actions", headers=H, json={
            "outlook_asof": asof, "symbol": "NVDA", "side": "long", "action": "skipped"})
        assert skip.status_code == 409 and "reason" in skip.text
        assert c.post("/api/v1/accounts/acct/actions", headers=H, json={
            "outlook_asof": asof, "symbol": "NVDA", "side": "long", "action": "taken"}).status_code == 409
        c.post("/api/v1/accounts/acct/executions", headers=H, json=[
            {"exec_id": "E1", "symbol": "NVDA", "side": "buy", "qty": 10, "price": 135.0, "ts": "2025-06-03T14:00:00Z"}])
        taken = c.post("/api/v1/accounts/acct/actions", headers=H, json={
            "outlook_asof": asof, "symbol": "NVDA", "side": "long", "action": "taken", "exec_ids": ["E1"]}).json()
        assert taken["row"]["plan"]["stop"] == row["plan"]["stop"]
        lv = db.position_levels.find_one({"account_id": "acct", "symbol": "NVDA", "active": True})
        assert lv["stop"] == row["plan"]["stop"] and lv["timeout_session"] is not None
        # Every strategy paused: protection still runs. A real later bar trades through the stop.
        db.strategy_versions.update_many({}, {"$set": {"status": "paused"}})
        db.position_levels.update_one({"_id": lv["_id"]}, {"$set": {"stop": 1e6}})  # long stop above the price
        new = tickets.check_protective(db, NOW)
        assert [n["type"] for n in new] == ["stop_crossed"] and "Check that the stop order filled" in new[0]["message"]
        assert tickets.check_protective(db, NOW) == []  # deduplicated
        notes = c.get("/api/v1/notifications?account_id=acct", headers=H).json()
        assert len(notes) == 1
        c.post("/login", data={"password": "pw"})
        page = c.get("/accounts/acct").text
        assert "traded through your stop" in page and "Order tickets for the next session" in page and "active" in page
        assert c.post(f"/api/v1/notifications/{notes[0]['id']}/ack", headers=H).status_code == 200
        assert c.get("/api/v1/notifications?account_id=acct", headers=H).json() == []
        # Manual levels on a holding with no strategy at all (e.g. an opening balance).
        r = c.put("/api/v1/accounts/acct/levels/NVDA", headers=H,
                  json={"side": "long", "stop": 50.0, "target": 40.0, "note": "bad"})
        assert r.status_code == 409
        assert c.put("/api/v1/accounts/acct/levels/NVDA", headers=H,
                     json={"side": "long", "stop": 50.0, "target": 1e6, "note": "my own levels"}).status_code == 200
        assert db.position_levels.count_documents({"account_id": "acct", "active": True}) == 1
