from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pymongo.database import Database

from .. import __version__
from ..db import connect, get_database, require_replica_set
from ..db_indexes import ensure_indexes
from ..settings import Settings, get_settings
from ..yahoo import ChartFetcher, YahooChartClient
from .routes import router


def create_app(settings: Settings | None = None, *, db: Database | None = None,
               fetcher: ChartFetcher | None = None) -> FastAPI:
    settings = settings or get_settings()
    keys = settings.api_key_list()
    if not keys:
        raise RuntimeError("STOCKS_API_KEYS is empty: refusing to start an unauthenticated API")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        client = None
        if app.state.db is None:
            client = connect(settings.mongo_url)
            app.state.db = get_database(client, settings.mongo_db)
        else:
            require_replica_set(app.state.db.client)
        ensure_indexes(app.state.db)
        yield
        if client is not None:
            client.close()

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

    app.include_router(router)
    return app
