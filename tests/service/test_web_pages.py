import datetime as dt

import pytest

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
    assert "Veto (longs)" in page and "Veto (shorts)" in page and "Difference per label" in page


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


def test_baseline_pairing_requires_identical_conditions(db, world):  # noqa: F811
    from stocks_service.paper.report import compare, matching_baseline
    broker.create_paper_account(db, account_id="agent", name="A", starting_cash=100_000.0, risk_profile="default@1",
                                now=EVENING)
    agent = db.accounts.find_one({"_id": "agent"})
    assert matching_baseline(db, agent)[0] is None                                    # none yet
    broker.create_paper_account(db, account_id="small-base", name="B1", starting_cash=50_000.0,
                                risk_profile="default@1", policy=baseline.POLICY_ID, now=EVENING)
    assert matching_baseline(db, agent)[0] is None                                    # different capital
    assert compare(db, "agent", "small-base")["comparable"] is False
    for b in ("base-1", "base-2"):
        broker.create_paper_account(db, account_id=b, name=b, starting_cash=100_000.0, risk_profile="default@1",
                                    policy=baseline.POLICY_ID, now=EVENING)
    base, why = matching_baseline(db, agent)
    assert base is None and "ambiguous" in why
    with pytest.raises(broker.AccountError, match="same starting cash"):
        broker.create_paper_account(db, account_id="agent-2", name="A2", starting_cash=100_000.0,
                                    risk_profile="default@1", paired_baseline="small-base", now=EVENING)
    broker.create_paper_account(db, account_id="agent-3", name="A3", starting_cash=100_000.0,
                                risk_profile="default@1", paired_baseline="base-2", now=EVENING)
    assert matching_baseline(db, db.accounts.find_one({"_id": "agent-3"})) == ("base-2", "explicitly paired")
    with _client(db) as c:
        c.post("/login", data={"password": "pw"})
        page = c.get("/paper").text
    assert "ambiguous" in page and "agent-3 vs base-2" in page


def test_research_page_survives_undefined_cagr(db, world):  # noqa: F811
    db.overlay_evaluations.insert_one({"created_at": NOW, "strategy": "s@1", "overlay": "o@1", "window": ["a", "b"],
                                       "without": {"metrics": {"cagr": float("nan"), "max_drawdown": 1.0}, "trades": 1},
                                       "with": {"metrics": {"cagr": 0.01, "max_drawdown": 0.5}, "trades": 1},
                                       "paired_excess_annual": {"mean": 0.0, "ci95": [-0.1, 0.1]},
                                       "verdict": "no_added_value"})
    with _client(db) as c:
        c.post("/login", data={"password": "pw"})
        r = c.get("/research")
    assert r.status_code == 200 and "CAGR n/a" in r.text
