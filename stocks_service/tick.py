"""The scheduled tick (Railway cron, every 15 minutes on weekdays): keeps data and the outlook current.

1. Incrementally ingest completed daily bars for every enabled symbol that has history (a few
   overlapping sessions are re-fetched for the overlap check). A failing symbol (e.g. quarantined)
   is recorded and the others continue.
2. When a new session's SPY close is stored and the latest outlook is older — or the latest outlook
   lacked some symbol's close for that session and it has now arrived — rebuild the outlook from
   the existing calibration. Calibration itself only uses pre-holdout history, so new bars do
   not change it; it is re-run explicitly (``POST /api/v1/outlook/run``).

3. Protective alerts for protected holdings (stop/target crossed, timeout due) — always on, whatever
   the strategy's status — and a pre-open ticket notification per account when active strategies
   produce tickets.

4. Paper accounts: process completed sessions through the shared simulator, then the baseline
   policy places its orders for the next session.

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
    latest = db.outlook_runs.find_one(sort=[("created_at", -1), ("_id", -1)], projection={"asof": 1, "missing_inputs": 1})
    if latest and latest["asof"] >= last_session:
        arrived = [s for s in latest.get("missing_inputs", [])
                   if db.bars.find_one({"symbol": s, "interval": "1d", "session": spy["session"]}, {"_id": 1})]
        if not arrived:
            return {"status": "current", "asof": latest["asof"]}
    else:
        arrived = []
    try:
        o = build_outlook(db, now=now)
    except OutlookUnavailable as e:
        return {"status": "unavailable", "reason": str(e)}
    return {"status": "rebuilt", "asof": o["asof"], "rows": len(o["rows"]), **({"arrived": arrived} if arrived else {})}


def _alerts(db: Database, now: dt.datetime) -> dict:
    """Protective alerts for every protected holding, then pre-open tickets (active strategies only)."""
    from pymongo.errors import DuplicateKeyError
    from .accounts import tickets
    created = tickets.check_protective(db, now)
    ticket_notes = 0
    for acc in db.accounts.find({}, {"_id": 1}):
        try:
            t = tickets.build_tickets(db, acc["_id"], now)
        except Exception as e:  # one account's problem must not block the others
            created.append({"type": "ticket_error", "account_id": acc["_id"], "error": f"{type(e).__name__}: {e}"})
            continue
        if not t["tickets"]:
            continue
        try:
            db.notifications.insert_one({"type": "pre_open_tickets", "account_id": acc["_id"], "asof": t["asof"],
                                         "tickets": t["tickets"], "created_at": now, "acknowledged": False,
                                         "dedupe_key": f"pre_open_tickets:{acc['_id']}:{t['asof']}",
                                         "message": f"{len(t['tickets'])} order ticket(s) to place before the open"})
            ticket_notes += 1
        except DuplicateKeyError:
            pass
    return {"protective": len([c for c in created if c.get("type") != "ticket_error"]), "ticket_notifications": ticket_notes,
            "errors": [c for c in created if c.get("type") == "ticket_error"]}


def _paper(db: Database, now: dt.datetime) -> list[dict]:
    """Advance every paper account through completed sessions, then let baseline accounts place orders."""
    from .paper import baseline, broker
    out = []
    for acc in db.accounts.find({"kind": "paper"}, {"_id": 1, "policy": 1}):
        try:
            res = broker.process_account(db, acc["_id"], now)
            if acc.get("policy") == baseline.POLICY_ID and not res["stalled"]:
                res["baseline"] = baseline.run_baseline(db, acc["_id"], now)
        except Exception as e:  # one account's problem must not block the others
            res = {"account_id": acc["_id"], "error": f"{type(e).__name__}: {e}"}
        out.append(res)
    return out


def run_tick(db: Database, fetcher: ChartFetcher, settings: Settings, *, pause: float = 0.2,
             run_in_thread: bool = False) -> str:
    def work(log):
        now = dt.datetime.now(dt.timezone.utc)
        ing = _ingest_all(db, fetcher, settings, now, pause)
        log(step="ingest_1d", **{k: v for k, v in ing.items() if k != "failures"}, failed=len(ing["failures"]))
        out = _refresh_outlook(db, now)
        log(step="outlook", **out)
        alerts = _alerts(db, now)
        log(step="alerts", **alerts)
        paper = _paper(db, now)
        log(step="paper", accounts=len(paper))
        return {"ingest_1d": ing, "outlook": out, "alerts": alerts, "paper": paper}

    return jobs.start_job(db, "tick", work, run_in_thread=run_in_thread)
