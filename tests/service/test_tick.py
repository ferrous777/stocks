import dataclasses
import datetime as dt

import pytest

from stocks_service import jobs, tick
from stocks_service.outlook import build
from stocks_service.research import protocol
from stocks_service.settings import Settings

from .conftest import NOW
from .test_ingestion import _add_symbol, _ingest, _verify
from .test_research import _load_db

UTC = dt.timezone.utc
S = Settings(mongo_url="x", api_keys="k")


def test_tick_ingests_new_bars_records_failures_and_is_idempotent(db, fetcher):
    _add_symbol(db, "NVDA")
    _verify(db, fetcher)
    _ingest(db, fetcher)
    # Pretend the last two weeks have not been stored yet: the tick must fetch them incrementally.
    db.bars.delete_many({"symbol": "NVDA", "session": {"$gt": dt.datetime(2024, 7, 1, tzinfo=UTC)}})
    _add_symbol(db, "AMD")   # enabled, no history: reported as not backfilled, never fetched
    _add_symbol(db, "INTC")
    db.bars.insert_one({"symbol": "INTC", "interval": "1d", "session": dt.datetime(2024, 7, 1, tzinfo=UTC),
                        "ts": dt.datetime(2024, 7, 1, 13, 30, tzinfo=UTC), "o": 1, "h": 1, "l": 1, "c": 1, "v": 1})
    job = jobs.get_job(db, tick.run_tick(db, fetcher, S, pause=0))
    assert job["status"] == "completed"
    ing = job["result"]["ingest_1d"]
    assert ing["symbols"] == 2 and ing["new_bars"] == 9 and ing["not_backfilled"] == ["AMD"]
    assert [f["symbol"] for f in ing["failures"]] == ["INTC"]   # no recorded data: recorded, others continue
    assert job["result"]["outlook"] == {"status": "skipped", "reason": "no SPY data"}
    assert job["result"]["paper"]["paper_accounts"]["created"] == []   # no baseline account to copy from yet
    assert db.bars.count_documents({"symbol": "NVDA"}) == 51
    again = jobs.get_job(db, tick.run_tick(db, fetcher, S, pause=0))["result"]["ingest_1d"]
    assert again["new_bars"] == 0
    assert all(c[0] != "AMD" for c in fetcher.calls)


def test_overlapping_ticks_do_not_run_concurrently(db, fetcher):
    assert jobs.claim_lock(db, "job:tick", "other", dt.datetime.now(UTC))
    with pytest.raises(jobs.JobConflict):
        tick.run_tick(db, fetcher, S, pause=0)


def test_tick_rebuilds_the_outlook_only_for_a_new_session(db):
    _load_db(db)
    protocol.seal_holdout(db, start=dt.date(2024, 11, 18), end=dt.date(2025, 5, 30), now=NOW)
    assert tick._refresh_outlook(db, NOW)["status"] == "unavailable"  # no calibration yet: explained, not fatal
    db.cost_profiles.insert_one({"_id": "market@1", **dataclasses.asdict(protocol.BASE_COST), "profile_id": "market"})
    cal = build.run_calibration(db, now=NOW)
    first = tick._refresh_outlook(db, NOW)
    assert first["status"] == "rebuilt" and first["asof"] == "2025-06-02"
    assert tick._refresh_outlook(db, NOW) == {"status": "current", "asof": "2025-06-02"}
    assert db.outlook_runs.count_documents({}) == 1 and cal


def test_same_session_rebuild_when_a_missing_close_arrives(db):
    _load_db(db)
    protocol.seal_holdout(db, start=dt.date(2024, 11, 18), end=dt.date(2025, 5, 30), now=NOW)
    db.cost_profiles.insert_one({"_id": "market@1", **dataclasses.asdict(protocol.BASE_COST), "profile_id": "market"})
    build.run_calibration(db, now=NOW)
    last = dt.datetime(2025, 6, 2, tzinfo=UTC)
    held = db.bars.find_one({"symbol": "INTC", "session": last})
    db.bars.delete_one({"_id": held["_id"]})                    # INTC's close not published yet
    first = tick._refresh_outlook(db, NOW)
    assert first["status"] == "rebuilt"
    assert db.outlook_runs.find_one(sort=[("created_at", -1), ("_id", -1)])["missing_inputs"] == ["INTC"]
    assert tick._refresh_outlook(db, NOW)["status"] == "current"  # still missing: nothing to do
    db.bars.insert_one(held)                                      # it arrives on a later tick
    again = tick._refresh_outlook(db, NOW)
    assert again["status"] == "rebuilt" and again["arrived"] == ["INTC"]
    assert db.outlook_runs.find_one(sort=[("created_at", -1), ("_id", -1)])["missing_inputs"] == []


def test_synchronous_jobs_renew_their_lease(db, monkeypatch):
    import time as _time
    monkeypatch.setattr(jobs, "HEARTBEAT_SECONDS", 0.05)
    seen = []

    def work(log):
        first = db.job_locks.find_one({"_id": "job:slow"})["expires_at"]
        _time.sleep(0.3)
        seen.append((first, db.job_locks.find_one({"_id": "job:slow"})["expires_at"]))

    jobs.start_job(db, "slow", work, run_in_thread=False)
    assert seen[0][1] > seen[0][0]  # extended while the synchronous work ran


def test_jobs_listing_for_operational_checks(db, fetcher):
    from fastapi.testclient import TestClient
    from stocks_service.api.app import create_app
    _add_symbol(db, "NVDA")
    _verify(db, fetcher)
    _ingest(db, fetcher)
    tick.run_tick(db, fetcher, S, pause=0)
    with TestClient(create_app(S, db=db), base_url="https://testserver") as c:
        rows = c.get("/api/v1/admin/jobs?kind=tick", headers={"X-API-Key": "k"}).json()
        assert len(rows) == 1 and rows[0]["status"] == "completed" and "ingest_1d" in rows[0]["result"]
        assert "traceback" not in rows[0]
