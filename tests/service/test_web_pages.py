import datetime as dt

from fastapi.testclient import TestClient

from stocks_service import cross_asset, umpires
from stocks_service.api.app import create_app
from stocks_service.paper import baseline, broker
from stocks_service.research import protocol, tuning
from stocks_service.research.overlays import evaluate_overlay
from stocks_service.settings import Settings

from .conftest import NOW
from .test_paper import EVENING, LATER, world  # noqa: F401  (fixture)


def _client(db):
    s = Settings(mongo_url="x", api_keys="k", admin_password="pw", session_secret="s" * 40)
    return TestClient(create_app(s, db=db), base_url="https://testserver")


def test_research_page_shows_lifecycle_overlays_tuning_and_umpires(db, world, monkeypatch):  # noqa: F811
    db.bars.insert_many(world)
    evaluate_overlay(db, strategy="ensemble@1", overlay=cross_asset.GroupConsensus({"NVDA": ["s"], "INTC": ["s"]}),
                     start=dt.date(2021, 6, 1), end=dt.date(2024, 11, 15), now=NOW)
    monkeypatch.setattr(tuning, "FIRST_TRAIN_YEARS", 1)
    monkeypatch.setattr(tuning, "FOLD_YEARS", 1)
    monkeypatch.setattr(tuning, "GRID", {"stop_atr": (2.0, 3.0), "target_atr": (4.0,)})
    tuning.tune(db, strategy="ma_crossover@1", start=dt.date(2021, 6, 1), end=dt.date(2024, 11, 15), now=NOW)
    umpires.train(db, now=NOW)
    with _client(db) as c:
        c.post("/login", data={"password": "pw"})
        page = c.get("/research").text
    assert "Strategy versions and live tracking" in page and "needs 30 resolved" in page
    assert "cross_asset@1(w=0.5) on ensemble@1" in page and "ATR stop/target tuning on ma_crossover@1" in page
    assert "Umpire veto (longs)" in page and "Umpire veto (shorts)" in page


def test_paper_page_shows_accounts_orders_and_the_gate(db, world):  # noqa: F811
    broker.create_paper_account(db, account_id="agent", name="AI agent", starting_cash=100_000.0,
                                risk_profile="default@1", now=EVENING)
    broker.create_paper_account(db, account_id="base", name="Baseline", starting_cash=100_000.0,
                                risk_profile="default@1", policy=baseline.POLICY_ID, now=EVENING)
    baseline.run_baseline(db, "base", EVENING)
    broker.place_order(db, "agent", symbol="QQQ", side="short", qty=5, idempotency_key="agent-qqq-1",
                       decided_by={"agent_id": "claude-test"}, now=EVENING)
    db.bars.insert_many(world)
    broker.process_account(db, "agent", LATER)
    broker.process_account(db, "base", LATER)
    with _client(db) as c:
        c.post("/login", data={"password": "pw"})
        page = c.get("/paper").text
    assert "agent vs base" in page and "Influence gate" in page and "shadow-only" in page
    assert "claude-test" in page and "baseline_v1@1" in page and "QQQ" in page
