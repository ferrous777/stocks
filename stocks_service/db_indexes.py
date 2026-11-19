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
        IndexModel([("strategy", ASCENDING), ("symbol", ASCENDING), ("asof", ASCENDING), ("source", ASCENDING)],
                   name="strategy_symbol_asof_source", unique=True),
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
    "cost_profiles": [
        IndexModel([("profile_id", ASCENDING), ("version", ASCENDING)], name="profile_version", unique=True),
    ],
    "calibrations": [
        IndexModel([("created_at", DESCENDING)], name="created_at"),
    ],
    "outlook_runs": [
        IndexModel([("created_at", DESCENDING)], name="created_at"),
    ],
    "jobs": [
        IndexModel([("kind", ASCENDING), ("status", ASCENDING)], name="kind_status"),
    ],
    "ledger_events": [
        IndexModel([("account_id", ASCENDING), ("kind", ASCENDING), ("ref", ASCENDING)], name="account_kind_ref",
                   unique=True),
        IndexModel([("account_id", ASCENDING), ("ts", ASCENDING)], name="account_ts"),
    ],
    "executions": [
        IndexModel([("account_id", ASCENDING), ("exec_id", ASCENDING)], name="account_exec", unique=True),
        IndexModel([("account_id", ASCENDING), ("ts", ASCENDING)], name="account_ts"),
        IndexModel([("account_id", ASCENDING), ("symbol", ASCENDING), ("ts", ASCENDING)], name="account_symbol_ts"),
    ],
    "portfolio_snapshots": [
        IndexModel([("account_id", ASCENDING), ("as_of", DESCENDING)], name="account_asof"),
    ],
    "reconciliation_breaks": [
        IndexModel([("snapshot_id", ASCENDING), ("symbol", ASCENDING)], name="snapshot_symbol", unique=True),
        IndexModel([("account_id", ASCENDING), ("status", ASCENDING)], name="account_status"),
    ],
    "risk_profiles": [
        IndexModel([("profile_id", ASCENDING), ("version", ASCENDING)], name="profile_version", unique=True),
    ],
    "opportunity_actions": [
        IndexModel([("account_id", ASCENDING), ("created_at", DESCENDING)], name="account_created"),
    ],
    "position_levels": [
        IndexModel([("account_id", ASCENDING), ("symbol", ASCENDING), ("active", ASCENDING)], name="account_symbol_active"),
        IndexModel([("active", ASCENDING)], name="active"),
    ],
    "notifications": [
        IndexModel([("dedupe_key", ASCENDING)], name="dedupe_key", unique=True),
        IndexModel([("account_id", ASCENDING), ("created_at", DESCENDING)], name="account_created"),
    ],
    "orders": [
        IndexModel([("account_id", ASCENDING), ("idempotency_key", ASCENDING)], name="account_idem", unique=True),
        IndexModel([("account_id", ASCENDING), ("status", ASCENDING)], name="account_status"),
        IndexModel([("account_id", ASCENDING), ("placed_at", DESCENDING)], name="account_placed"),
    ],
    "equity_curve": [
        IndexModel([("account_id", ASCENDING), ("session", ASCENDING)], name="account_session", unique=True),
    ],
    "forecast_outcomes": [
        IndexModel([("asof", ASCENDING), ("symbol", ASCENDING), ("side", ASCENDING)], name="asof_symbol_side",
                   unique=True),
        IndexModel([("source", ASCENDING), ("resolved_session", DESCENDING)], name="source_resolved"),
    ],
    "lifecycle_events": [
        IndexModel([("strategy", ASCENDING), ("at", DESCENDING)], name="strategy_at"),
    ],
    "relationships": [
        IndexModel([("a", ASCENDING), ("b", ASCENDING), ("window", ASCENDING)], name="a_b_window", unique=True),
        IndexModel([("b", ASCENDING), ("window", ASCENDING)], name="b_window"),
    ],
    "overlay_evaluations": [
        IndexModel([("created_at", DESCENDING)], name="created_at"),
    ],
    "umpire_models": [
        IndexModel([("created_at", DESCENDING)], name="created_at"),
    ],
    "param_sets": [
        IndexModel([("strategy", ASCENDING), ("created_at", DESCENDING)], name="strategy_created"),
    ],
    "mcp_confirmations": [   # single-use confirmation tokens for MCP changes
        IndexModel([("expires_at", ASCENDING)], name="ttl_expires_at", expireAfterSeconds=0),
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
