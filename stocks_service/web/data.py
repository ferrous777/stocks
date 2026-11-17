"""Read models for the website. Everything shown is computed from stored data; nothing is invented.

Sections that depend on later plan phases (validated research, the six-month outlook) report an
explicit "not available yet" state rather than placeholder numbers.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from pymongo.database import Database

from .. import estimation
from ..ingestion import load_splits
from ..levels import LevelsUnavailable, atr_levels
from ..strategies import Decision, all_specs, decide
from ..strategies.runner import load_view

STRATEGY_KEYS = [s.key for s in all_specs()]


@dataclass
class SymbolRow:
    symbol: str
    asset_class: str
    sector: str | None
    groups: list[str]
    enabled: bool
    quarantine: str | None
    last_session: dt.date | None
    last_close: float | None
    change_pct: float | None
    decisions: dict[str, Decision] = field(default_factory=dict)


def _last_daily(db: Database, symbol: str) -> list[dict]:
    return list(db.bars.find({"symbol": symbol, "interval": "1d"}, {"session": 1, "c": 1})
                .sort("session", -1).limit(2))


def overview(db: Database) -> dict:
    rows: list[SymbolRow] = []
    for s in db.symbols.find().sort("_id", 1):
        last = _last_daily(db, s["_id"])
        row = SymbolRow(
            symbol=s["_id"], asset_class=s.get("asset_class", ""), sector=s.get("sector"),
            groups=s.get("groups", []), enabled=s.get("enabled", True),
            quarantine=(s.get("quarantine") or {}).get("reason"),
            last_session=last[0]["session"].date() if last else None,
            last_close=last[0]["c"] if last else None,
            change_pct=None,
        )
        if row.last_session is not None:
            view = load_view(db, row.symbol, row.last_session)
            # Stored closes are raw; compare on the view's split-adjusted basis so a split is not a "move".
            if len(view) >= 2:
                row.change_pct = float(view.c[-1] / view.c[-2] - 1)
            row.decisions = {spec.key: decide(view, spec) for spec in all_specs()}
        rows.append(row)
    versions = {v["_id"]: v.get("status", "unregistered") for v in db.strategy_versions.find()}
    return {
        "rows": rows,
        "strategy_keys": STRATEGY_KEYS,
        "strategy_status": {k: versions.get(k, "research") for k in STRATEGY_KEYS},
        "loaded": sum(1 for r in rows if r.last_session is not None),
        "price_sources": list(db.price_sources.find()),
    }


def _chart_points(view, width: int = 760, height: int = 220, pad: int = 8) -> dict | None:
    closes = list(view.c[-260:])
    sessions = list(view.sessions[-260:])
    if len(closes) < 2:
        return None
    lo, hi = min(closes), max(closes)
    span = (hi - lo) or 1.0
    step = (width - 2 * pad) / (len(closes) - 1)
    pts = " ".join(f"{pad + i * step:.1f},{pad + (hi - c) / span * (height - 2 * pad):.1f}"
                   for i, c in enumerate(closes))
    return {"points": pts, "width": width, "height": height, "lo": lo, "hi": hi,
            "first": sessions[0], "last": sessions[-1], "n": len(closes)}


def symbol_detail(db: Database, symbol: str) -> dict | None:
    sym = db.symbols.find_one({"_id": symbol})
    if sym is None:
        return None
    last = _last_daily(db, symbol)
    out: dict = {"symbol": symbol, "meta": sym, "has_data": bool(last),
                 "corporate_actions": list(db.corporate_actions.find({"symbol": symbol}).sort("ex_date", -1).limit(20))}
    if not last:
        return out
    asof = last[0]["session"].date()
    view = load_view(db, symbol, asof)
    out.update({
        "asof": asof,
        "last_close": float(view.c[-1]),
        "chart": _chart_points(view),
        "basis_note": "Split-adjusted as of " + asof.isoformat(),
        "decisions": [decide(view, spec) for spec in all_specs()],
        "splits": load_splits(db, symbol),
    })
    sides = {}
    for side in ("long", "short"):
        try:
            lv = atr_levels(view, side)
        except LevelsUnavailable as e:
            sides[side] = {"error": str(e)}
            continue
        est = estimation.ensemble_estimate(view, lv.entry_limit, lv.target, lv.stop, side)
        sides[side] = {"levels": lv, "estimate": est}
    out["sides"] = sides
    return out


def research_status(db: Database) -> dict:
    from ..research.protocol import latest_report
    holdout = db.holdouts.find_one({"_id": "primary"})
    return {
        "versions": list(db.strategy_versions.find().sort("_id", 1)),
        "experiments": db.experiments.count_documents({}),
        "report": latest_report(db),
        "holdout": holdout,
    }
