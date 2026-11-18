"""Shared cluster mapping for paper sizing: explicit groups + 252-day correlation clusters as of an outlook.

Every placement (REST, MCP, baseline) applies the same clusters to existing holdings, open orders and
the candidate order.
"""

from __future__ import annotations

import datetime as dt
import threading

from pymongo.database import Database

from ..accounts.risk import cluster_keys, correlation_clusters
from ..research.protocol import load_universe

_cache: dict[tuple[str, str, float], dict[str, int]] = {}
_lock = threading.Lock()


def cluster_map(db: Database, asof: str, threshold: float) -> tuple[dict[str, list[str]], dict[str, int]]:
    """(groups, correlation clusters). Groups are read fresh (they can be edited at any time); only the
    correlation clusters, which depend on stored history up to ``asof``, are cached per database."""
    groups = {s["_id"]: s.get("groups", []) for s in db.symbols.find({}, {"groups": 1})}
    key = (db.name, asof, threshold)
    with _lock:
        corr = _cache.get(key)
    if corr is None:
        uni, tradable = load_universe(db)
        d = dt.date.fromisoformat(asof)
        corr = correlation_clusters(uni, [s for s in tradable if uni[s].has_bar(d)], d, threshold)
        with _lock:
            _cache.clear()           # only the latest outlook is needed
            _cache[key] = corr
    return groups, corr


def keys_for(symbol: str, groups: dict, corr: dict) -> set[str]:
    return cluster_keys(symbol, groups, corr)
