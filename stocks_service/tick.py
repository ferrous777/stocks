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

   Then the lifecycle checks: replay every new live decision (parity; a mismatch pauses the
   version), score resolved forecasts against what happened, and run the monitors.
4. Paper accounts: process completed sessions through the shared simulator, then the baseline
   policy places its orders for the next session.

Each step runs only when its schedule says it is due (``stocks_service.ops``: ``auto`` by default,
which is event-driven, or every tick, an interval, or off); every run or skip is timed and recorded
in ``step_runs``.

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


def _behind(db: Database, now: dt.datetime) -> list[str]:
    """Enabled symbols with history whose last daily bar is older than the last completed session."""
    from .accounts.tickets import last_completed_session
    done = dt.datetime.combine(last_completed_session(now), dt.time(), dt.timezone.utc)
    last = {d["_id"]: d["last"] for d in db.bars.aggregate([
        {"$match": {"interval": "1d"}}, {"$group": {"_id": "$symbol", "last": {"$max": "$session"}}}])}
    return [d["_id"] for d in db.symbols.find({"enabled": True}, {"_id": 1}).sort("_id", 1)
            if d["_id"] in last and last[d["_id"]] < done]


def _ingest_all(db: Database, fetcher: ChartFetcher, settings: Settings, now: dt.datetime, pause: float,
                only: list[str] | None = None) -> dict:
    have = set(db.bars.distinct("symbol", {"interval": "1d"}))
    targets = [d["_id"] for d in db.symbols.find({"enabled": True}, {"_id": 1}).sort("_id", 1)
               if d["_id"] in have and (only is None or d["_id"] in only)]
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


def _lifecycle(db: Database, now: dt.datetime) -> dict:
    """Parity replay of live decisions, forecast-vs-actual scoring, monitors (may pause versions)."""
    from . import lifecycle
    return {"parity": lifecycle.run_parity(db, now), "forecasts": lifecycle.track_forecasts(db, now),
            "monitors": lifecycle.run_monitors(db, now)}


def _paper(db: Database, now: dt.datetime) -> list[dict]:
    """Advance every paper account through completed sessions, then let the rule-based accounts
    (the baseline and one per strategy) place orders."""
    from .paper import baseline, broker, strategy_accounts
    out = []
    for acc in db.accounts.find({"kind": "paper"}, {"_id": 1, "policy": 1}):
        try:
            res = broker.process_account(db, acc["_id"], now)
            if acc.get("policy") == baseline.POLICY_ID and not res["stalled"]:
                res["baseline"] = baseline.run_baseline(db, acc["_id"], now)
            elif acc.get("policy") == strategy_accounts.POLICY_ID and not res["stalled"]:
                res["strategy"] = strategy_accounts.run_strategy(db, acc["_id"], now)
        except Exception as e:  # one account's problem must not block the others
            res = {"account_id": acc["_id"], "error": f"{type(e).__name__}: {e}"}
        out.append(res)
    return out


def _data_session(db: Database) -> str | None:
    spy = db.bars.find_one({"symbol": "SPY", "interval": "1d"}, {"session": 1}, sort=[("session", -1)])
    return spy["session"].date().isoformat() if spy else None


def run_tick(db: Database, fetcher: ChartFetcher, settings: Settings, *, pause: float = 0.2,
             run_in_thread: bool = False) -> str:
    from . import ops

    def work(log):
        now = dt.datetime.now(dt.timezone.utc)
        sched = ops.get_schedule(db)
        results: dict = {}
        state = {"outlook_rebuilt": False}

        def step(name: str, auto: tuple[bool, str], fn, *, marker=None, summarize=None):
            cfg = sched[name]
            due, why = ops.is_due(cfg, auto, now)
            started = dt.datetime.now(dt.timezone.utc)
            if not due:
                ops.record_step(db, job="tick", job_id=log.job_id, step=name, started_at=started, duration_s=None,
                                status="skipped", reason=why, mode=cfg["mode"])
                log(step=name, skipped=why)
                results[name] = {"skipped": why}
                return None
            t0 = time.perf_counter()
            try:
                out = fn(cfg["mode"])
            except Exception as e:
                ops.record_step(db, job="tick", job_id=log.job_id, step=name, started_at=started,
                                duration_s=time.perf_counter() - t0, status="failed",
                                reason=f"{type(e).__name__}: {e}", mode=cfg["mode"])
                raise
            dur = time.perf_counter() - t0
            ops.record_step(db, job="tick", job_id=log.job_id, step=name, started_at=started, duration_s=dur,
                            status="ok", reason=why, mode=cfg["mode"],
                            marker=marker() if callable(marker) else marker)
            log(step=name, duration_s=round(dur, 3), **(summarize(out) if summarize else {}))
            results[name] = out
            return out

        def new_session(name):
            ds = _data_session(db)
            last = sched[name].get("last_marker")
            if ds is None:
                return False, "no SPY data yet"
            return (ds != last), (f"new data session {ds}" if ds != last else f"already ran for {ds}")

        # 1. prices
        behind = _behind(db, now)
        step("ingest_1d", (bool(behind), f"{len(behind)} symbol(s) behind the last completed session"
                           if behind else "every symbol has the last completed session"),
             lambda mode: _ingest_all(db, fetcher, settings, now, pause, only=behind if mode == "auto" else None),
             summarize=lambda ing: {k: v for k, v in ing.items() if k != "failures"} | {"failed": len(ing["failures"])})

        # 2. analytics (never block the trading pipeline)
        def rel(_mode):
            from .cross_asset import run_relationships
            try:
                return run_relationships(db, now)
            except Exception as e:
                return {"status": "failed", "error": f"{type(e).__name__}: {e}"}
        step("relationships", new_session("relationships"), rel, marker=lambda: _data_session(db),
             summarize=lambda r: r)

        # 3. outlook (cheap self-check every tick)
        out = step("outlook", (True, "checks for a new close or late symbols"), lambda _m: _refresh_outlook(db, now),
                   summarize=lambda o: o)
        state["outlook_rebuilt"] = bool(out and out.get("status") == "rebuilt")

        # 4. lifecycle
        step("lifecycle", new_session("lifecycle"), lambda _m: _lifecycle(db, now), marker=lambda: _data_session(db),
             summarize=lambda life: {"parity": life["parity"], "forecasts": life["forecasts"],
                                     "breaches": [m["source"] for m in life["monitors"] if m["status"] == "breach"]})

        # 5. alerts and tickets
        due, why = new_session("alerts")
        if state["outlook_rebuilt"]:
            due, why = True, "outlook rebuilt"
        step("alerts", (due, why), lambda _m: _alerts(db, now), marker=lambda: _data_session(db), summarize=lambda a: a)

        # 6. paper accounts
        def paper(_mode):
            from .paper.strategy_accounts import ensure_strategy_accounts
            accounts = ensure_strategy_accounts(db, now)   # new strategies get their paper account here; never raises
            return {"paper_accounts": accounts, "accounts": _paper(db, now)}
        ds = _data_session(db)
        lagging = [a["_id"] for a in db.accounts.find({"kind": "paper"}, {"last_session_executed": 1})
                   if ds and a["last_session_executed"].date().isoformat() < ds]
        from .paper.strategy_accounts import account_id_for
        from .strategies import all_specs
        missing = [k.key for k in all_specs() if not db.accounts.find_one({"_id": account_id_for(k.key)}, {"_id": 1})]
        pdue = ((True, "outlook rebuilt") if state["outlook_rebuilt"]
                else (True, f"{len(lagging)} paper account(s) behind {ds}") if lagging
                else (True, f"{len(missing)} strategy account(s) to create") if missing
                else (False, f"every paper account is processed through {ds}"))
        step("paper", pdue, paper, summarize=lambda p: {"accounts": len(p["accounts"]),
                                                        "created": p["paper_accounts"]["created"],
                                                        "failed": p["paper_accounts"]["failed"]})
        return results

    return jobs.start_job(db, "tick", work, run_in_thread=run_in_thread)
