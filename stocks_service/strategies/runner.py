"""The single entry point for strategy decisions.

Live runs, historical replay, backtests and evaluation all call ``run_decision`` (or
``decide`` with a view built by ``load_view``), so identical inputs give identical
decisions everywhere. ``check_parity`` recomputes a stored live decision and pauses
the strategy version if they differ.
"""

from __future__ import annotations

import dataclasses
import datetime as dt

from pymongo.database import Database

from ..ingestion import load_splits
from .base import Decision, StrategySpec, all_specs, get_spec
from .view import PointInTimeView

# Bars loaded per decision. Every ported strategy needs <= 250; loading a fixed window
# (rather than "all history") keeps live and replay inputs identical.
LOOKBACK_BARS = 400


def _d(day: dt.date) -> dt.datetime:
    return dt.datetime(day.year, day.month, day.day, tzinfo=dt.timezone.utc)


def decide(view: PointInTimeView, spec: StrategySpec) -> Decision:
    if len(view) < spec.min_bars:
        return Decision(spec.key, view.symbol, view.asof, "hold", 0.0, ("insufficient_bars",), {}, len(view))
    s = spec.fn(view, spec.params)
    return Decision(spec.key, view.symbol, view.asof, s.direction, s.strength, s.reasons, dict(s.features), len(view))


def load_view(db: Database, symbol: str, asof: dt.date, lookback: int = LOOKBACK_BARS) -> PointInTimeView:
    docs = list(db.bars.find({"symbol": symbol, "interval": "1d", "session": {"$lte": _d(asof)}},
                             {"session": 1, "o": 1, "h": 1, "l": 1, "c": 1, "v": 1})
                .sort("session", -1).limit(lookback))   # lookback=0: no limit (all history)
    bars = [{"session": d["session"].date(), "o": d["o"], "h": d["h"], "l": d["l"], "c": d["c"], "v": d["v"]}
            for d in docs]
    return PointInTimeView.from_raw(symbol, bars, load_splits(db, symbol), asof)


def run_decision(db: Database, symbol: str, asof: dt.date, strategy_key: str) -> Decision:
    return decide(load_view(db, symbol, asof), get_spec(strategy_key))


# ---------------------------------------------------------------------------
# Persistence, registry sync and parity
# ---------------------------------------------------------------------------

def _doc(decision: Decision) -> dict:
    d = dataclasses.asdict(decision)
    d["asof"] = _d(decision.asof)
    d["reasons"] = list(decision.reasons)
    return d


LIVE = "live"


def persist_decision(db: Database, decision: Decision, *, source: str, now: dt.datetime) -> bool:
    """Store a decision under (strategy, symbol, asof, source).

    The first ``live`` snapshot is immutable: later live writes for the same key never replace it,
    so parity always compares against what was actually decided at the time. Other sources
    (e.g. ``replay``) are stored separately and may be refreshed. Returns True if a document was
    created or updated.
    """
    key = {"strategy": decision.strategy, "symbol": decision.symbol, "asof": _d(decision.asof), "source": source}
    doc = {**_doc(decision), "source": source}
    if source == LIVE:
        res = db.signals.update_one(key, {"$setOnInsert": {**doc, "created_at": now}}, upsert=True)
        return res.upserted_id is not None
    res = db.signals.update_one(key, {"$set": {**doc, "updated_at": now}, "$setOnInsert": {"created_at": now}},
                                upsert=True)
    return res.upserted_id is not None or res.modified_count > 0


def sync_strategy_versions(db: Database, now: dt.datetime) -> list[str]:
    """Record every registered version; new ones start as `research` (never auto-promoted)."""
    added = []
    for spec in all_specs():
        res = db.strategy_versions.update_one(
            {"_id": spec.key},
            {"$setOnInsert": {"name": spec.name, "version": spec.version, "params": spec.params,
                              "min_bars": spec.min_bars, "description": spec.description, "status": "research",
                              "created_at": now}},
            upsert=True,
        )
        if res.upserted_id is not None:
            added.append(spec.key)
    return added


class ParityViolation(RuntimeError):
    pass


def check_parity(db: Database, strategy_key: str, symbol: str, asof: dt.date, *, now: dt.datetime,
                 pause: bool = True) -> bool:
    """Recompute the stored *live* decision; on mismatch record a violation and (unless the caller
    handles it, e.g. ``lifecycle.run_parity``) pause the version."""
    stored = db.signals.find_one({"strategy": strategy_key, "symbol": symbol, "asof": _d(asof), "source": LIVE})
    if stored is None:
        raise LookupError(f"no stored live decision for {strategy_key} {symbol} {asof}")
    replay = _doc(run_decision(db, symbol, asof, strategy_key))
    fields = ("direction", "strength", "reasons", "features", "bars_used")
    diffs = {f: {"live": stored.get(f), "replay": replay[f]} for f in fields if stored.get(f) != replay[f]}
    if not diffs:
        return True
    db.parity_violations.insert_one({"strategy": strategy_key, "symbol": symbol, "asof": _d(asof), "diffs": diffs,
                                     "detected_at": now})
    if not pause:
        return False
    db.strategy_versions.update_one(
        {"_id": strategy_key},
        {"$set": {"status": "paused", "paused_reason": "parity_violation", "paused_at": now}},
    )
    return False
