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


def price_history(view) -> dict:
    """Every daily close on the view's split-adjusted basis, for the interactive chart."""
    return {"dates": [d.isoformat() for d in view.sessions], "closes": [float(f"{c:.6g}") for c in view.c]}


def yearly_summary(view) -> list[dict]:
    """Calendar-year rows, newest first: the return is measured from the previous year's last close (as
    the year overlay chart is), or from the first close on file for the first year (``partial``)."""
    rows: list[dict] = []
    prev_close = None
    by_year: dict[int, list[tuple[dt.date, float]]] = {}
    for d, c in zip(view.sessions, view.c):
        by_year.setdefault(d.year, []).append((d, float(c)))
    for year in sorted(by_year):
        pts = by_year[year]
        base = prev_close if prev_close is not None else pts[0][1]
        closes = [c for _, c in pts]
        rows.append({"year": year, "sessions": len(pts), "first": pts[0][0], "last": pts[-1][0],
                     "base": base, "close": closes[-1], "return": closes[-1] / base - 1,
                     "high": max(closes), "low": min(closes),
                     "partial": prev_close is None, "to_date": year == view.asof.year})
        prev_close = closes[-1]
    return rows[::-1]


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
    full = load_view(db, symbol, asof, lookback=0)   # whole history for the chart and yearly table
    out.update({
        "asof": asof,
        "last_close": float(view.c[-1]),
        "chart": _chart_points(view),
        "history": price_history(full),
        "years": yearly_summary(full),
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
    from .. import lifecycle
    from ..research.protocol import _finite
    versions = list(db.strategy_versions.find().sort("_id", 1))
    for v in versions:
        v["monitor"] = lifecycle.monitor(db, f"signal:{v['_id']}")
        v["resolved_forecasts"] = db.forecast_outcomes.count_documents({"source": f"signal:{v['_id']}"})
    latest = lambda coll, **q: _finite({k: x for k, x in (db[coll].find_one(q, sort=[("created_at", -1), ("_id", -1)])  # noqa: E731
                                                          or {}).items() if k != "_id"}) or None
    ump = db.umpire_models.find_one(sort=[("created_at", -1), ("_id", -1)],
                                    projection={"sides.long.data": 0, "sides.short.data": 0, "_id": 0})
    return {
        "versions": versions,
        "experiments": db.experiments.count_documents({}),
        "report": latest_report(db),
        "holdout": holdout,
        "overlays": [_finite({k: x for k, x in d.items() if k != "_id"})
                     for d in db.overlay_evaluations.find().sort("created_at", -1).limit(6)],
        "tuning": latest("param_sets"),
        "umpires": _finite(ump) if ump else None,
        "events": list(db.lifecycle_events.find({}, {"_id": 0}).sort("at", -1).limit(10)),
    }


def paper_status(db: Database) -> dict:
    from ..paper import read
    rows = read.summaries(db)          # leaderboard: best return first
    comparisons = [c for c in (read.comparison(db, a) for a in db.accounts.find({"kind": "paper", "policy": "agent"})
                               .sort("_id", 1)) if c is not None]
    decisions = db.agent_decisions.count_documents({})
    return {"leaderboard": rows, "comparisons": comparisons, "decisions": decisions}


def paper_account(db: Database, account_id: str, *, now: dt.datetime, limit: int | None = 200) -> dict | None:
    """One paper account: summary, equity curve, positions, orders, transactions, baseline comparison.
    ``limit`` caps the orders and transactions shown (newest first); None shows the complete history."""
    from ..accounts import service
    from ..paper import read
    acc = db.accounts.find_one({"_id": account_id, "kind": "paper"})
    if acc is None:
        return None
    perf = read.performance(db, account_id)
    try:
        h = service.holdings(db, account_id, now)
    except service.AccountError as e:   # e.g. a held symbol has no price: say so instead of guessing
        h = {"positions": [], "error": str(e)}
    return {
        "acc": acc, "s": read.summary(db, acc), "perf": perf, "holdings": h,
        "history": {"dates": [p["session"] for p in perf["curve"]], "closes": [p["equity"] for p in perf["curve"]]},
        "orders": list(db.orders.find({"account_id": account_id}).sort("placed_at", -1).limit(limit or 0)),
        "order_count": db.orders.count_documents({"account_id": account_id}),
        "tx": _all_transactions(db, account_id, now) if limit is None else read.transactions(db, account_id, limit=limit, now=now),
        "limit": limit,
        "comparison": read.comparison(db, acc),
    }


def _all_transactions(db: Database, account_id: str, now: dt.datetime) -> dict:
    from ..paper import read
    rows, cursor = [], None
    splits = read.split_rows(db, account_id, now)   # derived once for every page
    while True:
        page = read.transactions(db, account_id, limit=500, cursor=cursor, now=now, splits=splits)
        rows += page["transactions"]
        cursor = page["next_cursor"]
        if cursor is None:
            return {"account_id": account_id, "transactions": rows, "next_cursor": None}


def outlook_status(db: Database, side: str | None = None) -> dict:
    from ..outlook.build import latest_outlook
    doc = latest_outlook(db)
    if doc and side in ("long", "short"):
        doc["rows"] = [r for r in doc["rows"] if r["side"] == side]
    cal = db.calibrations.find_one(sort=[("created_at", -1), ("_id", -1)], projection={"buckets": 0})
    return {"outlook": doc, "calibration": cal, "side": side}


IDENTITY_PARAMS = ("agent_id", "model_id", "prompt_version")


def mcp_connect(db: Database, base_url: str, tools: list, api_keys: list[str]) -> dict:
    """Facts for the Connect page, all read from the running server: its URL, the tools the MCP server
    registers (name, description, parameters) and the paper accounts an agent may trade."""
    rows = []
    for t in tools:
        schema = t.inputSchema or {}
        required = set(schema.get("required") or [])
        params = [{"name": n, "type": p.get("type") or "/".join(x.get("type", "?") for x in p.get("anyOf", [])),
                   "required": n in required, "default": p.get("default")}
                  for n, p in (schema.get("properties") or {}).items() if n not in IDENTITY_PARAMS]
        rows.append({"name": t.name, "description": (t.description or "").strip(), "params": params})
    from ..paper.report import matching_baseline
    agents = []
    for a in db.accounts.find({"kind": "paper", "policy": "agent"}).sort("_id", 1):
        base, why = matching_baseline(db, a)          # the same pairing the Paper page and the gate use
        agents.append({"_id": a["_id"], "name": a.get("name", ""), "baseline": base, "pairing": why})
    return {
        "endpoint": base_url.rstrip("/") + "/mcp",
        "tools": rows,
        "identity_params": IDENTITY_PARAMS,
        "agent_accounts": agents,
        "key_count": len(api_keys),
    }
