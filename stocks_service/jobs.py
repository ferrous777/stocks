"""Background jobs with an atomic, expiring, heartbeated lease (one run per kind at a time).

A job row lives in ``jobs``; the lease lives in ``job_locks`` (``_id`` = lock name, unique). The
worker renews the lease every ``HEARTBEAT_SECONDS``. If a deploy or crash kills the worker the
lease lapses; the next start takes it over and marks the orphaned ``running`` row ``abandoned``.
"""

from __future__ import annotations

import datetime as dt
import threading
import traceback
from typing import Callable

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

LEASE = dt.timedelta(minutes=5)
HEARTBEAT_SECONDS = 60


class JobConflict(RuntimeError):
    pass


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def claim_lock(db: Database, name: str, holder: str, now: dt.datetime) -> bool:
    """Take lease ``name`` if free or expired. Race-free: a live lease makes the upsert hit the unique _id."""
    try:
        db.job_locks.find_one_and_update({"_id": name, "expires_at": {"$lt": now}},
                                         {"$set": {"holder": holder, "expires_at": now + LEASE, "claimed_at": now}},
                                         upsert=True, return_document=ReturnDocument.AFTER)
        return True
    except DuplicateKeyError:
        return False


def start_job(db: Database, kind: str, work: Callable[[Callable[..., None]], dict | None], *,
              params: dict | None = None, run_in_thread: bool = True) -> str:
    """Run ``work(log)`` under the ``kind`` lease. ``log(**entry)`` appends progress; the returned dict
    is stored as the job's ``result``. Raises ``JobConflict`` if a live run of this kind exists."""
    now = _now()
    job_id = ObjectId()
    lock = f"job:{kind}"
    if not claim_lock(db, lock, str(job_id), now):
        raise JobConflict(f"a {kind} job is already running")
    db.jobs.update_many({"kind": kind, "status": "running"},
                        {"$set": {"status": "abandoned", "finished_at": now,
                                  "error": "worker stopped without finishing (lease expired)"}})
    db.jobs.insert_one({"_id": job_id, "kind": kind, "status": "running", "params": params or {},
                        "started_at": now, "progress": []})
    stop = threading.Event()

    def log(**entry):
        db.jobs.update_one({"_id": job_id}, {"$push": {"progress": {"at": _now(), **entry}}})

    def heartbeat():
        while not stop.wait(HEARTBEAT_SECONDS):
            db.job_locks.update_one({"_id": lock, "holder": str(job_id)}, {"$set": {"expires_at": _now() + LEASE}})

    def run():
        try:
            result = work(log)
            db.jobs.update_one({"_id": job_id}, {"$set": {"status": "completed", "finished_at": _now(),
                                                         "result": result or {}}})
        except Exception as e:
            db.jobs.update_one({"_id": job_id}, {"$set": {"status": "failed", "finished_at": _now(),
                                                         "error": f"{type(e).__name__}: {e}",
                                                         "traceback": traceback.format_exc()[-4000:]}})
        finally:
            stop.set()
            db.job_locks.delete_one({"_id": lock, "holder": str(job_id)})

    if run_in_thread:
        threading.Thread(target=heartbeat, daemon=True).start()
        threading.Thread(target=run, daemon=True).start()
    else:
        run()
    return str(job_id)


def get_job(db: Database, job_id: str, kind: str | None = None) -> dict | None:
    try:
        oid = ObjectId(job_id)
    except Exception:
        return None
    q = {"_id": oid} if kind is None else {"_id": oid, "kind": kind}
    doc = db.jobs.find_one(q, {"traceback": 0})
    if doc:
        doc["id"] = str(doc.pop("_id"))
    return doc
