"""Server-rendered website (Jinja2), protected by a single admin password and a signed session cookie."""

from __future__ import annotations

import hmac
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pymongo.database import Database

from ..api.deps import get_db
from ..models import SYMBOL_PATTERN
from . import data

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
router = APIRouter(include_in_schema=False)


class LoginRequired(Exception):
    pass


def website_enabled(request: Request) -> bool:
    return bool(request.app.state.settings.admin_password)


def require_login(request: Request) -> None:
    if not website_enabled(request):
        raise HTTPException(503, "Website disabled: set STOCKS_ADMIN_PASSWORD and STOCKS_SESSION_SECRET.")
    if not request.session.get("user"):
        raise LoginRequired()


def _render(request: Request, name: str, **ctx):
    return templates.TemplateResponse(request, name, {"page": name.removesuffix(".html"), **ctx})


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    if not website_enabled(request):
        raise HTTPException(503, "Website disabled: set STOCKS_ADMIN_PASSWORD and STOCKS_SESSION_SECRET.")
    return _render(request, "login.html", error=None)


@router.post("/login", response_class=HTMLResponse)
def login(request: Request, password: str = Form(...)):
    if not website_enabled(request):
        raise HTTPException(503, "Website disabled.")
    if not hmac.compare_digest(password, request.app.state.settings.admin_password):
        return _render(request, "login.html", error="Incorrect password.")
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


@router.get("/outlook", response_class=HTMLResponse, dependencies=[Depends(require_login)])
def outlook(request: Request):
    return _render(request, "outlook.html")
