"""Operations: how often each scheduled step runs, and how long every process takes.

**Schedule.** The cron tick fires every 15 minutes on weekdays (the finest granularity; set in
``.railway/railway.ts``). On each tick every step decides whether it is due from its schedule in
the ``schedules`` collection, editable on the Ops page or ``PUT /api/v1/ops/schedule/{step}``:

* ``auto`` (default): event-driven, runs only when there is something new for it (rules below);
* ``every_tick``: runs on every tick;
* ``interval``: runs when its last successful run is at least ``interval_minutes`` old;
* ``off``: never runs (the Ops page shows it as paused).

**Timing.** Every step run (or skip, with its reason) is written to ``step_runs``; every job records
its ``duration_s``; MCP tool calls record ``duration_ms`` in ``agent_decisions``; website and API
requests are aggregated per route and hour in ``request_timings``. All of it is measured, never
estimated.
"""

from __future__ import annotations

import datetime as dt
import math

from pymongo.database import Database

UTC = dt.timezone.utc
MODES = ("auto", "every_tick", "interval", "off")
CRON = "*/15 12-23 * * 1-5"
CRON_NOTE = "every 15 minutes, 12:00-23:59 UTC, Monday-Friday"

# Tick steps in execution order, with what "auto" means for each.
STEPS: dict[str, str] = {
    "ingest_1d": "fetch only symbols whose last daily bar is older than the last completed session "
                 "(daily bars complete once a day, after the close); every_tick/interval re-fetch all",
    "relationships": "when the latest session or the symbols with a bar on it changed (new close, late "
                     "symbol, watch-list change); checked with indexed lookups",
    "outlook": "every tick: it rebuilds only when a new close or a late symbol arrives (a quick check)",
    "lifecycle": "once per new data session, and whenever the outlook was rebuilt (new live decisions)",
    "alerts": "protective alerts every tick (timeouts, missing prices); order tickets once per new data "
              "session or rebuilt outlook",
    "paper": "when a paper account is behind the latest data session, or the outlook was rebuilt",
}


class ScheduleError(ValueError):
    pass


def get_schedule(db: Database) -> dict[str, dict]:
    stored = {d["_id"]: d for d in db.schedules.find()}
    out = {}
    for step, rule in STEPS.items():
        d = stored.get(step, {})
        out[step] = {"step": step, "mode": d.get("mode", "auto"), "interval_minutes": d.get("interval_minutes"),
                     "auto_rule": rule, "updated_at": d.get("updated_at"), "last_run_at": d.get("last_run_at"),
                     "last_success_at": d.get("last_success_at"), "last_marker": d.get("last_marker"),
                     "last_duration_s": d.get("last_duration_s"), "last_status": d.get("last_status")}
    return out


def set_schedule(db: Database, step: str, *, mode: str, interval_minutes: int | None, now: dt.datetime) -> dict:
    if step not in STEPS:
        raise ScheduleError(f"unknown step {step!r}; steps: {', '.join(STEPS)}")
    if mode not in MODES:
        raise ScheduleError(f"mode must be one of {', '.join(MODES)}")
    if mode == "interval":
        if interval_minutes is None or not 15 <= interval_minutes <= 7 * 24 * 60:
            raise ScheduleError("interval_minutes must be between 15 (the tick's own frequency) and 10080 (a week)")
    else:
        interval_minutes = None
    db.schedules.update_one({"_id": step}, {"$set": {"mode": mode, "interval_minutes": interval_minutes,
                                                     "updated_at": now}}, upsert=True)
    return get_schedule(db)[step]


def is_due(cfg: dict, auto_due: tuple[bool, str], now: dt.datetime) -> tuple[bool, str]:
    """Whether a step runs on this tick, and why (or why not)."""
    mode = cfg["mode"]
    if mode == "off":
        return False, "schedule is off"
    if mode == "every_tick":
        return True, "every tick"
    if mode == "interval":
        last = cfg.get("last_success_at")
        if last is None:
            return True, "never run"
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        age = (now - last).total_seconds() / 60
        if age >= cfg["interval_minutes"]:
            return True, f"last success {age:.0f} min ago >= {cfg['interval_minutes']} min"
        return False, f"last success {age:.0f} min ago < {cfg['interval_minutes']} min"
    return auto_due


def record_step(db: Database, *, job: str, job_id: str | None, step: str, started_at: dt.datetime,
                duration_s: float | None, status: str, reason: str, mode: str, marker=None) -> None:
    """One step's outcome on one tick: ``ok``, ``failed`` or ``skipped`` (with the reason)."""
    db.step_runs.insert_one({"job": job, "job_id": job_id, "step": step, "at": started_at, "duration_s": duration_s,
                             "status": status, "reason": reason, "mode": mode})
    upd: dict = {"last_run_at": started_at, "last_status": status}
    if status != "skipped":
        upd["last_duration_s"] = duration_s
    if status == "ok":
        upd["last_success_at"] = started_at
        if marker is not None:
            upd["last_marker"] = marker
    db.schedules.update_one({"_id": step}, {"$set": upd}, upsert=True)


# --- request timing --------------------------------------------------------------------------

def record_request(db: Database, *, route: str, method: str, status: int, duration_ms: float, now: dt.datetime) -> None:
    hour = now.replace(minute=0, second=0, microsecond=0)
    db.request_timings.update_one(
        {"route": route, "method": method, "hour": hour},
        {"$inc": {"count": 1, "total_ms": duration_ms, "errors": 1 if status >= 500 else 0},
         "$max": {"max_ms": duration_ms}}, upsert=True)


class RequestTimer:
    """ASGI middleware: time every website/API request, aggregated per route template and hour.
    Static files are skipped. A failure to record never affects the response."""

    def __init__(self, app, get_db):
        self.app, self.get_db = app, get_db

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path", "").startswith("/static/"):
            return await self.app(scope, receive, send)
        import time
        t0 = time.perf_counter()
        status = {"code": 500}

        async def _send(msg):
            if msg["type"] == "http.response.start":
                status["code"] = msg["status"]
            await send(msg)

        try:
            await self.app(scope, receive, _send)
        finally:
            ms = (time.perf_counter() - t0) * 1000
            route = scope.get("route")
            path = getattr(route, "path", None) or ("/mcp" if scope.get("path", "").startswith("/mcp") else "(unmatched)")
            try:
                db = self.get_db()
                if db is not None:
                    from starlette.concurrency import run_in_threadpool
                    await run_in_threadpool(record_request, db, route=path, method=scope.get("method", ""),
                                            status=status["code"], duration_ms=ms, now=dt.datetime.now(UTC))
            except Exception:
                pass


# --- summaries ---------------------------------------------------------------------------------

def _pct(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    return s[min(len(s) - 1, max(0, math.ceil(q * len(s)) - 1))]


def _stats(xs: list[float]) -> dict:
    return {"runs": len(xs), "avg": sum(xs) / len(xs) if xs else None, "p50": _pct(xs, 0.5), "p95": _pct(xs, 0.95),
            "max": max(xs) if xs else None, "total": sum(xs)}


def step_timings(db: Database, *, since: dt.datetime) -> list[dict]:
    """Per tick step since ``since``: duration stats of the runs, skip and failure counts."""
    rows = []
    for step in STEPS:
        runs = list(db.step_runs.find({"step": step, "at": {"$gte": since}}, {"duration_s": 1, "status": 1}))
        ok = [r["duration_s"] for r in runs if r["status"] == "ok" and r.get("duration_s") is not None]
        rows.append({"step": step, **_stats(ok), "skipped": sum(r["status"] == "skipped" for r in runs),
                     "failed": sum(r["status"] == "failed" for r in runs)})
    return rows


def job_timings(db: Database, *, since: dt.datetime) -> list[dict]:
    """Per job kind (tick, outlook, research, data loads, ...): duration stats of finished runs."""
    by: dict[str, list] = {}
    for j in db.jobs.find({"started_at": {"$gte": since}}, {"kind": 1, "status": 1, "started_at": 1,
                                                             "finished_at": 1, "duration_s": 1}):
        by.setdefault(j.get("kind", "?"), []).append(j)
    out = []
    for kind, js in sorted(by.items()):
        durs = []
        for j in js:
            d = j.get("duration_s")
            if d is None and j.get("finished_at") and j.get("started_at"):
                d = (j["finished_at"] - j["started_at"]).total_seconds()
            if d is not None:
                durs.append(d)
        last = max(js, key=lambda j: j["started_at"])
        out.append({"kind": kind, **_stats(durs), "failed": sum(j["status"] == "failed" for j in js),
                    "last_started": last["started_at"], "last_status": last["status"]})
    return out


def request_timings(db: Database, *, since: dt.datetime, limit: int = 40) -> list[dict]:
    agg = db.request_timings.aggregate([
        {"$match": {"hour": {"$gte": since}}},
        {"$group": {"_id": {"route": "$route", "method": "$method"}, "count": {"$sum": "$count"},
                    "total_ms": {"$sum": "$total_ms"}, "max_ms": {"$max": "$max_ms"}, "errors": {"$sum": "$errors"}}},
        {"$sort": {"total_ms": -1}}, {"$limit": limit}])
    return [{"route": a["_id"]["route"], "method": a["_id"]["method"], "count": a["count"],
             "avg_ms": a["total_ms"] / a["count"], "max_ms": a["max_ms"], "total_ms": a["total_ms"],
             "errors": a["errors"]} for a in agg]


def tool_timings(db: Database, *, since: dt.datetime) -> list[dict]:
    by: dict[str, list[float]] = {}
    for d in db.agent_decisions.find({"ts": {"$gte": since}, "duration_ms": {"$exists": True}}, {"tool": 1, "duration_ms": 1}):
        by.setdefault(d["tool"], []).append(d["duration_ms"])
    return sorted(({"tool": t, **_stats(xs)} for t, xs in by.items()), key=lambda r: -r["total"])


def recent_ticks(db: Database, limit: int = 20) -> list[dict]:
    """The latest ticks with each step's duration (or skip), for the per-tick breakdown."""
    ticks = list(db.jobs.find({"kind": "tick"}, {"status": 1, "started_at": 1, "finished_at": 1, "duration_s": 1})
                 .sort("started_at", -1).limit(limit))
    ids = [str(t["_id"]) for t in ticks]
    steps: dict[str, dict] = {}
    for r in db.step_runs.find({"job_id": {"$in": ids}}):
        steps.setdefault(r["job_id"], {})[r["step"]] = r
    for t in ticks:
        t["steps"] = steps.get(str(t["_id"]), {})
        t.setdefault("duration_s", None)   # a running tick has no duration yet
        if t["duration_s"] is None and t.get("finished_at"):
            t["duration_s"] = (t["finished_at"] - t["started_at"]).total_seconds()
    return ticks
