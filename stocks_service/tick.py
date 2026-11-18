"""The scheduled tick (Railway cron, every 15 minutes on weekdays): keeps data and the outlook current.

1. Incrementally ingest completed daily bars for every enabled symbol that has history (a few
   overlapping sessions are re-fetched for the overlap check). A failing symbol (e.g. quarantined)
   is recorded and the others continue.
2. When a new session's SPY close is stored and the latest outlook is older, rebuild the outlook
   from the existing calibration. Calibration itself only uses pre-holdout history, so new bars do
   not change it; it is re-run explicitly (``POST /api/v1/outlook/run``).

Runs under the shared ``tick`` lease (``stocks_service.jobs``), so overlapping cron runs never
ingest concurrently, and each run is recorded in ``jobs``. Idempotent: running it twice in a row
fetches nothing new the second time and leaves the outlook as is.
"""

from __future__ import annotations

import datetime as dt
import time

from pymongo.database import Database

from . import ingestion, jobs
from .settings import Settings
from .yahoo import ChartFetcher


def _ingest_all(db: Database, fetcher: ChartFetcher, settings: Settings, now: dt.datetime, pause: float) -> dict:
    have = set(db.bars.distinct("symbol", {"interval": "1d"}))
    targets = [d["_id"] for d in db.symbols.find({"enabled": True}, {"_id": 1}).sort("_id", 1) if d["_id"] in have]
    new_bars, failures = 0, []
    for sym in targets:
        try:
            r = ingestion.update(db, fetcher, symbol=sym, interval="1d", now=now,
                                 buffer=dt.timedelta(minutes=settings.ingest_buffer_minutes),
                                 overlap_tolerance=settings.overlap_tolerance,
                                 gap_threshold=settings.unexplained_gap_log_threshold)
            new_bars += r.upserted
        except Exception as e:  # record and continue
            failures.append({"symbol": sym, "error": f"{type(e).__name__}: {e}"})
        if pause:
            time.sleep(pause)
    not_loaded = sorted(d["_id"] for d in db.symbols.find({"enabled": True}, {"_id": 1}) if d["_id"] not in have)
    return {"symbols": len(targets), "new_bars": new_bars, "failures": failures, "not_backfilled": not_loaded}


def _refresh_outlook(db: Database, now: dt.datetime) -> dict:
    from .outlook.build import OutlookUnavailable, build_outlook
    spy = db.bars.find_one({"symbol": "SPY", "interval": "1d"}, sort=[("session", -1)], projection={"session": 1})
    if spy is None:
        return {"status": "skipped", "reason": "no SPY data"}
    last_session = spy["session"].date().isoformat()
    latest = db.outlook_runs.find_one(sort=[("created_at", -1)], projection={"asof": 1})
    if latest and latest["asof"] >= last_session:
        return {"status": "current", "asof": latest["asof"]}
    try:
        o = build_outlook(db, now=now)
    except OutlookUnavailable as e:
        return {"status": "unavailable", "reason": str(e)}
    return {"status": "rebuilt", "asof": o["asof"], "rows": len(o["rows"])}


def run_tick(db: Database, fetcher: ChartFetcher, settings: Settings, *, pause: float = 0.2,
             run_in_thread: bool = False) -> str:
    def work(log):
        now = dt.datetime.now(dt.timezone.utc)
        ing = _ingest_all(db, fetcher, settings, now, pause)
        log(step="ingest_1d", **{k: v for k, v in ing.items() if k != "failures"}, failed=len(ing["failures"]))
        out = _refresh_outlook(db, now)
        log(step="outlook", **out)
        return {"ingest_1d": ing, "outlook": out}

    return jobs.start_job(db, "tick", work, run_in_thread=run_in_thread)
