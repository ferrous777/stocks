import datetime as dt

import pytest
from fastapi.testclient import TestClient

from stocks_service import jobs, ops, tick
from stocks_service.api.app import create_app
from stocks_service.settings import Settings

from .test_ingestion import _add_symbol, _ingest, _verify
from .test_tick import S

UTC = dt.timezone.utc
H = {"X-API-Key": "k"}


def _client(db):
    s = Settings(mongo_url="x", api_keys="k", admin_password="pw", session_secret="s" * 40)
    return TestClient(create_app(s, db=db), base_url="https://testserver")


def _spy(db, fetcher):
    """NVDA's recorded bars stored as SPY too, so there is a data session."""
    _add_symbol(db, "NVDA")
    _verify(db, fetcher)
    _ingest(db, fetcher)
    db.bars.insert_many([{**{k: v for k, v in b.items() if k != "_id"}, "symbol": "SPY"}
                         for b in db.bars.find({"symbol": "NVDA"})])


def test_every_tick_step_is_timed_and_auto_skips_work_with_nothing_new(db, fetcher, monkeypatch):
    _spy(db, fetcher)
    job = jobs.get_job(db, tick.run_tick(db, fetcher, S, pause=0))
    assert job["status"] == "completed" and job["duration_s"] > 0
    runs = {r["step"]: r for r in db.step_runs.find({"job_id": job["id"]})}
    assert set(runs) == set(ops.STEPS)
    assert all(r["status"] == "ok" and r["duration_s"] >= 0 for r in runs.values() if r["step"] != "paper")
    assert runs["relationships"]["reason"].startswith("inputs changed") and runs["lifecycle"]["reason"].startswith("new data session")
    # Next tick: nothing behind, the same data session -> the daily steps skip, with their reason.
    monkeypatch.setattr(tick, "_behind", lambda db_, now: [])
    fetcher.calls.clear()
    job2 = jobs.get_job(db, tick.run_tick(db, fetcher, S, pause=0))
    runs2 = {r["step"]: r for r in db.step_runs.find({"job_id": job2["id"]})}
    assert runs2["ingest_1d"]["status"] == "skipped" and "every symbol" in runs2["ingest_1d"]["reason"]
    assert fetcher.calls == []                                      # no price-source traffic at all
    assert runs2["relationships"]["status"] == runs2["lifecycle"]["status"] == "skipped"
    assert "already ran for" in runs2["lifecycle"]["reason"] and runs2["outlook"]["status"] == "ok"
    assert job2["result"]["ingest_1d"] == {"skipped": runs2["ingest_1d"]["reason"]}
    # The user can override: every tick re-fetches every symbol; off pauses a step.
    ops.set_schedule(db, "ingest_1d", mode="every_tick", interval_minutes=None, now=dt.datetime.now(UTC))
    ops.set_schedule(db, "outlook", mode="off", interval_minutes=None, now=dt.datetime.now(UTC))
    job3 = jobs.get_job(db, tick.run_tick(db, fetcher, S, pause=0))
    runs3 = {r["step"]: r for r in db.step_runs.find({"job_id": job3["id"]})}
    assert runs3["ingest_1d"]["status"] == "ok" and {c[0] for c in fetcher.calls} == {"NVDA"}
    assert runs3["outlook"] == {**runs3["outlook"], "status": "skipped", "reason": "schedule is off"}


def test_auto_ingest_fetches_only_symbols_behind(db, fetcher, monkeypatch):
    _spy(db, fetcher)
    _add_symbol(db, "SPY")
    seen = []
    real = tick._ingest_all
    monkeypatch.setattr(tick, "_ingest_all", lambda *a, only=None, **k: seen.append(only) or real(*a, only=only, **k))
    tick.run_tick(db, fetcher, S, pause=0)
    assert seen == [sorted(tick._behind(db, dt.datetime.now(UTC)))] and seen[0] == ["NVDA", "SPY"]


def test_interval_and_validation():
    now = dt.datetime(2026, 1, 5, 15, tzinfo=UTC)
    cfg = {"mode": "interval", "interval_minutes": 60, "last_success_at": now - dt.timedelta(minutes=45)}
    assert ops.is_due(cfg, (True, "x"), now)[0] is False
    assert ops.is_due({**cfg, "last_success_at": now - dt.timedelta(minutes=61)}, (False, "x"), now)[0] is True
    assert ops.is_due({**cfg, "last_success_at": None}, (False, "x"), now) == (True, "never run")
    assert ops.is_due({"mode": "auto"}, (False, "nothing new"), now) == (False, "nothing new")
    assert ops.is_due({"mode": "every_tick"}, (False, "x"), now)[0] is True


def test_schedule_api_page_and_request_and_tool_timings(db, fetcher):
    with _client(db) as c:
        assert c.put("/api/v1/ops/schedule/ingest_1d", json={"mode": "interval"}, headers=H).status_code == 422
        assert c.put("/api/v1/ops/schedule/nope", json={"mode": "auto"}, headers=H).status_code == 422
        ok = c.put("/api/v1/ops/schedule/ingest_1d", json={"mode": "interval", "interval_minutes": 60}, headers=H).json()
        assert ok["mode"] == "interval" and ok["interval_minutes"] == 60
        c.post("/login", data={"password": "pw"})
        r = c.post("/ops/schedule", data={"step": "lifecycle", "mode": "off", "interval_minutes": ""},
                   follow_redirects=False)
        assert r.status_code == 303 and ops.get_schedule(db)["lifecycle"]["mode"] == "off"
        bad = c.post("/ops/schedule", data={"step": "lifecycle", "mode": "interval", "interval_minutes": "5"}).text
        assert "Not saved" in bad and ops.get_schedule(db)["lifecycle"]["mode"] == "off"
        page = c.get("/ops").text
        assert 'aria-current="page">Ops<' in page and "ingest_1d" in page and "interval 60 min" in page
        c.get("/ops?days=1")
        overview = c.get("/api/v1/ops", headers=H).json()
    assert overview["cron"]["schedule"] == ops.CRON
    routes = {(r["route"], r["method"]): r for r in overview["requests"]}
    assert routes[("/ops", "GET")]["count"] >= 1 and routes[("/ops", "GET")]["avg_ms"] > 0
    assert routes[("/api/v1/ops/schedule/{step}", "PUT")]["count"] == 3   # route templates, not raw paths


def test_mcp_calls_record_their_duration(db):
    import json
    with _client(db) as c:
        c.post("/mcp/", headers={"Authorization": "Bearer k", "Accept": "application/json, text/event-stream",
                                 "Content-Type": "application/json"},
               content=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
                   "name": "get_watchlist", "arguments": {"agent_id": "a", "model_id": "m", "prompt_version": "v"}}}))
    d = db.agent_decisions.find_one({"tool": "get_watchlist"})
    assert d["duration_ms"] > 0
    assert ops.tool_timings(db, since=dt.datetime(2000, 1, 1, tzinfo=UTC))[0]["tool"] == "get_watchlist"


def test_review_fixes_failures_late_data_alerts_and_running_ticks(db, fetcher, monkeypatch):
    from stocks_service import cross_asset
    _spy(db, fetcher)
    # A non-blocking step that fails is recorded as failed and retried, never as a success.
    monkeypatch.setattr(cross_asset, "run_relationships", lambda db_, now: (_ for _ in ()).throw(RuntimeError("boom")))
    job = jobs.get_job(db, tick.run_tick(db, fetcher, S, pause=0))
    rel = db.step_runs.find_one({"job_id": job["id"], "step": "relationships"})
    assert job["status"] == "completed" and rel["status"] == "failed" and "boom" in rel["reason"]
    assert ops.get_schedule(db)["relationships"]["last_success_at"] is None
    monkeypatch.undo()
    monkeypatch.setattr(tick, "_behind", lambda db_, now: [])
    job2 = jobs.get_job(db, tick.run_tick(db, fetcher, S, pause=0))
    runs2 = {r["step"]: r for r in db.step_runs.find({"job_id": job2["id"]})}
    assert runs2["relationships"]["status"] == "ok"                       # retried
    # Protective alerts run every tick; tickets wait for new data.
    assert runs2["alerts"]["status"] == "ok" and job2["result"]["alerts"]["tickets_checked"] is False
    # A late symbol's close changes the relationships inputs on the same session.
    current, _ = cross_asset.relationships_current(db)
    assert current
    last = db.bars.find_one({"symbol": "NVDA"}, sort=[("session", -1)])
    db.bars.delete_one({"_id": last["_id"]})
    assert cross_asset.relationships_current(db)[0] is False
    db.bars.insert_one(last)
    # An outlook rebuilt by a late close re-runs lifecycle (parity of the new decisions) before alerts/paper.
    monkeypatch.setattr(tick, "_refresh_outlook", lambda db_, now: {"status": "rebuilt", "asof": "x", "rows": 0})
    job3 = jobs.get_job(db, tick.run_tick(db, fetcher, S, pause=0))
    runs3 = {r["step"]: r for r in db.step_runs.find({"job_id": job3["id"]})}
    assert runs3["lifecycle"]["status"] == "ok" and runs3["lifecycle"]["reason"] == "outlook rebuilt"
    assert job3["result"]["alerts"]["tickets_checked"] is True
    # The page works while a tick is running (no duration yet).
    db.jobs.insert_one({"kind": "tick", "status": "running", "started_at": dt.datetime.now(UTC), "progress": []})
    with _client(db) as c:
        c.post("/login", data={"password": "pw"})
        r = c.get("/ops")
    assert r.status_code == 200 and ">running<" in r.text
