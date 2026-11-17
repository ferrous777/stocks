"""Declarative index definitions; ``ensure_indexes`` is idempotent.

Only collections used by the current phase are listed; later phases add theirs here.
"""

from __future__ import annotations

from pymongo import ASCENDING, DESCENDING, IndexModel
from pymongo.database import Database

INDEXES: dict[str, list[IndexModel]] = {
    "symbols": [
        IndexModel([("groups", ASCENDING)], name="groups"),
        IndexModel([("asset_class", ASCENDING)], name="asset_class"),
        IndexModel([("enabled", ASCENDING), ("priority", ASCENDING)], name="enabled_priority"),
    ],
    "bars": [
        IndexModel([("symbol", ASCENDING), ("interval", ASCENDING), ("ts", ASCENDING)],
                   name="symbol_interval_ts", unique=True),
        IndexModel([("interval", ASCENDING), ("ts", ASCENDING)], name="interval_ts"),
        IndexModel([("symbol", ASCENDING), ("interval", ASCENDING), ("session", ASCENDING)],
                   name="symbol_interval_session"),
    ],
    "corporate_actions": [
        IndexModel([("symbol", ASCENDING), ("type", ASCENDING), ("ex_date", ASCENDING)],
                   name="symbol_type_exdate", unique=True),
        IndexModel([("ex_date", ASCENDING)], name="ex_date"),
    ],
    "signals": [
        IndexModel([("strategy", ASCENDING), ("symbol", ASCENDING), ("asof", ASCENDING)],
                   name="strategy_symbol_asof", unique=True),
        IndexModel([("symbol", ASCENDING), ("asof", DESCENDING)], name="symbol_asof"),
        IndexModel([("strategy", ASCENDING), ("asof", DESCENDING)], name="strategy_asof"),
    ],
    "strategy_versions": [
        IndexModel([("status", ASCENDING)], name="status"),
    ],
    "parity_violations": [
        IndexModel([("strategy", ASCENDING), ("detected_at", DESCENDING)], name="strategy_detected_at"),
    ],
    "migration_reports": [
        IndexModel([("created_at", DESCENDING)], name="created_at"),
    ],
    "ingest_log": [
        IndexModel([("symbol", ASCENDING), ("interval", ASCENDING), ("at", DESCENDING)], name="symbol_interval_at"),
    ],
    "job_locks": [
        IndexModel([("expires_at", ASCENDING)], name="ttl_expires_at", expireAfterSeconds=0),
    ],
}


def ensure_indexes(db: Database) -> dict[str, list[str]]:
    created: dict[str, list[str]] = {}
    for coll, models in INDEXES.items():
        created[coll] = db[coll].create_indexes(models)
    return created
