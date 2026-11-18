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
    cal = db.calibrations.find_one(sort=[("created_at", -1), ("_id", -1)])
    if cal is None:
        raise HTTPException(404, "no calibration yet; run POST /api/v1/outlook/run")
    cal["id"] = str(cal.pop("_id"))
    return cal


# --- real accounts (phase 4b): JSON snapshots, executions, reconciliation ------------------

ACCOUNT_PATTERN = r"^[a-z0-9][a-z0-9_-]{1,40}$"
AccountPath = Path(pattern=ACCOUNT_PATTERN)


class AccountIn(BaseModel):
    account_id: str = Field(pattern=ACCOUNT_PATTERN)
    name: str = Field(min_length=1, max_length=100)


class SnapshotPosition(BaseModel):
    symbol: str = Field(pattern=SYMBOL_PATTERN)
    qty: float = Field(description="shares; negative for a short position")
    avg_cost: float | None = Field(default=None, gt=0, description="average cost per share (required for the opening snapshot)")


class SnapshotIn(BaseModel):
    as_of: dt.datetime = Field(description="when the broker positions were taken, with timezone")
    cash: float
    positions: list[SnapshotPosition] = Field(default_factory=list)
    opening: bool = Field(default=False, description="treat as the opening balance (only for an account with no history)")


class ExecutionIn(BaseModel):
    exec_id: str | None = Field(default=None, max_length=100, description="broker execution id (dedupe key)")
    symbol: str = Field(pattern=SYMBOL_PATTERN)
    side: Literal["buy", "sell", "short", "cover"]
    qty: float = Field(gt=0)
    price: float = Field(gt=0)
    fees: float = Field(default=0.0, ge=0)
    ts: dt.datetime


class ResolveIn(BaseModel):
    kind: Literal["transfer_in", "transfer_out", "manual_adjustment"]
    note: str = Field(min_length=3, max_length=500)
    cost_basis: float | None = Field(default=None, description="total cost of shares coming in; default: diff x snapshot avg_cost")


def _acct_call(fn, *a, **k):
    from ..accounts.service import AccountError, NotFound
    try:
        return fn(*a, **k)
    except NotFound as e:
        raise HTTPException(404, str(e))
    except AccountError as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _snap_out(res: dict) -> dict:
    snap = dict(res["snapshot"])
    snap["id"] = str(snap.pop("_id"))
    return {"snapshot": snap, "breaks": [_break_out(b) for b in res["breaks"]]}


def _break_out(b: dict) -> dict:
    b = dict(b)
    b["id"] = str(b.pop("_id"))
    b["snapshot_id"] = str(b["snapshot_id"])
    return b


@router.post("/accounts", status_code=status.HTTP_201_CREATED)
def create_account(body: AccountIn, db: Database = Depends(get_db)):
    from ..accounts import service
    return _acct_call(service.create_account, db, account_id=body.account_id, name=body.name, now=_now())


@router.get("/accounts")
def list_accounts(db: Database = Depends(get_db)):
    return list(db.accounts.find().sort("_id", 1))


@router.post("/accounts/{account_id}/snapshots", status_code=status.HTTP_201_CREATED)
def upload_snapshot(body: SnapshotIn, account_id: str = AccountPath, db: Database = Depends(get_db)):
    """Upload broker positions. The first snapshot of a new account is its opening balance; later ones are
    reconciled against the ledger and differences come back as breaks (never as trades). The response
    includes the account's outlook when one exists."""
    from ..accounts import service
    res = _acct_call(service.upload_snapshot, db, account_id, as_of=body.as_of, cash=body.cash,
                     positions=[p.model_dump() for p in body.positions], opening=body.opening, now=_now())
    out = _snap_out(res)
    try:
        out["outlook"] = service.account_outlook(db, account_id, _now())
    except service.NotFound as e:
        out["outlook"] = None
        out["outlook_unavailable"] = str(e)
    return out


@router.get("/accounts/{account_id}/snapshots")
def list_snapshots(account_id: str = AccountPath, db: Database = Depends(get_db)):
    docs = list(db.portfolio_snapshots.find({"account_id": account_id}).sort("as_of", -1))
    for d in docs:
        d["id"] = str(d.pop("_id"))
    return docs


@router.post("/accounts/{account_id}/executions", status_code=status.HTTP_201_CREATED)
def add_executions(body: list[ExecutionIn], account_id: str = AccountPath, db: Database = Depends(get_db)):
    from ..accounts import service
    return _acct_call(service.add_executions, db, account_id, [x.model_dump() for x in body], now=_now())


@router.get("/accounts/{account_id}/executions")
def list_executions(account_id: str = AccountPath, db: Database = Depends(get_db)):
    return [{k: v for k, v in x.items() if k != "_id"}
            for x in db.executions.find({"account_id": account_id}).sort("ts", -1)]


@router.get("/accounts/{account_id}/breaks")
def list_breaks(account_id: str = AccountPath, status_: Literal["open", "resolved"] | None = Query(None, alias="status"),
                db: Database = Depends(get_db)):
    q = {"account_id": account_id, **({"status": status_} if status_ else {})}
    return [_break_out(b) for b in db.reconciliation_breaks.find(q).sort([("as_of", -1), ("symbol", 1)])]


@router.post("/breaks/{break_id}/resolve")
def resolve_break(break_id: str, body: ResolveIn, db: Database = Depends(get_db)):
    from ..accounts import service
    res = _acct_call(service.resolve_break, db, break_id, kind=body.kind, note=body.note, now=_now(),
                     cost_basis=body.cost_basis)
    ev = {k: (str(v) if k == "break_id" else v) for k, v in res["event"].items() if k != "_id"}
    return {"event": ev, "breaks": [_break_out(b) for b in res["breaks"]]}


@router.get("/accounts/{account_id}/positions")
def account_positions(account_id: str = AccountPath, db: Database = Depends(get_db)):
    from ..accounts import service
    return _acct_call(service.holdings, db, account_id, _now())


@router.get("/accounts/{account_id}/outlook")
def account_outlook(account_id: str = AccountPath, db: Database = Depends(get_db)):
    from ..accounts import service
    return _acct_call(service.account_outlook, db, account_id, _now())


# --- scheduled tick (also runnable on demand) ------------------------------------------

@router.post("/admin/tick", status_code=status.HTTP_202_ACCEPTED)
def admin_tick(request: Request, db: Database = Depends(get_db)):
    """Run the cron tick now (incremental daily ingest + outlook refresh) as a background job."""
    from .. import jobs, tick
    try:
        job_id = tick.run_tick(db, request.app.state.fetcher, request.app.state.settings, run_in_thread=True)
    except jobs.JobConflict as e:
        raise HTTPException(409, str(e))
    return {"job_id": job_id, "status_url": f"/api/v1/admin/jobs/{job_id}"}


# --- risk profiles, tickets, actions, protective levels, notifications (phase 4c) -----------

class RiskProfileIn(BaseModel):
    profile_id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,40}$")
    version: int = Field(ge=1)
    risk_per_trade: float = Field(gt=0, le=0.05)
    max_position_pct: float = Field(gt=0, le=1)
    max_cluster_pct: float = Field(gt=0, le=1)
    max_heat_pct: float = Field(gt=0, le=0.5)
    gap_stress_atr: float = Field(ge=0, le=10)
    max_gross: float = Field(gt=0, le=2)
    max_short_pct: float = Field(ge=0, le=1)
    corr_threshold: float = Field(gt=0, le=1)
    min_adv_usd: float = Field(ge=0)
    max_adv_pct: float = Field(gt=0, le=1)
    note: str = Field(min_length=3, max_length=500)


@router.post("/risk-profiles", status_code=status.HTTP_201_CREATED)
def create_risk_profile(body: RiskProfileIn, db: Database = Depends(get_db)):
    doc = {"_id": f"{body.profile_id}@{body.version}", **body.model_dump(), "created_at": _now()}
    try:
        db.risk_profiles.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(409, f"{doc['_id']} already exists; profiles are immutable, create a new version")
    return doc


@router.get("/risk-profiles")
def list_risk_profiles(db: Database = Depends(get_db)):
    return list(db.risk_profiles.find().sort([("profile_id", 1), ("version", 1)]))


class AccountRiskIn(BaseModel):
    risk_profile: str = Field(pattern=r"^[a-z][a-z0-9_]{1,40}@[0-9]+$")


@router.put("/accounts/{account_id}/risk-profile")
def set_account_risk_profile(body: AccountRiskIn, account_id: str = AccountPath, db: Database = Depends(get_db)):
    if db.risk_profiles.find_one({"_id": body.risk_profile}) is None:
        raise HTTPException(404, f"risk profile {body.risk_profile} not found")
    res = db.accounts.update_one({"_id": account_id}, {"$set": {"risk_profile": body.risk_profile}})
    if res.matched_count == 0:
        raise HTTPException(404, f"account {account_id} not found")
    return {"account_id": account_id, "risk_profile": body.risk_profile}


@router.get("/accounts/{account_id}/tickets")
def account_tickets(account_id: str = AccountPath, db: Database = Depends(get_db)):
    """Order tickets for the next session. Produced only for rows backed by an active strategy version."""
    from ..accounts import tickets
    return _acct_call(tickets.build_tickets, db, account_id, _now())


class ActionIn(BaseModel):
    outlook_asof: dt.date
    symbol: str = Field(pattern=SYMBOL_PATTERN)
    side: Literal["long", "short"]
    action: Literal["taken", "skipped"]
    reason: str | None = Field(default=None, max_length=500)
    exec_ids: list[str] = Field(default_factory=list)
    stop: float | None = Field(default=None, gt=0)
    target: float | None = Field(default=None, gt=0)


@router.post("/accounts/{account_id}/actions", status_code=status.HTTP_201_CREATED)
def record_action(body: ActionIn, account_id: str = AccountPath, db: Database = Depends(get_db)):
    """Record what you did with an outlook row: taken (with its fills; sets protective levels) or skipped."""
    from ..accounts import tickets
    doc = _acct_call(tickets.record_action, db, account_id, outlook_asof=body.outlook_asof.isoformat(),
                     symbol=body.symbol, side=body.side, action=body.action, reason=body.reason,
                     exec_ids=body.exec_ids, stop=body.stop, target=body.target, now=_now())
    doc["id"] = str(doc.pop("_id"))
    doc["outlook_run"] = str(doc["outlook_run"])
    return doc


@router.get("/accounts/{account_id}/actions")
def list_actions(account_id: str = AccountPath, db: Database = Depends(get_db)):
    out = []
    for d in db.opportunity_actions.find({"account_id": account_id}).sort("created_at", -1):
        d["id"], d["outlook_run"] = str(d.pop("_id")), str(d["outlook_run"])
        out.append(d)
    return out


class LevelsIn(BaseModel):
    side: Literal["long", "short"]
    stop: float = Field(gt=0)
    target: float | None = Field(default=None, gt=0)
    timeout_session: dt.date | None = None
    note: str = Field(min_length=3, max_length=200)


@router.put("/accounts/{account_id}/levels/{symbol}")
def put_levels(body: LevelsIn, account_id: str = AccountPath, symbol: str = SymbolPath, db: Database = Depends(get_db)):
    """Set protective levels on any holding (e.g. an opening-balance position) so the tick watches it."""
    from ..accounts import tickets
    from ..accounts.service import get_account
    _acct_call(get_account, db, account_id)
    doc = _acct_call(tickets.set_levels, db, account_id, symbol=symbol, side=body.side, stop=body.stop,
                     target=body.target, timeout_session=body.timeout_session, source=f"manual:{body.note}", now=_now())
    doc["id"] = str(doc.pop("_id"))
    return doc


@router.get("/notifications")
def list_notifications(account_id: str | None = None, include_acknowledged: bool = False,
                       db: Database = Depends(get_db)):
    q = {**({"account_id": account_id} if account_id else {}), **({} if include_acknowledged else {"acknowledged": False})}
    out = []
    for d in db.notifications.find(q).sort("created_at", -1).limit(200):
        d["id"] = str(d.pop("_id"))
        d.pop("levels_id", None)
        out.append(d)
    return out


@router.post("/notifications/{notification_id}/ack")
def ack_notification(notification_id: str, db: Database = Depends(get_db)):
    from bson import ObjectId
    try:
        oid = ObjectId(notification_id)
    except Exception:
        raise HTTPException(404, "notification not found")
    res = db.notifications.update_one({"_id": oid}, {"$set": {"acknowledged": True, "acknowledged_at": _now()}})
    if res.matched_count == 0:
        raise HTTPException(404, "notification not found")
    return {"id": notification_id, "acknowledged": True}


# --- paper accounts (phase 5) ---------------------------------------------------------------

class PaperAccountIn(BaseModel):
    account_id: str = Field(pattern=ACCOUNT_PATTERN)
    name: str = Field(min_length=1, max_length=100)
    starting_cash: float = Field(gt=0, le=1e9)
    risk_profile: str = Field(pattern=r"^[a-z][a-z0-9_]{1,40}@[0-9]+$")
    cost_profile: str = Field(default="market@1", pattern=r"^[a-z][a-z0-9_]{1,40}@[0-9]+$")
    policy: Literal["agent", "baseline_v1@1"] = "agent"


class PaperOrderIn(BaseModel):
    symbol: str = Field(pattern=SYMBOL_PATTERN)
    side: Literal["long", "short"]
    qty: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=100)
    rationale: str = Field(min_length=3, max_length=2000)


def _order_out(o: dict) -> dict:
    o = dict(o)
    o["id"] = str(o.pop("_id"))
    return o


@router.post("/paper-accounts", status_code=status.HTTP_201_CREATED)
def create_paper_account(body: PaperAccountIn, db: Database = Depends(get_db)):
    """A simulated account. Its first trading session is the one after the last completed close."""
    from ..paper import broker
    return _acct_call(broker.create_paper_account, db, account_id=body.account_id, name=body.name,
                      starting_cash=body.starting_cash, risk_profile=body.risk_profile,
                      cost_profile=body.cost_profile, policy=body.policy, now=_now())


@router.post("/accounts/{account_id}/orders", status_code=status.HTTP_201_CREATED)
def place_paper_order(body: PaperOrderIn, request: Request, account_id: str = AccountPath,
                      db: Database = Depends(get_db)):
    """DAY limit order for the next session from the latest outlook row (paper accounts only; real -> 403)."""
    from ..paper import broker
    try:
        res = broker.place_order(db, account_id, symbol=body.symbol, side=body.side, qty=body.qty,
                                 idempotency_key=body.idempotency_key,
                                 decided_by={"via": "rest", "rationale": body.rationale}, now=_now())
    except broker.PaperOnly as e:
        raise HTTPException(403, str(e))
    except Exception as e:  # noqa: BLE001 - mapped consistently with the other account endpoints
        from ..accounts.service import AccountError, NotFound
        if isinstance(e, NotFound):
            raise HTTPException(404, str(e))
        if isinstance(e, (AccountError, ValueError)):
            raise HTTPException(409, str(e))
        raise
    return {**_order_out(res["order"]), "replayed": res["replayed"]}


@router.delete("/accounts/{account_id}/orders/{order_id}")
def cancel_paper_order(order_id: str = Path(pattern=r"^[0-9a-f]{24}$"), account_id: str = AccountPath,
                       db: Database = Depends(get_db)):
    from ..accounts.service import AccountError, NotFound
    from ..paper import broker
    try:
        return _order_out(broker.cancel_order(db, account_id, order_id, now=_now()))
    except broker.PaperOnly as e:          # subclass of AccountError: map it first
        raise HTTPException(403, str(e))
    except NotFound as e:
        raise HTTPException(404, str(e))
    except AccountError as e:
        raise HTTPException(409, str(e))


@router.get("/accounts/{account_id}/orders")
def list_orders(account_id: str = AccountPath, status_: str | None = Query(None, alias="status"),
                db: Database = Depends(get_db)):
    q = {"account_id": account_id, **({"status": status_} if status_ else {})}
    return [_order_out(o) for o in db.orders.find(q).sort("placed_at", -1).limit(500)]


@router.get("/accounts/{account_id}/equity")
def equity_curve(account_id: str = AccountPath, db: Database = Depends(get_db)):
    return [{k: v for k, v in e.items() if k != "_id"}
            for e in db.equity_curve.find({"account_id": account_id}).sort("session", 1)]
