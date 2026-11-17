"""Background data-load jobs runnable through the API (no shell access to the service needed).

Each job records its progress and every per-symbol failure in the ``jobs`` collection.
"""

from __future__ import annotations

import datetime as dt
import threading
import time
import traceback
from pathlib import Path

from bson import ObjectId
from pymongo.database import Database

from . import ingestion, migration
from .db_indexes import ensure_indexes
from .models import AssetClass, SymbolIn
from .settings import Settings
from .yahoo import ChartFetcher

REPO = Path(__file__).resolve().parent.parent
STEPS = ("init", "universe", "verify_1d", "verify_1h", "data_symbols", "backfill_1d", "backfill_1h", "update_1d")
# Known splits used to verify each interval's price basis (confirmed from Yahoo's own events data).
BASIS_CHECKS = {"1d": ("NVDA", dt.date(2024, 6, 10)), "1h": ("ORLY", dt.date(2025, 6, 10))}
# Data-only series needed by the validation baselines (not tradable).
DATA_SYMBOLS = [SymbolIn(symbol="^IRX", asset_class=AssetClass.index, name="13-week T-bill yield", tradable=False)]


class JobRunning(RuntimeError):
    pass


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def start_load(db: Database, fetcher: ChartFetcher, settings: Settings, steps: list[str],
               symbols: list[str] | None = None, pause: float = 0.3) -> str:
    unknown = [s for s in steps if s not in STEPS]
    if unknown:
        raise ValueError(f"unknown steps {unknown}; valid: {list(STEPS)}")
    if db.jobs.find_one({"kind": "data_load", "status": "running"}):
        raise JobRunning("a data load is already running")
    job_id = db.jobs.insert_one({"kind": "data_load", "status": "running", "steps": steps, "symbols": symbols,
                                 "started_at": _now(), "progress": [], "failures": []}).inserted_id
    t = threading.Thread(target=_run, args=(db, fetcher, settings, job_id, steps, symbols, pause), daemon=True)
    t.start()
    return str(job_id)


def run_load_sync(db, fetcher, settings, steps, symbols=None, pause=0.0) -> str:
    """Same as start_load but blocking (tests / CLI)."""
    job_id = db.jobs.insert_one({"kind": "data_load", "status": "running", "steps": steps, "symbols": symbols,
                                 "started_at": _now(), "progress": [], "failures": []}).inserted_id
    _run(db, fetcher, settings, job_id, steps, symbols, pause)
    return str(job_id)


def _log(db, job_id, **entry):
    db.jobs.update_one({"_id": job_id}, {"$push": {"progress": {"at": _now(), **entry}}})


def _fail(db, job_id, **entry):
    db.jobs.update_one({"_id": job_id}, {"$push": {"failures": {"at": _now(), **entry}}})


def _run(db, fetcher, settings, job_id, steps, symbols, pause):
    try:
        now = _now()
        for step in steps:
            if step == "init":
                ensure_indexes(db)
                _log(db, job_id, step=step, ok=True)
            elif step == "universe":
                syms, groups = migration.build_universe(REPO / "config" / "system_config.yaml")
                res = migration.apply_universe(db, syms, groups)
                _log(db, job_id, step=step, inserted=len(res["inserted"]), existing=len(res["already_present"]))
            elif step in ("verify_1d", "verify_1h"):
                interval = step.split("_")[1]
                sym, ex = BASIS_CHECKS[interval]
                v = ingestion.verify_basis(db, fetcher, interval=interval, symbol=sym, split_ex_date=ex, now=now)
                _log(db, job_id, step=step, price_basis=v.price_basis.value, volume_basis=v.volume_basis.value)
            elif step == "data_symbols":
                for s in DATA_SYMBOLS:
                    doc = s.model_dump(mode="json", exclude={"symbol"})
                    db.symbols.update_one({"_id": s.symbol}, {"$setOnInsert": {**doc, "ca_version": 0,
                                                                              "created_at": now}}, upsert=True)
                _log(db, job_id, step=step, symbols=[s.symbol for s in DATA_SYMBOLS])
            else:
                kind, interval = step.split("_")
                targets = symbols or [d["_id"] for d in db.symbols.find({"enabled": True}, {"_id": 1}).sort("_id", 1)]
                if kind == "backfill":
                    loaded = set(db.bars.distinct("symbol", {"interval": interval}))
                    targets = [t for t in targets if t not in loaded]
                    start = (now - dt.timedelta(days=729)) if interval == "1h" else dt.datetime(1990, 1, 2, tzinfo=dt.timezone.utc)
                ok = 0
                for sym in targets:
                    try:
                        if kind == "backfill":
                            r = ingestion.ingest(db, fetcher, symbol=sym, interval=interval, start=start, now=now,
                                                 buffer=dt.timedelta(minutes=settings.ingest_buffer_minutes),
                                                 overlap_tolerance=settings.overlap_tolerance,
                                                 gap_threshold=settings.unexplained_gap_log_threshold)
                        else:
                            r = ingestion.update(db, fetcher, symbol=sym, interval=interval, now=now,
                                                 buffer=dt.timedelta(minutes=settings.ingest_buffer_minutes),
                                                 overlap_tolerance=settings.overlap_tolerance,
                                                 gap_threshold=settings.unexplained_gap_log_threshold)
                        ok += 1
                        _log(db, job_id, step=step, symbol=sym, bars=r.upserted + r.revised + r.unchanged)
                    except Exception as e:  # record and continue with the next symbol
                        _fail(db, job_id, step=step, symbol=sym, error=f"{type(e).__name__}: {e}")
                    time.sleep(pause)
                _log(db, job_id, step=step, ok=ok, total=len(targets))
        failed = db.jobs.find_one({"_id": job_id}, {"failures": 1})["failures"]
        db.jobs.update_one({"_id": job_id}, {"$set": {"status": "completed_with_failures" if failed else "completed",
                                                     "finished_at": _now()}})
    except Exception as e:
        db.jobs.update_one({"_id": job_id}, {"$set": {"status": "failed", "finished_at": _now(),
                                                     "error": f"{type(e).__name__}: {e}",
                                                     "traceback": traceback.format_exc()[-4000:]}})


def get_job(db: Database, job_id: str) -> dict | None:
    try:
        oid = ObjectId(job_id)
    except Exception:
        return None
    doc = db.jobs.find_one({"_id": oid})
    if doc:
        doc["id"] = str(doc.pop("_id"))
    return doc
