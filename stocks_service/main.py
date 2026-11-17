"""ASGI entry point: ``uvicorn stocks_service.main:app``."""

from .api.app import create_app

app = create_app()
