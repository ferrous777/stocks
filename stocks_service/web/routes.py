"""Server-rendered website (Jinja2), protected by a secret sign-in link and/or a password, and a signed
session cookie (90 days)."""

from __future__ import annotations

import functools
import hashlib
import hmac
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pymongo.database import Database

from ..api.deps import get_db
from ..models import SYMBOL_PATTERN
from . import data

STATIC_DIR = Path(__file__).parent / "static"
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _asset_url(name: str) -> str:
    """URL of a static file with a content hash, so browsers refetch it after each deploy."""
    digest = hashlib.sha256((STATIC_DIR / name).read_bytes()).hexdigest()[:12]
    return f"/static/{name}?v={digest}"


templates.env.globals["asset"] = functools.cache(_asset_url)
router = APIRouter(include_in_schema=False)


class LoginRequired(Exception):
    pass


def website_enabled(request: Request) -> bool:
    s = request.app.state.settings
    return bool(s.admin_password or s.login_token)


def require_login(request: Request) -> None:
    if not website_enabled(request):
        raise HTTPException(503, "Website disabled: set STOCKS_LOGIN_TOKEN (or STOCKS_ADMIN_PASSWORD) and STOCKS_SESSION_SECRET.")
    if not request.session.get("user"):
        raise LoginRequired()


def _render(request: Request, name: str, **ctx):
    return templates.TemplateResponse(request, name, {"page": name.removesuffix(".html"), **ctx})


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    if not website_enabled(request):
        raise HTTPException(503, "Website disabled: set STOCKS_LOGIN_TOKEN (or STOCKS_ADMIN_PASSWORD) and STOCKS_SESSION_SECRET.")
    return _render(request, "login.html", error=None, password_enabled=bool(request.app.state.settings.admin_password))


@router.post("/login/link", response_class=HTMLResponse)
def login_link(request: Request, token: str = Form(...)):
    """Sign in with the token from the bookmark ``/login#<token>``.

    The token lives in the URL *fragment*, which browsers never send to the server, so it cannot
    appear in access or proxy logs; the login page's script posts it here in the request body.
    """
    secret = request.app.state.settings.login_token
    if not secret or not hmac.compare_digest(token.encode("utf-8"), secret.encode("utf-8")):
        return _render(request, "login.html", error="That sign-in link is not valid.",
                       password_enabled=bool(request.app.state.settings.admin_password))
    request.session["user"] = "admin"
    return RedirectResponse("/", status_code=303)


@router.post("/login", response_class=HTMLResponse)
def login(request: Request, password: str = Form(...)):
    if not request.app.state.settings.admin_password:
        raise HTTPException(404, "Password sign-in is not enabled; use your sign-in link.")
    # compare_digest only accepts ASCII str; compare UTF-8 bytes so any password works.
    if not hmac.compare_digest(password.encode("utf-8"), request.app.state.settings.admin_password.encode("utf-8")):
        return _render(request, "login.html", error="Incorrect password.", password_enabled=True)
    request.session["user"] = "admin"
    return RedirectResponse("/", status_code=303)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@router.get("/", response_class=HTMLResponse, dependencies=[Depends(require_login)])
def dashboard(request: Request, db: Database = Depends(get_db)):
    return _render(request, "dashboard.html", **data.overview(db))


@router.get("/symbol/{symbol}", response_class=HTMLResponse, dependencies=[Depends(require_login)])
def symbol_page(request: Request, symbol: str, db: Database = Depends(get_db)):
    import re
    if not re.fullmatch(SYMBOL_PATTERN, symbol):
        raise HTTPException(404, "Unknown symbol")
    detail = data.symbol_detail(db, symbol)
    if detail is None:
        raise HTTPException(404, f"{symbol} is not in the universe")
    return _render(request, "symbol.html", d=detail)


@router.get("/research", response_class=HTMLResponse, dependencies=[Depends(require_login)])
def research(request: Request, db: Database = Depends(get_db)):
    return _render(request, "research.html", **data.research_status(db))


@router.get("/paper", response_class=HTMLResponse, dependencies=[Depends(require_login)])
def paper(request: Request, db: Database = Depends(get_db)):
    return _render(request, "paper.html", **data.paper_status(db))


@router.get("/outlook", response_class=HTMLResponse, dependencies=[Depends(require_login)])
def outlook(request: Request, side: str | None = None, db: Database = Depends(get_db)):
    return _render(request, "outlook.html", **data.outlook_status(db, side))


@router.get("/connect", response_class=HTMLResponse, dependencies=[Depends(require_login)])
async def connect(request: Request, db: Database = Depends(get_db)):
    """How to connect an AI agent to the MCP server: endpoint, auth, client setup and the live tool list."""
    tools = await request.app.state.mcp.list_tools()
    return _render(request, "connect.html", **data.mcp_connect(db, str(request.base_url), tools,
                                                               request.app.state.api_keys))


# --- accounts ---------------------------------------------------------------------------------

def _account_page(request: Request, db: Database, account_id: str, message: str | None = None,
                  error: str | None = None, draft: dict | None = None):
    import datetime as _dt
    from ..accounts import service
    try:
        acc = service.get_account(db, account_id)
    except service.NotFound:
        raise HTTPException(404, "Unknown account")
    now = _dt.datetime.now(_dt.timezone.utc)
    h = service.holdings(db, account_id, now)
    try:
        o = service.account_outlook(db, account_id, now)
        rows = [r for r in o["rows"] if r.get("kind") != "new" or r["grade"] in ("A", "B")]
    except service.NotFound:
        o, rows = None, []
    breaks = list(db.reconciliation_breaks.find({"account_id": account_id}).sort([("status", 1), ("as_of", -1)]).limit(50))
    alerts = list(db.notifications.find({"account_id": account_id, "acknowledged": False}).sort("created_at", -1).limit(20))
    from ..accounts import tickets as _tickets
    from ..ingestion import load_splits
    levels = {}
    for lv in db.position_levels.find({"account_id": account_id, "active": True}):
        latest = _tickets._latest_session(db, lv["symbol"])  # show levels on today's price basis (after splits)
        levels[lv["symbol"]] = {**lv, **(_tickets.levels_on(lv, latest, load_splits(db, lv["symbol"])) if latest else {})}
    try:
        tk = _tickets.build_tickets(db, account_id, now) if o else None
    except (service.AccountError, service.NotFound) as e:
        tk = {"tickets": [], "withheld": [], "note": str(e)}
    snaps = list(db.portfolio_snapshots.find({"account_id": account_id}, {"positions": 0}).sort("as_of", -1).limit(10))
    return _render(request, "account.html", acc=acc, h=h, outlook=o, rows=rows, breaks=breaks, snaps=snaps,
                   alerts=alerts, levels=levels, tk=tk,
                   message=message, error=error, draft=draft or {})


@router.get("/accounts", response_class=HTMLResponse, dependencies=[Depends(require_login)])
def accounts(request: Request, db: Database = Depends(get_db)):
    accs = list(db.accounts.find().sort("_id", 1))
    for a in accs:
        a["open_breaks"] = db.reconciliation_breaks.count_documents({"account_id": a["_id"], "status": "open"})
        last = db.portfolio_snapshots.find_one({"account_id": a["_id"]}, sort=[("as_of", -1)])
        a["latest_snapshot"] = last["as_of"] if last else None
    return _render(request, "accounts.html", accounts=accs, error=None)


@router.post("/accounts", response_class=HTMLResponse, dependencies=[Depends(require_login)])
def create_account_form(request: Request, account_id: str = Form(...), name: str = Form(...),
                        db: Database = Depends(get_db)):
    import datetime as _dt
    import re
    from ..accounts import service
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,40}", account_id):
        return _render(request, "accounts.html", accounts=list(db.accounts.find()),
                       error="Account id: lowercase letters, digits, - or _ (2-41 characters).")
    try:
        service.create_account(db, account_id=account_id, name=name.strip() or account_id,
                               now=_dt.datetime.now(_dt.timezone.utc))
    except service.AccountError as e:
        return _render(request, "accounts.html", accounts=list(db.accounts.find()), error=str(e))
    return RedirectResponse(f"/accounts/{account_id}", status_code=303)


@router.get("/accounts/{account_id}", response_class=HTMLResponse, dependencies=[Depends(require_login)])
def account_page(request: Request, account_id: str, db: Database = Depends(get_db)):
    return _account_page(request, db, account_id)


@router.post("/accounts/{account_id}/upload", response_class=HTMLResponse, dependencies=[Depends(require_login)])
def account_upload(request: Request, account_id: str, kind: str = Form(...), payload: str = Form(...),
                   db: Database = Depends(get_db)):
    """Paste-in JSON upload; validated by the same models and service as the API."""
    import datetime as _dt
    import json
    from pydantic import TypeAdapter, ValidationError
    from ..accounts import service
    from ..api.routes import ExecutionIn, SnapshotIn
    now = _dt.datetime.now(_dt.timezone.utc)
    try:
        raw = json.loads(payload)
        if kind == "snapshot":
            body = SnapshotIn.model_validate(raw)
            res = service.upload_snapshot(db, account_id, as_of=body.as_of, cash=body.cash, opening=body.opening,
                                          positions=[p.model_dump() for p in body.positions], now=now)
            n = len([b for b in res["breaks"] if b["status"] == "open"])
            msg = ("Opening balance recorded." if res["snapshot"]["opening"]
                   else f"Snapshot reconciled: {n} open difference(s).")
        elif kind == "executions":
            items = TypeAdapter(list[ExecutionIn]).validate_python(raw if isinstance(raw, list) else [raw])
            res = service.add_executions(db, account_id, [x.model_dump() for x in items], now=now)
            msg = f"{res['inserted']} fill(s) recorded, {res['duplicates']} duplicate(s) skipped."
        else:
            raise HTTPException(422, "kind must be snapshot or executions")
    except service.NotFound:
        raise HTTPException(404, "Unknown account")
    except (json.JSONDecodeError, ValidationError, service.AccountError, ValueError) as e:
        return _account_page(request, db, account_id, error=f"Not saved: {e}", draft={kind: payload})
    return _account_page(request, db, account_id, message=msg)
