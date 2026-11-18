"""Phase-1 REST endpoints: symbols, groups, bars, corporate actions, price sources."""

from __future__ import annotations

import datetime as dt
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError
from pydantic import BaseModel, Field

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
    update = {
        "$unset": {"quarantine": ""},
        "$push": {"quarantine_history": {**doc["quarantine"], "cleared_at": now, "note": note}},
    }
    q = doc["quarantine"]
    if q.get("reason") == "unexplained_gap" and q.get("details", {}).get("session"):
        # Record the reviewed gap so re-ingesting the same history does not quarantine it again.
        update["$addToSet"] = {"accepted_gaps": q["details"]["session"]}
    db.symbols.update_one({"_id": symbol}, update)
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


# --- research (phase 3 validation) ---------------------------------------------------

@router.get("/research/report")
def research_report(db: Database = Depends(get_db)):
    from ..research.protocol import latest_report
    rep = latest_report(db)
    if rep is None:
        raise HTTPException(404, "no research report yet; run POST /api/v1/research/run")
    return rep


@router.post("/research/run", status_code=status.HTTP_202_ACCEPTED)
def research_run(db: Database = Depends(get_db), dev_start: dt.date = dt.date(2006, 1, 3),
                 dev_end: dt.date = dt.date(2024, 11, 15), holdout_start: dt.date = dt.date(2024, 11, 18)):
    from ..research.protocol import HoldoutError, start_development_job
    if dev_end >= holdout_start:
        raise HTTPException(422, "dev_end must be before holdout_start")
    try:
        job_id = start_development_job(db, dev_start=dev_start, dev_end=dev_end, holdout_start=holdout_start)
    except (RuntimeError, HoldoutError) as e:
        raise HTTPException(409, str(e))
    return {"job_id": job_id}


@router.get("/research/jobs/{job_id}")
def research_job(job_id: str, db: Database = Depends(get_db)):
    from bson import ObjectId
    try:
        doc = db.jobs.find_one({"_id": ObjectId(job_id), "kind": "research"})
    except Exception:
        doc = None
    if doc is None:
        raise HTTPException(404, "job not found")
    doc["id"] = str(doc.pop("_id"))
    return doc


# --- cost profiles (explicit, versioned, immutable once created) ------------------------

class CostProfileIn(BaseModel):
    profile_id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,40}$")
    version: int = Field(ge=1)
    commission_per_share: float = Field(ge=0)
    min_commission: float = Field(ge=0)
    half_spread_bps: float = Field(ge=0)
    slippage_bps: float = Field(ge=0)
    borrow_rate_annual: float | None = Field(default=..., ge=0)  # null disables shorts under this profile
    note: str = Field(min_length=3, max_length=500)


@router.post("/cost-profiles", status_code=status.HTTP_201_CREATED)
def create_cost_profile(body: CostProfileIn, db: Database = Depends(get_db)):
    doc = {"_id": f"{body.profile_id}@{body.version}", **body.model_dump(), "created_at": dt.datetime.now(dt.timezone.utc)}
    try:
        db.cost_profiles.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(409, f"{doc['_id']} already exists; profiles are immutable, create a new version")
    return doc


@router.get("/cost-profiles")
def list_cost_profiles(db: Database = Depends(get_db)):
    return list(db.cost_profiles.find().sort([("profile_id", 1), ("version", 1)]))


# --- six-month outlook (phase 4) -----------------------------------------------------------

class OutlookRunIn(BaseModel):
    steps: list[Literal["calibrate", "outlook"]] = Field(default=["calibrate", "outlook"], min_length=1)


@router.post("/outlook/run", status_code=status.HTTP_202_ACCEPTED)
def outlook_run(body: OutlookRunIn, db: Database = Depends(get_db)):
    from ..jobs import JobConflict
    from ..outlook.build import start_outlook_job
    try:
        job_id = start_outlook_job(db, steps=list(body.steps))
    except JobConflict as e:
        raise HTTPException(409, str(e))
    return {"job_id": job_id, "status_url": f"/api/v1/outlook/jobs/{job_id}"}


@router.get("/outlook/jobs/{job_id}")
def outlook_job(job_id: str, db: Database = Depends(get_db)):
    from ..jobs import get_job
    doc = get_job(db, job_id, kind="outlook")
    if doc is None:
        raise HTTPException(404, "job not found")
    return doc


@router.get("/outlook")
def outlook(db: Database = Depends(get_db), side: Literal["long", "short"] | None = None,
            sort: Literal["return", "per_session", "evidence", "downside"] = "return",
            min_grade: Literal["A", "B", "C", "insufficient"] = "insufficient", limit: int = Query(200, ge=1, le=1000)):
    """Latest six-month outlook: every watched symbol x side, sorted by expected 6-month net return."""
    from ..outlook.build import GRADE_ORDER, latest_outlook
    doc = latest_outlook(db)
    if doc is None:
        raise HTTPException(404, "no outlook yet; run POST /api/v1/outlook/run")
    rows = [r for r in doc["rows"] if (side is None or r["side"] == side)
            and GRADE_ORDER[r["grade"]] <= GRADE_ORDER[min_grade]]
    neg = -1e9
    keys = {
        "return": lambda r: -(r.get("exp_return_6m") if r.get("exp_return_6m") is not None else neg),
        "per_session": lambda r: -(r.get("exp_return_per_session") if r.get("exp_return_per_session") is not None else neg),
        "evidence": lambda r: (GRADE_ORDER[r["grade"]], -(r.get("exp_return_6m") or neg)),
        "downside": lambda r: -(r.get("p10_return_6m") if r.get("p10_return_6m") is not None else neg),
    }
    rows.sort(key=keys[sort])
    doc["rows"] = rows[:limit]
    return doc


@router.get("/outlook/calibration")
def outlook_calibration(db: Database = Depends(get_db)):
    cal = db.calibrations.find_one(sort=[("created_at", -1)])
    if cal is None:
        raise HTTPException(404, "no calibration yet; run POST /api/v1/outlook/run")
    cal["id"] = str(cal.pop("_id"))
    return cal
