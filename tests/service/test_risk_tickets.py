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
BEFORE_OPEN = dt.datetime(2025, 6, 3, 1, 0, tzinfo=UTC)  # after the 2025-06-02 close, before the next open
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
        # The API uses the real clock, long past this fixture outlook's deadline: everything is withheld.
        late = c.get("/api/v1/accounts/acct/tickets", headers=H).json()
        assert late["tickets"] == [] and all("placement window closed" in w["reason"] for w in late["withheld"])
        t = tickets.build_tickets(db, "acct", BEFORE_OPEN)
        assert t["tickets"] == [] and t["withheld"] and t["withheld"][0]["reason"] == "account has no risk profile"
        body = {**{k: v for k, v in dataclasses.asdict(PROFILE).items()}, "note": "test limits"}
        assert c.post("/api/v1/risk-profiles", json=body, headers=H).status_code == 201
        assert c.put("/api/v1/accounts/acct/risk-profile", json={"risk_profile": "default@1"}, headers=H).status_code == 200
        t = tickets.build_tickets(db, "acct", BEFORE_OPEN)
        shorts_withheld = [w for w in t["withheld"] if w["side"] == "short"]
        assert shorts_withheld and all(w["reason"] == "symbol is not marked shortable" for w in shorts_withheld)
        db.symbols.update_many({}, {"$set": {"shortable": True}})
        t = tickets.build_tickets(db, "acct", BEFORE_OPEN)
        assert t["tickets"], t["withheld"]
        for tk in t["tickets"]:
            assert tk["action"] in ("Buy", "Sell Short") and tk["order_type"] == "Limit" and tk["time_in_force"] == "Day"
            assert tk["quantity"] >= 1 and tk["estimated_cost"] <= 0.10 * 100_000 + 1e-6
            assert tk["max_loss_at_stop_with_gap"] <= 0.01 * 100_000 + 1e-6
            oco = tk["after_fill"]
            assert oco["type"] == "OCO" and len(oco["legs"]) == 2 and oco["time_in_force"] == "Good 'til Canceled"
            assert tk["grade"] == "A" and "126 sessions" in tk["timeout"]
            assert tk["limit_price"] == round(tk["limit_price"], 2)
            if tk["action"] == "Sell Short":
                assert "borrow" in tk["notes"][0] and oco["legs"][0]["action"] == "Buy to Cover"
        assert sum(tk["estimated_cost"] for tk in t["tickets"] if tk["action"] == "Sell Short") <= 0.2 * 100_000 + 1e-6
        # Pausing the strategy after the outlook was built withholds its tickets immediately.
        db.strategy_versions.update_many({}, {"$set": {"status": "paused"}})
        t = tickets.build_tickets(db, "acct", BEFORE_OPEN)
        assert t["tickets"] == [] and all("paused" in w["reason"] for w in t["withheld"])


def test_actions_validate_fills_and_levels_validate_holdings(db, monkeypatch):
    with _client(db) as c:
        _setup(db, c, monkeypatch, calibration.MIN_SKILL)
        asof = build.latest_outlook(db)["asof"]
        act = lambda **k: c.post("/api/v1/accounts/acct/actions", headers=H,  # noqa: E731
                                 json={"outlook_asof": asof, "symbol": "NVDA", "side": "long", **k})
        assert act(action="skipped").status_code == 409                     # needs a reason
        assert act(action="skipped", reason="too volatile").status_code == 201
        assert act(action="taken").status_code == 409                       # needs fills
        c.post("/api/v1/accounts/acct/executions", headers=H, json=[
            {"exec_id": "S1", "symbol": "SPY", "side": "buy", "qty": 1, "price": 590.0, "ts": "2025-06-03T14:00:00Z"},
            {"exec_id": "E1", "symbol": "NVDA", "side": "buy", "qty": 10, "price": 135.0, "ts": "2025-06-03T14:00:00Z"}])
        wrong = act(action="taken", exec_ids=["S1"])
        assert wrong.status_code == 409 and "not buy fills of NVDA" in wrong.text
        row = next(r for r in build.latest_outlook(db)["rows"] if r["symbol"] == "NVDA" and r["side"] == "long")
        assert act(action="taken", exec_ids=["E1"]).status_code == 201
        lv = db.position_levels.find_one({"account_id": "acct", "symbol": "NVDA", "active": True})
        assert lv["stop"] == row["plan"]["stop"] and lv["effective_session"].date() == dt.date(2025, 6, 3)
        assert lv["basis_session"].date() == dt.date(2025, 6, 2)
        # Levels need a holding in that direction; a wrong-side update leaves the existing protection alone.
        bad = c.put("/api/v1/accounts/acct/levels/NVDA", headers=H,
                    json={"side": "short", "stop": 200.0, "target": 100.0, "note": "wrong side"})
        assert bad.status_code == 409 and "holds a long position" in bad.text
        assert c.put("/api/v1/accounts/acct/levels/INTC", headers=H,
                     json={"side": "long", "stop": 10.0, "note": "nothing held"}).status_code == 409
        assert db.position_levels.find_one({"_id": lv["_id"]})["active"] is True
        assert c.put("/api/v1/accounts/acct/levels/NVDA", headers=H,
                     json={"side": "long", "stop": 50.0, "target": 40.0, "note": "bad"}).status_code == 409


def _hold(db, symbol, qty, ts):
    from stocks_service.accounts import service
    service.create_account(db, account_id="acct", name="A", now=NOW)
    service.add_executions(db, "acct", [{"symbol": symbol, "side": "buy", "qty": qty, "price": 1.0, "ts": ts}], now=NOW)


def test_alerts_scan_every_new_bar_once_and_ignore_strategy_status(db):
    _load_db(db)
    _hold(db, "SPY", 5, dt.datetime(2025, 2, 28, 15, tzinfo=UTC))
    bars = list(db.bars.find({"symbol": "SPY", "session": {"$gte": dt.datetime(2025, 3, 3, tzinfo=UTC)}}).sort("session", 1))
    m = min(range(len(bars)), key=lambda i: bars[i]["l"])   # the April 2025 sell-off low
    assert 2 <= m < len(bars) - 2
    mid, stop = bars[m], bars[m]["l"] + 0.005
    assert all(b["l"] > stop for i, b in enumerate(bars) if i != m)
    tickets.set_levels(db, "acct", symbol="SPY", side="long", stop=stop, target=None, source="test",
                       now=NOW, effective_session=dt.date(2025, 3, 3))
    # The first check sees only bars through the day before the breach; the next sees several new bars at once.
    later = [b for b in bars if b["session"] >= mid["session"]]
    db.bars.delete_many({"_id": {"$in": [b["_id"] for b in later]}})
    db.strategy_versions.update_many({}, {"$set": {"status": "paused"}})
    check_time = dt.datetime.combine(mid["session"].date(), dt.time(12), UTC)
    assert [n["type"] for n in tickets.check_protective(db, check_time)] == []
    db.bars.insert_many(later)
    new = tickets.check_protective(db, dt.datetime(2025, 6, 2, 23, tzinfo=UTC))
    assert [(n["type"], n["price_session"]) for n in new] == [("stop_crossed", mid["session"].date().isoformat())]
    assert tickets.check_protective(db, dt.datetime(2025, 6, 2, 23, tzinfo=UTC)) == []   # deduplicated


def test_levels_follow_splits(db):
    _load_db(db)
    _hold(db, "NVDA", 10, dt.datetime(2024, 6, 3, 15, tzinfo=UTC))
    # Set on the 2024-06-07 basis (pre-split ~1,200): a 1,000 stop is ~100 after the 10:1 split.
    tickets.set_levels(db, "acct", symbol="NVDA", side="long", stop=1000.0, target=2000.0, source="test", now=NOW,
                       basis_session=dt.date(2024, 6, 7), effective_session=dt.date(2024, 6, 10))
    db.bars.delete_many({"symbol": "NVDA", "session": {"$gt": dt.datetime(2024, 6, 21, tzinfo=UTC)}})
    lows = [b["l"] for b in db.bars.find({"symbol": "NVDA", "session": {"$gte": dt.datetime(2024, 6, 10, tzinfo=UTC)}})]
    assert min(lows) > 100.0  # raw prices stayed above the restated stop
    assert tickets.check_protective(db, dt.datetime(2024, 6, 21, 23, tzinfo=UTC)) == []


def test_timeout_and_missing_prices_come_from_the_calendar(db):
    _load_db(db)
    _hold(db, "SPY", 5, dt.datetime(2025, 4, 30, 15, tzinfo=UTC))
    tickets.set_levels(db, "acct", symbol="SPY", side="long", stop=1.0, target=None, source="test", now=NOW,
                       effective_session=dt.date(2025, 5, 1), timeout_session=dt.date(2025, 5, 30))
    db.bars.delete_many({"symbol": "SPY", "session": {"$gte": dt.datetime(2025, 5, 27, tzinfo=UTC)}})
    new = {n["type"]: n for n in tickets.check_protective(db, dt.datetime(2025, 6, 2, 23, tzinfo=UTC))}
    assert set(new) == {"timeout_due", "price_data_missing"}
    assert "2025-06-02" in new["price_data_missing"]["message"]
    assert tickets.last_completed_session(dt.datetime(2025, 6, 2, 20, 30, tzinfo=UTC)) == dt.date(2025, 5, 30)


def test_correlation_requires_every_session_of_the_window():
    uni = _universe()
    spy = uni["SPY"]
    from stocks_service.research.series import SymbolSeries
    gap = dt.date(2024, 8, 5)
    keep = [i for i, d in enumerate(spy.sessions) if d != gap]
    holed = SymbolSeries("SPY", [spy.sessions[i] for i in keep], [spy.raw[i] for i in keep], spy.splits, spy.dividends)
    c = correlation_clusters({**uni, "SPY": holed}, ["SPY", "QQQ", "QQQM"], dt.date(2024, 11, 15), 0.8)
    assert "SPY" not in c and c["QQQ"] == c["QQQM"]  # a missing interior session excludes SPY, not misaligns it


def test_sizing_uses_cent_prices_and_rejects_levels_that_collapse():
    q, why, limits = size_ticket(_row(entry=100.004, stop=96.004, target=108.004), Book(100_000, 100_000),
                                 dataclasses.replace(PROFILE, max_position_pct=1.0), keys=set(), adv_usd=1e12,
                                 shortable=True)
    assert limits["risk_per_trade"] == pytest.approx(1000 / (100.0 - 96.0 + 2.0))
    q, why, _ = size_ticket(_row(entry=10.001, stop=9.999, target=10.004, atr=0.01), Book(100_000, 100_000),
                            PROFILE, keys=set(), adv_usd=1e12, shortable=True)
    assert q == 0 and "rounding" in why[0]
