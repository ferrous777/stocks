import datetime as dt
import json

from fastapi.testclient import TestClient

from stocks_service.api.app import create_app
from stocks_service.paper import broker, report
from stocks_service.settings import Settings

import pytest

from .test_paper import EVENING, LATER, world  # noqa: F401  (fixture)

H = {"Authorization": "Bearer k", "Accept": "application/json, text/event-stream",
     "Content-Type": "application/json"}
IDENT = {"agent_id": "claude-test", "model_id": "claude-opus-5-5", "prompt_version": "v1"}


def _rpc(c, method, params=None, headers=H, rid=1):
    r = c.post("/mcp/", headers=headers, content=json.dumps({"jsonrpc": "2.0", "id": rid, "method": method,
                                                              "params": params or {}}))
    return r


def _call(c, tool, **args):
    r = _rpc(c, "tools/call", {"name": tool, "arguments": args})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "result" in body, body
    res = body["result"]
    if res.get("isError"):
        return res["content"][0]["text"], True
    sc = res.get("structuredContent")
    return (sc.get("result", sc) if sc else json.loads(res["content"][0]["text"])), False


def _client(db):
    s = Settings(mongo_url="x", api_keys="k", admin_password="pw", session_secret="s" * 40)
    return TestClient(create_app(s, db=db), base_url="https://testserver")


def test_mcp_requires_a_bearer_api_key(db):
    with _client(db) as c:
        assert _rpc(c, "tools/list", headers={**H, "Authorization": "Bearer nope"}).status_code == 401
        assert _rpc(c, "tools/list", headers={k: v for k, v in H.items() if k != "Authorization"}).status_code == 401
        init = _rpc(c, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                      "clientInfo": {"name": "test", "version": "0"}})
        assert init.status_code == 200 and init.json()["result"]["serverInfo"]["name"] == "stocks-paper"
        tools = {t["name"] for t in _rpc(c, "tools/list").json()["result"]["tools"]}
        bare = c.post("/mcp", headers=H, follow_redirects=False,
                      content=json.dumps({"jsonrpc": "2.0", "id": 9, "method": "tools/list", "params": {}}))
        assert bare.status_code == 200  # served directly, no redirect
        assert tools == {"get_outlook", "get_prediction", "get_watchlist", "add_to_watchlist", "remove_from_watchlist",
                         "list_accounts", "get_account", "get_performance", "list_orders", "list_transactions",
                         "upload_holdings", "place_paper_order", "cancel_order", "get_links"}


def test_agent_trades_a_paper_account_and_every_call_is_logged(db, world, monkeypatch):  # noqa: F811
    broker.create_paper_account(db, account_id="agent", name="Agent", starting_cash=100_000.0,
                                risk_profile="default@1", now=EVENING)
    db.accounts.insert_one({"_id": "real", "name": "Real", "kind": "real"})
    monkeypatch.setattr("stocks_service.mcp_server._now", lambda: EVENING)
    with _client(db) as c:
        # Identity is mandatory.
        _, err = _call(c, "get_outlook", agent_id="", model_id="m", prompt_version="v")
        assert err
        out, err = _call(c, "get_outlook", **IDENT, limit=5)
        assert not err and out["asof"] == "2025-03-31" and len(out["rows"]) == 5
        acct, _ = _call(c, "get_account", **IDENT, account_id="agent")
        assert acct["equity"] == 100_000.0
        _, err = _call(c, "list_orders", **IDENT, account_id="real")
        assert err  # order tools refuse real accounts
        o, err = _call(c, "place_paper_order", **IDENT, account_id="agent", symbol="SPY", side="long", qty=3,
                       idempotency_key="agent-spy-1", rationale="broad market, positive base rate")
        assert not err and o["status"] == "open" and o["decided_by"]["agent_id"] == "claude-test"
        again, _ = _call(c, "place_paper_order", **IDENT, account_id="agent", symbol="SPY", side="long", qty=3,
                         idempotency_key="agent-spy-1", rationale="retry")
        assert again["replayed"] and again["id"] == o["id"]
        big, _ = _call(c, "place_paper_order", **IDENT, account_id="agent", symbol="NVDA", side="long", qty=100_000,
                       idempotency_key="agent-nvda-1", rationale="too big")
        assert "risk limit" in big["rejected"]
        orders, _ = _call(c, "list_orders", **IDENT, account_id="agent")
        assert [x["symbol"] for x in orders["orders"]] == ["SPY"]
    logged = list(db.agent_decisions.find({}, {"_id": 0}))
    assert {d["tool"] for d in logged} >= {"get_outlook", "get_account", "place_paper_order", "list_orders"}
    assert all(d["agent_id"] == "claude-test" and d["model_id"] and d["prompt_version"] for d in logged)
    place = [d for d in logged if d["tool"] == "place_paper_order"]
    assert place[0]["args"]["rationale"] and place[-1]["result"]["rejected"]


def test_paired_comparison_and_shadow_gate(db, world):  # noqa: F811
    from stocks_service.paper import baseline
    broker.create_paper_account(db, account_id="agent", name="A", starting_cash=100_000.0, risk_profile="default@1",
                                now=EVENING)
    broker.create_paper_account(db, account_id="base", name="B", starting_cash=100_000.0, risk_profile="default@1",
                                policy=baseline.POLICY_ID, now=EVENING)
    baseline.run_baseline(db, "base", EVENING)
    broker.place_order(db, "agent", symbol="QQQ", side="short", qty=10, idempotency_key="agent-qqq-s",
                       decided_by={"agent_id": "t"}, now=EVENING)
    db.bars.insert_many(world)
    broker.process_account(db, "agent", LATER)
    broker.process_account(db, "base", LATER)
    cmp_ = report.compare(db, "agent", "base")
    assert cmp_["sessions"] == len(list(db.equity_curve.find({"account_id": "agent"})))
    assert cmp_["paired_excess_annual"]["ci95"] is not None          # 43 shared sessions >= 40
    assert cmp_["gate"]["promotable"] is False and cmp_["gate"]["checks"]["min_sessions"] is False
    assert cmp_["closed_orders"]["agent"] == 1


def test_rejections_are_audited_and_observations_are_reconstructible(db, world, monkeypatch):  # noqa: F811
    broker.create_paper_account(db, account_id="agent", name="Agent", starting_cash=100_000.0,
                                risk_profile="default@1", now=EVENING)
    db.accounts.insert_one({"_id": "real", "name": "Real", "kind": "real"})
    monkeypatch.setattr("stocks_service.mcp_server._now", lambda: EVENING)
    with _client(db) as c:
        _, err = _call(c, "place_paper_order", **IDENT, account_id="real", symbol="SPY", side="long", qty=1,
                       idempotency_key="real-spy-1", rationale="never on a real account")
        assert err
        _, err = _call(c, "place_paper_order", **IDENT, account_id="agent", symbol="SPY", side="long", qty=1,
                       idempotency_key="short", rationale="x")
        assert err
        seen, _ = _call(c, "get_outlook", **IDENT, limit=3)
    logs = {d["tool"]: d for d in db.agent_decisions.find({}, {"_id": 0})}
    place = [d for d in db.agent_decisions.find({"tool": "place_paper_order"})]
    assert "real account" in place[0]["result"]["error"]
    assert "idempotency_key" in place[1]["result"]["error"]
    obs = logs["get_outlook"]["result"]["observation"]
    assert obs["run_id"] == seen["run_id"] and obs["rows"] == seen["rows"] and len(obs["rows"]) == 3
    assert db.outlook_runs.find_one({"_id": __import__("bson").ObjectId(obs["run_id"])})


def test_comparison_counts_the_first_session_and_only_in_window_trades(db, world):  # noqa: F811
    broker.create_paper_account(db, account_id="a", name="A", starting_cash=100_000.0, risk_profile="default@1",
                                now=EVENING)
    broker.create_paper_account(db, account_id="b", name="B", starting_cash=100_000.0, risk_profile="default@1",
                                now=EVENING)
    broker.place_order(db, "a", symbol="QQQ", side="short", qty=10, idempotency_key="a-qqq-short",
                       decided_by={}, now=EVENING)
    db.bars.insert_many(world)
    broker.process_account(db, "a", LATER)
    broker.process_account(db, "b", LATER)
    full = report.compare(db, "a", "b")
    first_eq = db.equity_curve.find_one({"account_id": "a"}, sort=[("session", 1)])["equity"]
    eq_a = [e["equity"] for e in db.equity_curve.find({"account_id": "a"}).sort("session", 1)]
    assert full["total_return"]["agent"] == pytest.approx(eq_a[-1] / 100_000.0 - 1)
    assert first_eq != 100_000.0  # the first session moved equity (entry costs at least) and it is counted
    # Restrict the shared period to sessions after the order closed: it no longer counts.
    closed = db.orders.find_one({"account_id": "a"})
    db.equity_curve.delete_many({"account_id": "b", "session": {"$lte": closed["exit_session"]}})
    late = report.compare(db, "a", "b")
    assert late["closed_orders"]["agent"] == 0 and full["closed_orders"]["agent"] == 1


SITE = "https://testserver"


def test_paper_accounts_can_be_navigated_with_links(db, world, monkeypatch):  # noqa: F811
    from stocks_service.paper import baseline
    broker.create_paper_account(db, account_id="base", name="B", starting_cash=100_000.0, risk_profile="default@1",
                                policy=baseline.POLICY_ID, now=EVENING)
    broker.create_paper_account(db, account_id="agent", name="A", starting_cash=100_000.0, risk_profile="default@1",
                                now=EVENING)
    baseline.run_baseline(db, "base", EVENING)
    db.bars.insert_many(world)
    broker.process_account(db, "base", LATER)
    broker.process_account(db, "agent", LATER)
    monkeypatch.setattr("stocks_service.mcp_server._now", lambda: LATER)
    with _client(db) as c:
        accts, err = _call(c, "list_accounts", **IDENT)
        assert not err and [a["account_id"] for a in accts["paper"]] == ["agent", "base"]   # best return first
        assert accts["paper"][1]["link"] == f"{SITE}/paper/base" and accts["real"] == []
        perf, _ = _call(c, "get_performance", **IDENT, account_id="agent", points=5)
        assert perf["comparison"]["baseline_account"] == "base" and len(perf["curve"]) == 5
        assert perf["sessions"] == db.equity_curve.count_documents({"account_id": "agent"})
        assert perf["links"]["account"] == f"{SITE}/paper/agent"
        base_perf, _ = _call(c, "get_performance", **IDENT, account_id="base")
        assert base_perf["comparison"] is None and base_perf["closed_orders"] == 4
        tx, _ = _call(c, "list_transactions", **IDENT, account_id="base", limit=3)
        assert len(tx["transactions"]) == 3 and tx["next_cursor"]
        more, _ = _call(c, "list_transactions", **IDENT, account_id="base", limit=100, cursor=tx["next_cursor"])
        assert {t["type"] for t in tx["transactions"] + more["transactions"]} >= {"buy", "sell", "opening_balance"}
        links, _ = _call(c, "get_links", **IDENT, symbol="nvda", compare_years=[2023, 2022], account_id="base")
        assert links["symbol"] == f"{SITE}/symbol/NVDA?compare=2022,2023" and links["account"] == f"{SITE}/paper/base"
        assert any(p["url"] == f"{SITE}/outlook" for p in links["pages"])
        _, err = _call(c, "get_links", **IDENT, symbol="NVDA", chart_range="2Y")
        assert err
        # Every linked page exists.
        c.post("/login", data={"password": "pw"})
        for u in (accts["paper"][0]["link"], links["symbol"], links["account"]):
            assert c.get(u.removeprefix(SITE)).status_code == 200, u


def test_prediction_details_one_ticker(db, world, monkeypatch):  # noqa: F811
    monkeypatch.setattr("stocks_service.mcp_server._now", lambda: EVENING)
    with _client(db) as c:
        p, err = _call(c, "get_prediction", **IDENT, symbol="nvda")
        assert not err, p
        assert p["symbol"] == "NVDA" and p["price"]["asof"] == "2025-03-31"
        assert {r["side"] for r in p["outlook"]["rows"]} == {"long", "short"}
        row = p["outlook"]["rows"][0]
        assert {"grade", "plan", "reasons", "signals"} <= set(row)
        assert {d["strategy"] for d in p["strategy_decisions"]} >= {"ensemble@1"}
        assert p["atr_levels_and_odds"]["long"]["levels"]["stop"] < p["price"]["last_close"]
        assert p["calendar_years"][0]["year"] == 2025 and p["links"]["chart"] == f"{SITE}/symbol/NVDA"
        assert p["links"]["compare_recent_years"] == f"{SITE}/symbol/NVDA?compare=2023,2024,2025"
        msg, err = _call(c, "get_prediction", **IDENT, symbol="ZZZZ")
        assert err and "add_to_watchlist" in msg


def test_watchlist_changes_need_a_confirmed_preview(db, world, monkeypatch):  # noqa: F811
    from .conftest import RecordedFetcher, load_yahoo
    db.price_sources.insert_one({"_id": "yahoo_chart:1d", "price_basis": "split_adjusted",
                                 "volume_basis": "split_adjusted"})
    when = dt.datetime(2025, 6, 20, 23, 0, tzinfo=dt.timezone.utc)
    monkeypatch.setattr("stocks_service.mcp_server._now", lambda: when)
    broker.create_paper_account(db, account_id="agent", name="A", starting_cash=100_000.0, risk_profile="default@1",
                                now=EVENING)
    broker.place_order(db, "agent", symbol="NVDA", side="long", qty=1, idempotency_key="agent-nvda-x",
                       decided_by={"agent_id": "t"}, now=EVENING)
    with _client(db) as c:
        c.app.state.fetcher = RecordedFetcher({("ORLY", "1d"): load_yahoo("ORLY_1d_2025-06-03_2025-06-17")})
        # Preview: validated at the price source, nothing changes.
        pv, err = _call(c, "add_to_watchlist", **IDENT, symbol="orly")
        assert not err and pv["preview"]["asset_class"] == "equity" and pv["confirm_token"]
        assert db.symbols.find_one({"_id": "ORLY"}) is None
        # A token only confirms the previewed arguments, once.
        msg, err = _call(c, "add_to_watchlist", **IDENT, symbol="INTC", confirm_token=pv["confirm_token"])
        assert err and "different arguments" in msg
        done, err = _call(c, "add_to_watchlist", **IDENT, symbol="ORLY", confirm_token=pv["confirm_token"])
        assert not err and done["status"] == "done" and done["history"]["status"] == "loaded", done
        assert db.bars.count_documents({"symbol": "ORLY", "interval": "1d"}) == done["history"]["bars_total"] > 0
        assert done["links"]["chart"] == f"{SITE}/symbol/ORLY"
        _, err = _call(c, "add_to_watchlist", **IDENT, symbol="ORLY", confirm_token=pv["confirm_token"])
        assert err   # used
        wl, _ = _call(c, "get_watchlist", **IDENT)
        assert "ORLY" in [r["symbol"] for r in wl["watched"]]
        # Removal: refused while a paper order needs the symbol's prices; otherwise previewed, then confirmed.
        msg, err = _call(c, "remove_from_watchlist", **IDENT, symbol="NVDA")
        assert err and "agent" in msg
        for required in ("SPY", "^IRX", "QQQM"):   # the session clock, cash rate and benchmarks stay
            msg, err = _call(c, "remove_from_watchlist", **IDENT, symbol=required)
            assert err and "needs it" in msg
        rv, _ = _call(c, "remove_from_watchlist", **IDENT, symbol="INTC")
        assert db.symbols.find_one({"_id": "INTC"})["enabled"] is True
        gone, err = _call(c, "remove_from_watchlist", **IDENT, symbol="INTC", confirm_token=rv["confirm_token"])
        assert not err and gone["action"] == "removed"
        doc = db.symbols.find_one({"_id": "INTC"})
        assert doc["enabled"] is False and db.bars.count_documents({"symbol": "INTC"}) > 0   # history kept
        wl, _ = _call(c, "get_watchlist", **IDENT)
        assert "INTC" in [r["symbol"] for r in wl["removed"]]
    tools = [d["tool"] for d in db.agent_decisions.find().sort("ts", 1)]
    assert tools.count("add_to_watchlist") == 4 and tools.count("remove_from_watchlist") == 6


def test_fidelity_holdings_upload_previews_then_reconciles(db, world, monkeypatch):  # noqa: F811
    monkeypatch.setattr("stocks_service.mcp_server._now", lambda: LATER)
    first = {"account_id": "fidelity", "as_of": "2025-05-30", "cash": 5_000.0, "account_name": "Fidelity brokerage",
             "positions": [{"symbol": "NVDA", "qty": 10, "avg_cost": 100.0}, {"symbol": "FXAIX", "qty": 3, "avg_cost": 200.0}]}
    with _client(db) as c:
        msg, err = _call(c, "upload_holdings", **IDENT, **{**first, "account_name": None})
        assert err and "account_name" in msg
        pv, err = _call(c, "upload_holdings", **IDENT, **first)
        assert not err and pv["preview"]["creates_account"] and pv["preview"]["opening_balance"]
        assert pv["preview"]["not_on_watch_list"] == ["FXAIX"] and db.accounts.find_one({"_id": "fidelity"}) is None
        done, err = _call(c, "upload_holdings", **IDENT, **first, confirm_token=pv["confirm_token"])
        assert not err and done["opening_balance"] and done["open_breaks"] == []
        assert done["links"]["account"] == f"{SITE}/accounts/fidelity"
        assert {p["symbol"]: p["qty"] for p in done["holdings"]["positions"]} == {"FXAIX": 3, "NVDA": 10}
        # A later snapshot that differs is reconciled: differences become breaks, never trades.
        later = {**first, "as_of": "2025-06-02", "account_name": None,
                 "positions": [{"symbol": "NVDA", "qty": 12, "avg_cost": 101.0}, {"symbol": "FXAIX", "qty": 3}]}
        pv2, _ = _call(c, "upload_holdings", **IDENT, **later)
        assert not pv2["preview"]["opening_balance"]
        assert pv2["preview"]["differences"] == [{"symbol": "NVDA", "expected": 10.0, "reported": 12.0, "diff": 2.0}]
        done2, _ = _call(c, "upload_holdings", **IDENT, **later, confirm_token=pv2["confirm_token"])
        assert [b["symbol"] for b in done2["open_breaks"]] == ["NVDA"]
        assert db.executions.count_documents({"account_id": "fidelity"}) == 0
        real, _ = _call(c, "get_account", **IDENT, account_id="fidelity")
        assert real["kind"] == "real" and real["open_breaks"] == 1 and real["cash"] == 5_000.0
        accts, _ = _call(c, "list_accounts", **IDENT, kind="real")
        assert accts["real"][0]["account_id"] == "fidelity" and "paper" not in accts
        # Paper accounts never take holdings uploads.
        broker.create_paper_account(db, account_id="agent", name="A", starting_cash=1.0, risk_profile="default@1",
                                    now=EVENING)
        msg, err = _call(c, "upload_holdings", **IDENT, **{**later, "account_id": "agent"})
        assert err and "paper account" in msg


def test_removed_symbols_take_no_paper_orders_and_removal_rechecks_orders(db, world):  # noqa: F811
    from stocks_service import mcp_ops
    from stocks_service.accounts.service import AccountError
    broker.create_paper_account(db, account_id="agent", name="A", starting_cash=100_000.0, risk_profile="default@1",
                                now=EVENING)
    mcp_ops.apply_remove(db, "INTC", EVENING)
    with pytest.raises(AccountError, match="not on the watch list"):
        broker.place_order(db, "agent", symbol="INTC", side="long", qty=1, idempotency_key="agent-intc-1",
                           decided_by={}, now=EVENING)
    # An order that lands after the preview's check still blocks the removal (checked in the same transaction).
    broker.place_order(db, "agent", symbol="NVDA", side="long", qty=1, idempotency_key="agent-nvda-1",
                       decided_by={}, now=EVENING)
    preview = mcp_ops.preview_remove

    def stale_preview(db_, sym, now):
        db_.orders.update_many({}, {"$set": {"status": "cancelled"}})
        p = preview(db_, sym, now)
        db_.orders.update_many({}, {"$set": {"status": "open"}})
        return p
    mcp_ops.preview_remove = stale_preview
    try:
        with pytest.raises(mcp_ops.OpError, match="now has an open order"):
            mcp_ops.apply_remove(db, "NVDA", EVENING)
    finally:
        mcp_ops.preview_remove = preview
    assert db.symbols.find_one({"_id": "NVDA"})["enabled"] is True   # rolled back


def test_prediction_lists_every_strategy_and_the_intraday_range(db, world, monkeypatch):  # noqa: F811
    from stocks_service import mcp_ops
    from stocks_service.strategies import all_specs
    p = mcp_ops.prediction(db, "QQQM")
    assert {d["strategy"] for d in p["strategy_decisions"]} == {s.key for s in all_specs()}
    bars = list(db.bars.find({"symbol": "QQQM", "interval": "1d"}).sort("session", -1).limit(252))
    assert p["price"]["high_52w"] >= max(b["c"] for b in bars) and p["price"]["low_52w"] <= min(b["c"] for b in bars)
    assert p["price"]["high_52w"] > max(b["c"] for b in bars)   # a real intraday high above every close
