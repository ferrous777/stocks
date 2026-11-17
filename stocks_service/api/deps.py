from __future__ import annotations

import hmac

from fastapi import Depends, Header, HTTPException, Request, status
from pymongo.database import Database


def get_db(request: Request) -> Database:
    return request.app.state.db


def require_api_key(request: Request, x_api_key: str | None = Header(default=None)) -> None:
    keys: list[str] = request.app.state.api_keys
    if not x_api_key or not any(hmac.compare_digest(x_api_key, k) for k in keys):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing or invalid X-API-Key")


Authed = Depends(require_api_key)
