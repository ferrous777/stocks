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
        assert tools == {"get_outlook", "get_account", "list_orders", "place_paper_order", "cancel_order",
                         "get_performance"}


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
        _, err = _call(c, "get_account", **IDENT, account_id="real")
        assert err  # real accounts are refused
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
        _, err = _call(c, "get_account", **IDENT, account_id="real")
        assert err
        _, err = _call(c, "place_paper_order", **IDENT, account_id="agent", symbol="SPY", side="long", qty=1,
                       idempotency_key="short", rationale="x")
        assert err
        seen, _ = _call(c, "get_outlook", **IDENT, limit=3)
    logs = {d["tool"]: d for d in db.agent_decisions.find({}, {"_id": 0})}
    assert "real account" in logs["get_account"]["result"]["error"]
    assert "idempotency_key" in logs["place_paper_order"]["result"]["error"]
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
