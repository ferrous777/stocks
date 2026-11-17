FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv
COPY requirements-service.txt .
RUN pip install -r requirements-service.txt

COPY stocks_service ./stocks_service
COPY config/system_config.yaml ./config/system_config.yaml

RUN useradd --create-home appuser
USER appuser

# Railway injects $PORT. Cron services override the start command (see railway.json / docs/railway_deployment.md).
CMD ["sh", "-c", "uvicorn stocks_service.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers"]
