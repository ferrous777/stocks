"""Phase-1 REST endpoints: symbols, groups, bars, corporate actions, price sources."""

from __future__ import annotations

import datetime as dt
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError
from pydantic import BaseModel

from .. import ingestion
from ..ingestion import load_splits
from ..models import GROUP_PATTERN, SYMBOL_PATTERN, GroupIn, SymbolIn, SymbolPatch
from ..price_basis import to_split_adjusted
from .deps import get_db, require_api_key

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_key)])

SymbolPath = Path(pattern=SYMBOL_PATTERN)
GroupPath = Path(pattern=GROUP_PATTERN)


def _symbol_out(doc: dict) -> dict:
    out = {k: v for k, v in doc.items() if k != "_id"}
    out["symbol"] = doc["_id"]
    return out


def _missing_groups(db: Database, groups: list[str]) -> list[str]:
    known = {g["_id"] for g in db.groups.find({"_id": {"$in": groups}}, {"_id": 1})}
    return [g for g in groups if g not in known]


# --- symbols -----------------------------------------------------------------

@router.get("/symbols")
def list_symbols(db: Database = Depends(get_db), group: str | None = None, enabled: bool | None = None):
    q: dict = {}
    if group:
        q["groups"] = group
    if enabled is not None:
        q["enabled"] = enabled
    return [_symbol_out(d) for d in db.symbols.find(q).sort("_id", 1)]


@router.post("/symbols", status_code=status.HTTP_201_CREATED)
def create_symbol(body: SymbolIn, db: Database = Depends(get_db)):
    missing = _missing_groups(db, body.groups)
    if missing:
        raise HTTPException(422, f"unknown groups: {missing}; create them first via PUT /api/v1/groups/{{id}}")
    doc = body.model_dump(mode="json", exclude={"symbol"})
    doc.update({"_id": body.symbol, "ca_version": 0, "created_at": dt.datetime.now(dt.timezone.utc)})
    try:
        db.symbols.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(409, f"{body.symbol} already exists")
    return _symbol_out(doc)


@router.get("/symbols/{symbol}")
def get_symbol(symbol: str = SymbolPath, db: Database = Depends(get_db)):
    doc = db.symbols.find_one({"_id": symbol})
    if not doc:
        raise HTTPException(404, f"{symbol} not found")
    return _symbol_out(doc)


@router.patch("/symbols/{symbol}")
def patch_symbol(body: SymbolPatch, symbol: str = SymbolPath, db: Database = Depends(get_db)):
    changes = body.model_dump(mode="json", exclude_unset=True)
    if not changes:
        raise HTTPException(422, "no fields to update")
    if "groups" in changes:
        changes["groups"] = sorted(set(changes["groups"]))
        missing = _missing_groups(db, changes["groups"])
        if missing:
            raise HTTPException(422, f"unknown groups: {missing}")
    res = db.symbols.update_one({"_id": symbol}, {"$set": changes})
    if res.matched_count == 0:
        raise HTTPException(404, f"{symbol} not found")
    return _symbol_out(db.symbols.find_one({"_id": symbol}))


@router.delete("/symbols/{symbol}", status_code=status.HTTP_204_NO_CONTENT)
def delete_symbol(symbol: str = SymbolPath, db: Database = Depends(get_db)):
    """Removes the symbol from the universe. Its bars are kept (historical data is not destroyed)."""
    if db.symbols.delete_one({"_id": symbol}).deleted_count == 0:
        raise HTTPException(404, f"{symbol} not found")


@router.post("/symbols/{symbol}/quarantine/clear")
def clear_quarantine(note: str = Query(min_length=3), symbol: str = SymbolPath, db: Database = Depends(get_db)):
    doc = db.symbols.find_one({"_id": symbol})
    if not doc:
        raise HTTPException(404, f"{symbol} not found")
    if not doc.get("quarantine"):
        raise HTTPException(409, f"{symbol} is not quarantined")
    now = dt.datetime.now(dt.timezone.utc)
    db.symbols.update_one({"_id": symbol}, {
        "$unset": {"quarantine": ""},
        "$push": {"quarantine_history": {**doc["quarantine"], "cleared_at": now, "note": note}},
    })
    return _symbol_out(db.symbols.find_one({"_id": symbol}))


@router.post("/symbols/{symbol}/backfill")
def backfill(request: Request, symbol: str = SymbolPath, interval: Literal["1d", "1h"] = "1d",
             start: dt.date = Query(...), db: Database = Depends(get_db)):
    s = request.app.state.settings
    now = dt.datetime.now(dt.timezone.utc)
    try:
        res = ingestion.ingest(
            db, request.app.state.fetcher, symbol=symbol, interval=interval,
            start=dt.datetime(start.year, start.month, start.day, tzinfo=dt.timezone.utc), now=now,
            buffer=dt.timedelta(minutes=s.ingest_buffer_minutes), overlap_tolerance=s.overlap_tolerance,
            gap_threshold=s.unexplained_gap_log_threshold,
        )
    except ingestion.UnknownSymbol as e:
        raise HTTPException(404, str(e))
    except (ingestion.SymbolQuarantined, ingestion.BasisNotVerified) as e:
        raise HTTPException(409, str(e))
    return res.__dict__


# --- groups ------------------------------------------------------------------

@router.get("/groups")
def list_groups(db: Database = Depends(get_db)):
    return [{"id": g["_id"], **{k: v for k, v in g.items() if k != "_id"}} for g in db.groups.find().sort("_id", 1)]


@router.put("/groups/{group_id}")
def put_group(body: GroupIn, group_id: str = GroupPath, db: Database = Depends(get_db)):
    db.groups.update_one({"_id": group_id}, {"$set": body.model_dump()}, upsert=True)
    return get_group(group_id, db)


@router.get("/groups/{group_id}")
def get_group(group_id: str = GroupPath, db: Database = Depends(get_db)):
    g = db.groups.find_one({"_id": group_id})
    if not g:
        raise HTTPException(404, f"group {group_id} not found")
    members = [d["_id"] for d in db.symbols.find({"groups": group_id}, {"_id": 1}).sort("_id", 1)]
    return {"id": group_id, "name": g["name"], "description": g.get("description"), "members": members}


@router.delete("/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_group(group_id: str = GroupPath, db: Database = Depends(get_db)):
    members = db.symbols.count_documents({"groups": group_id})
    if members:
        raise HTTPException(409, f"group {group_id} still has {members} member symbols; remove them first")
    if db.groups.delete_one({"_id": group_id}).deleted_count == 0:
        raise HTTPException(404, f"group {group_id} not found")


# --- market data -------------------------------------------------------------

@router.get("/bars/{symbol}")
def get_bars(
    symbol: str = SymbolPath,
    interval: Literal["1d", "1h"] = "1d",
    start: dt.date | None = None,
    end: dt.date | None = None,
    basis: Literal["raw", "split_adjusted"] = "raw",
    asof: dt.date | None = Query(default=None, description="split_adjusted only: use splits with ex_date <= asof"),
    limit: int = Query(default=1000, ge=1, le=10000),
    db: Database = Depends(get_db),
):
    q: dict = {"symbol": symbol, "interval": interval}
    rng = {}
    if start:
        rng["$gte"] = dt.datetime(start.year, start.month, start.day, tzinfo=dt.timezone.utc)
    if end:
        rng["$lte"] = dt.datetime(end.year, end.month, end.day, tzinfo=dt.timezone.utc)
    if rng:
        q["session"] = rng
    docs = list(db.bars.find(q).sort("ts", -1).limit(limit))
    docs.reverse()
    splits = load_splits(db, symbol) if basis == "split_adjusted" else []
    cutoff = asof or dt.datetime.now(dt.timezone.utc).date()
    out = []
    for d in docs:
        bar = {"session": d["session"].date(), "o": d["o"], "h": d["h"], "l": d["l"], "c": d["c"], "v": d["v"]}
        if basis == "split_adjusted":
            bar = to_split_adjusted(bar, splits, asof=cutoff)
        out.append({"symbol": symbol, "interval": interval, "ts": d["ts"], "ts_end": d["ts_end"], **bar,
                    "basis": basis})
    return out


@router.get("/corporate-actions/{symbol}")
def get_corporate_actions(symbol: str = SymbolPath, db: Database = Depends(get_db)):
    return [{k: v for k, v in d.items() if k != "_id"} for d in
            db.corporate_actions.find({"symbol": symbol}).sort("ex_date", 1)]


@router.get("/price-sources")
def get_price_sources(db: Database = Depends(get_db)):
    return list(db.price_sources.find())


# --- admin: data load jobs (no shell access to the service required) -----------

class LoadRequest(BaseModel):
    steps: list[str]
    symbols: list[str] | None = None


@router.post("/admin/load", status_code=status.HTTP_202_ACCEPTED)
def admin_load(body: LoadRequest, request: Request, db: Database = Depends(get_db)):
    from .. import admin
    try:
        job_id = admin.start_load(db, request.app.state.fetcher, request.app.state.settings, body.steps, body.symbols)
    except ValueError as e:
        raise HTTPException(422, str(e))
    except admin.JobRunning as e:
        raise HTTPException(409, str(e))
    return {"job_id": job_id, "status_url": f"/api/v1/admin/jobs/{job_id}"}


@router.get("/admin/jobs/{job_id}")
def admin_job(job_id: str, db: Database = Depends(get_db)):
    from .. import admin
    job = admin.get_job(db, job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return job
