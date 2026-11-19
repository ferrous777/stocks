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
        detail = c.get("/paper/agent").text
        base = c.get("/paper/base").text
        assert c.get("/paper/nope").status_code == 404
    assert "agent vs base" in page and "Influence gate" in page and "shadow-only" in page
    assert 'href="/paper/agent"' in page and 'href="/paper/base"' in page   # leaderboard links to each account
    # The account page: summary, equity chart data, orders (with who decided), transactions, the baseline comparison.
    assert "claude-test" in detail and "QQQ" in detail and 'id="equity-history"' in detail
    assert 'data-chart-modes="range"' in detail and "Against <a href=\"/paper/base\">base</a>" in detail
    assert "opening balance" in detail and ">short<" in detail
    assert "baseline_v1@1" in base and "Compared with the baseline" not in base   # a baseline has no baseline


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


def test_transactions_page_through_every_entry_exactly_once(db, world):  # noqa: F811
    """Many fills share a timestamp (entries at the same open); the cursor must not skip or repeat any."""
    from stocks_service.paper import read
    broker.create_paper_account(db, account_id="base", name="Baseline", starting_cash=100_000.0,
                                risk_profile="default@1", policy=baseline.POLICY_ID, now=EVENING)
    baseline.run_baseline(db, "base", EVENING)
    db.bars.insert_many(world)
    broker.process_account(db, "base", LATER)
    everything = read.transactions(db, "base", limit=500)
    assert everything["next_cursor"] is None
    n = len(everything["transactions"])
    assert n == db.executions.count_documents({"account_id": "base"}) + db.ledger_events.count_documents({"account_id": "base"})
    ts = [t["ts"] for t in everything["transactions"]]
    assert ts == sorted(ts, reverse=True) and len(set(ts)) < n   # newest first, with ties to page across
    seen, cursor = [], None
    while True:
        page = read.transactions(db, "base", limit=2, cursor=cursor)
        seen += page["transactions"]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert seen == everything["transactions"]
    with _client(db) as c:
        api = c.get("/api/v1/accounts/base/transactions", params={"limit": 3}, headers={"X-API-Key": "k"}).json()
        assert api["transactions"] == everything["transactions"][:3] and api["next_cursor"]
        assert c.get("/api/v1/accounts/base/transactions", params={"cursor": "junk"},
                     headers={"X-API-Key": "k"}).status_code == 422
        assert c.get("/api/v1/accounts/nope/transactions", headers={"X-API-Key": "k"}).status_code == 404


def test_link_builders_match_the_pages_and_chart_views():
    from stocks_service.web import links
    assert links.symbol("NVDA") == "/symbol/NVDA"
    assert links.symbol("BRK.B", range="5Y") == "/symbol/BRK.B?range=5Y"
    assert links.symbol("^IRX", from_year=2020) == "/symbol/%5EIRX?from=2020"
    assert links.symbol("NVDA", compare=[2022, 2020, 2021, 2021]) == "/symbol/NVDA?compare=2020,2021,2022"
    for bad in ({"range": "2Y"}, {"range": "1Y", "from_year": 2020}, {"compare": list(range(2010, 2020))}):
        with pytest.raises(ValueError):
            links.symbol("NVDA", **bad)
    assert links.outlook("short") == "/outlook?side=short" and links.outlook() == "/outlook"
    assert links.account("fidelity", "real") == "/accounts/fidelity" and links.account("paper-x", "paper") == "/paper/paper-x"
    assert links.absolute("https://h.example/", "/paper") == "https://h.example/paper"
    assert {c["page"] for c in links.CATALOG} >= {"symbol", "paper_account", "account", "outlook"}


def test_transactions_include_splits_that_changed_holdings(db, world):  # noqa: F811
    """The ledger applies splits from corporate actions (not ledger events); the history must show them."""
    from stocks_service.accounts import service
    from stocks_service.paper import read
    assert db.corporate_actions.find_one({"symbol": "NVDA", "type": "split"})
    service.create_account(db, account_id="fidelity", name="F", now=NOW)
    service.upload_snapshot(db, "fidelity", as_of=dt.datetime(2024, 6, 3, 21, tzinfo=dt.timezone.utc), cash=100.0,
                            positions=[{"symbol": "NVDA", "qty": 10, "avg_cost": 1000.0}], opening=True, now=NOW)
    tx = read.transactions(db, "fidelity", now=NOW)["transactions"]
    splits = [t for t in tx if t["type"] == "split"]
    assert [(s["symbol"], s["qty"], s["ratio"], s["ex_date"]) for s in splits] == [("NVDA", 90.0, 10.0, "2024-06-10")]
    assert [t["type"] for t in tx] == ["split", "opening_balance", "opening_balance"]   # newest first
    # Paging still visits every row exactly once.
    seen, cursor = [], None
    while True:
        page = read.transactions(db, "fidelity", limit=1, cursor=cursor, now=NOW)
        seen += page["transactions"]
        if not (cursor := page["next_cursor"]):
            break
    assert seen == tx
    # Splits before the account held the symbol are not its transactions.
    assert not [t for t in tx if t["type"] == "split" and t["ex_date"] < "2024-06-03"]


def test_account_page_can_show_the_full_order_history(db, world):  # noqa: F811
    from stocks_service.web import data
    broker.create_paper_account(db, account_id="base", name="Baseline", starting_cash=100_000.0,
                                risk_profile="default@1", policy=baseline.POLICY_ID, now=EVENING)
    baseline.run_baseline(db, "base", EVENING)
    capped = data.paper_account(db, "base", now=LATER, limit=2)
    assert len(capped["orders"]) == 2 and capped["order_count"] == 4
    full = data.paper_account(db, "base", now=LATER, limit=None)
    assert len(full["orders"]) == 4 and full["tx"]["next_cursor"] is None
    with _client(db) as c:
        c.post("/login", data={"password": "pw"})
        page = c.get("/paper/base", params={"history": "all"}).text
    assert page.count('<td class="small">2025-03-31 23:00</td>') == 4


def test_transactions_replay_history_only_when_a_split_applies(db, world, monkeypatch):  # noqa: F811
    from stocks_service.accounts import service
    from stocks_service.paper import read
    from stocks_service.web import data
    service.create_account(db, account_id="nosplit", name="N", now=NOW)
    service.upload_snapshot(db, "nosplit", as_of=dt.datetime(2024, 6, 3, 21, tzinfo=dt.timezone.utc), cash=100.0,
                            positions=[{"symbol": "SPY", "qty": 1, "avg_cost": 500.0}], opening=True, now=NOW)

    def boom(*a, **k):
        raise AssertionError("history replayed without an applicable split")
    monkeypatch.setattr(service, "_history", boom)
    assert len(read.transactions(db, "nosplit", now=NOW)["transactions"]) == 2
    # Reading the full history derives split rows once, not once per page.
    monkeypatch.undo()
    calls = []
    real = read.split_rows
    monkeypatch.setattr(read, "split_rows", lambda *a, **k: calls.append(1) or real(*a, **k))
    service.create_account(db, account_id="held", name="H", now=NOW)
    service.upload_snapshot(db, "held", as_of=dt.datetime(2024, 6, 3, 21, tzinfo=dt.timezone.utc), cash=100.0,
                            positions=[{"symbol": "NVDA", "qty": 10, "avg_cost": 1000.0}], opening=True, now=NOW)
    full = data._all_transactions(db, "held", NOW)
    assert calls == [1] and [t["type"] for t in full["transactions"]][0] == "split"
