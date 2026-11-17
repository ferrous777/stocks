"""Read-only migration from the legacy flat-file/SQLite stores.

Only the symbol universe is migrated. Legacy recommendation/backtest results are
development output and are intentionally not imported.

Nothing here modifies legacy files. Canonical bars come from a fresh Yahoo backfill
(consistent, verified basis); the legacy cache and SQLite snapshots are used only to
cross-check those bars in a reconciliation report.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path

import yaml
from pymongo.database import Database

from .ingestion import load_splits
from .models import AssetClass, SymbolIn
from .price_basis import split_factor_after

# Sector labels in the legacy YAML that describe a relationship worth grouping on.
# ETF / Mutual Fund / Benchmark are classifications, not relationships, so they get no group.
SECTOR_GROUPS = {
    "Technology": "technology",
    "Consumer": "consumer",
    "Healthcare": "healthcare",
    "Gold": "gold",
    "Semiconductors": "semiconductors",
    "Emerging Markets": "emerging_markets",
}
SECTOR_ASSET_CLASS = {"ETF": AssetClass.etf, "Benchmark": AssetClass.etf, "Mutual Fund": AssetClass.mutual_fund}

# Requested additions to the starting universe. MU and QQQM were added by commit e239ef0 but
# that change is missing from the current YAML; FCX and GLD were never configured.
ADDITIONS = [
    {"symbol": "MU", "asset_class": "equity", "sector": "Technology", "groups": ["technology"]},
    {"symbol": "QQQM", "asset_class": "etf", "sector": "ETF", "groups": []},
    {"symbol": "FCX", "asset_class": "equity", "sector": "Materials", "groups": []},
    {"symbol": "GLD", "asset_class": "etf", "sector": "Commodity", "groups": []},
]


def build_universe(yaml_path: Path) -> tuple[list[SymbolIn], dict[str, str]]:
    cfg = yaml.safe_load(yaml_path.read_text())
    entries = cfg.get("symbols") or []
    out: dict[str, SymbolIn] = {}
    for e in entries:
        sector = e.get("sector")
        out[e["symbol"]] = SymbolIn(
            symbol=e["symbol"],
            asset_class=SECTOR_ASSET_CLASS.get(sector, AssetClass.equity),
            sector=sector,
            groups=[SECTOR_GROUPS[sector]] if sector in SECTOR_GROUPS else [],
            enabled=bool(e.get("enabled", True)),
            priority=int(e.get("priority", 1)),
        )
    for a in ADDITIONS:
        if a["symbol"] not in out:
            out[a["symbol"]] = SymbolIn(**a)
    groups = {slug: label for label, slug in SECTOR_GROUPS.items()
              if any(slug in s.groups for s in out.values())}
    return sorted(out.values(), key=lambda s: s.symbol), groups


def apply_universe(db: Database, symbols: list[SymbolIn], groups: dict[str, str]) -> dict:
    now = dt.datetime.now(dt.timezone.utc)
    for slug, label in groups.items():
        db.groups.update_one({"_id": slug}, {"$setOnInsert": {"name": label, "description": None}}, upsert=True)
    inserted, existing = [], []
    for s in symbols:
        doc = s.model_dump(mode="json", exclude={"symbol"})
        doc.update({"_id": s.symbol, "ca_version": 0, "created_at": now, "origin": "legacy_migration"})
        res = db.symbols.update_one({"_id": s.symbol}, {"$setOnInsert": doc}, upsert=True)
        (inserted if res.upserted_id is not None else existing).append(s.symbol)
    return {"inserted": inserted, "already_present": existing}


# ---------------------------------------------------------------------------
# Bar reconciliation
# ---------------------------------------------------------------------------

def _compare(db: Database, symbol: str, legacy: dict[dt.date, float], tol: float) -> dict:
    splits = load_splits(db, symbol)
    mongo = {d["session"].date(): d["c"] for d in db.bars.find({"symbol": symbol, "interval": "1d"}, {"session": 1, "c": 1})}
    overlap = sorted(set(legacy) & set(mongo))
    mismatches = []
    max_rel = 0.0
    for day in overlap:
        # Legacy values are Yahoo split-adjusted as of their (unknown) fetch time; compare
        # against Mongo raw bars adjusted for all splits on file.
        adj = mongo[day] / split_factor_after(day, splits)
        rel = abs(adj - legacy[day]) / legacy[day]
        max_rel = max(max_rel, rel)
        if rel > tol:
            mismatches.append({"session": day.isoformat(), "legacy": legacy[day], "mongo_adjusted": adj})
    return {
        "legacy_count": len(legacy),
        "mongo_count": len(mongo),
        "overlap": len(overlap),
        "legacy_only": len(set(legacy) - set(mongo)),
        "legacy_range": [min(legacy).isoformat(), max(legacy).isoformat()] if legacy else None,
        "mismatches": len(mismatches),
        "max_rel_diff": max_rel,
        "mismatch_examples": mismatches[:5],
        "status": "ok" if not mismatches and overlap else ("no_overlap" if not overlap else "mismatch"),
    }


def reconcile_cache(db: Database, cache_dir: Path, tol: float = 0.005) -> dict:
    report = {}
    for f in sorted(cache_dir.glob("*_historical.json")):
        symbol = f.name.removesuffix("_historical.json")
        data = json.loads(f.read_text())
        legacy = {dt.date.fromisoformat(p["date"]): float(p["close"]) for p in data.get("data_points", [])}
        report[symbol] = _compare(db, symbol, legacy, tol)
        report[symbol]["in_universe"] = db.symbols.count_documents({"_id": symbol}) == 1
    return report


def reconcile_sqlite(db: Database, sqlite_path: Path, tol: float = 0.005) -> dict:
    con = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    try:
        rows = con.execute("select symbol, date, data from daily_snapshots").fetchall()
    finally:
        con.close()
    by_symbol: dict[str, dict[dt.date, float]] = {}
    for symbol, date, data in rows:
        by_symbol.setdefault(symbol, {})[dt.date.fromisoformat(date)] = float(json.loads(data)["close"])
    return {s: _compare(db, s, legacy, tol) for s, legacy in sorted(by_symbol.items())}
