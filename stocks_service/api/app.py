from __future__ import annotations

import re

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from pymongo.database import Database

from .. import __version__
from ..db import connect, get_database, require_replica_set
from ..db_indexes import ensure_indexes
from ..settings import Settings, get_settings
from ..yahoo import ChartFetcher, YahooChartClient
from ..web.routes import STATIC_DIR, LoginRequired
from ..web.routes import router as web_router
from .routes import router


def create_app(settings: Settings | None = None, *, db: Database | None = None,
               fetcher: ChartFetcher | None = None) -> FastAPI:
    settings = settings or get_settings()
    keys = settings.api_key_list()
    if not keys:
        raise RuntimeError("STOCKS_API_KEYS is empty: refusing to start an unauthenticated API")
    if settings.login_token and not re.fullmatch(r"[A-Za-z0-9_-]{32,}", settings.login_token):
        raise RuntimeError("STOCKS_LOGIN_TOKEN must be at least 32 URL-safe characters (A-Z a-z 0-9 _ -), "
                           "e.g. python -c 'import secrets; print(secrets.token_urlsafe(32))'")
    if (settings.admin_password or settings.login_token) and len(settings.session_secret) < 32:
        raise RuntimeError("STOCKS_SESSION_SECRET must be set (>= 32 chars) when a website login is configured")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        client = None
        if app.state.db is None:
            client = connect(settings.mongo_url)
            app.state.db = get_database(client, settings.mongo_db)
        else:
            require_replica_set(app.state.db.client)
        ensure_indexes(app.state.db)
        # Record registered strategy versions (new ones start as `research`; never promotes or resets status).
        import datetime as _dt
        from ..strategies import sync_strategy_versions
        sync_strategy_versions(app.state.db, _dt.datetime.now(_dt.timezone.utc))
        async with mcp.session_manager.run():  # MCP streamable-HTTP transport (stateless)
            yield
        if client is not None:
            client.close()

    from ..mcp_server import McpPath, _Auth, build_mcp
    mcp = build_mcp(lambda: app.state.db, lambda: app.state.fetcher, lambda: app.state.settings)

    app = FastAPI(title="Stocks Service", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.api_keys = keys
    app.state.db = db
    app.state.fetcher = fetcher or YahooChartClient(settings.yahoo_user_agent, settings.yahoo_timeout_seconds)

    @app.get("/health")
    def health(request: Request):
        try:
            set_name = require_replica_set(request.app.state.db.client)
            request.app.state.db.command("ping")
        except Exception as e:  # report, don't hide
            return JSONResponse(status_code=503, content={"status": "unhealthy", "error": str(e)})
        return {"status": "ok", "version": __version__, "replica_set": set_name}

    # Session cookie for the website; a random per-process secret when the website is disabled.
    import secrets as _secrets
    app.add_middleware(SessionMiddleware, secret_key=settings.session_secret or _secrets.token_urlsafe(32),
                       https_only=settings.session_https_only, same_site="lax", max_age=90 * 24 * 3600)

    @app.exception_handler(LoginRequired)
    def _login_required(request: Request, exc: LoginRequired):
        return RedirectResponse("/login", status_code=303)

    app.include_router(router)
    app.include_router(web_router)
    # Stylesheet etc. for the website; public, contains no data.
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    # MCP for the external AI agent: bearer = an API key; paper accounts only.
    app.mount("/mcp", _Auth(mcp.streamable_http_app(), keys))
    app.add_middleware(McpPath)
    from ..ops import RequestTimer   # request timing per route and hour (the Ops page)
    app.add_middleware(RequestTimer, get_db=lambda: app.state.db)
    app.state.mcp = mcp
    return app
