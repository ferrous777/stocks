"""Fixtures for stocks_service tests.

These tests need a MongoDB **replica set** (transactions). Locally:

    mongod --replSet rs0 --port 27027 --dbpath <dir>   # then: mongosh --port 27027 --eval 'rs.initiate()'

Set STOCKS_TEST_MONGO_URL to override the default. If MongoDB is unreachable the
tests fail with an explicit message rather than being skipped.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import uuid
from pathlib import Path

import pytest
from pymongo import MongoClient

from stocks_service.db_indexes import ensure_indexes

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
YAHOO = FIXTURES / "yahoo"
DEFAULT_URL = "mongodb://127.0.0.1:27027/?replicaSet=rs0&directConnection=true"
UTC = dt.timezone.utc


def load_yahoo(name: str) -> dict:
    return json.loads((YAHOO / f"{name}.json").read_text())


@pytest.fixture(scope="session")
def mongo_client():
    url = os.environ.get("STOCKS_TEST_MONGO_URL", DEFAULT_URL)
    client = MongoClient(url, tz_aware=True, serverSelectionTimeoutMS=3000)
    try:
        hello = client.admin.command("hello")
    except Exception as e:
        pytest.fail(f"MongoDB test replica set unreachable at {url}: {e}", pytrace=False)
    if not hello.get("setName"):
        pytest.fail(f"MongoDB at {url} is standalone; tests require a replica set", pytrace=False)
    yield client
    client.close()


@pytest.fixture
def db(mongo_client):
    name = f"stocks_test_{uuid.uuid4().hex[:12]}"
    database = mongo_client[name]
    ensure_indexes(database)
    yield database
    mongo_client.drop_database(name)


class RecordedFetcher:
    """Serves recorded real Yahoo responses keyed by (symbol, interval); records calls."""

    def __init__(self, payloads: dict[tuple[str, str], dict]):
        self.payloads = payloads
        self.calls: list[tuple[str, str, int, int]] = []

    def fetch_chart(self, symbol, interval, period1, period2):
        self.calls.append((symbol, interval, period1, period2))
        try:
            return json.loads(json.dumps(self.payloads[(symbol, interval)]))  # deep copy
        except KeyError:
            raise AssertionError(f"no recorded payload for {(symbol, interval)}")


@pytest.fixture
def fetcher():
    return RecordedFetcher({
        ("NVDA", "1d"): load_yahoo("NVDA_1d_2024-05-01_2024-07-15"),
        ("ORLY", "1h"): load_yahoo("ORLY_1h_2025-06-03_2025-06-17"),
        ("ORLY", "1d"): load_yahoo("ORLY_1d_2025-06-03_2025-06-17"),
    })


# Fixed "now" after the recorded data was fetched; keeps tests deterministic.
NOW = dt.datetime(2026, 11, 16, 23, 0, tzinfo=UTC)

_RAW_CACHE: dict[str, tuple] = {}


def raw_daily(name: str, symbol: str):
    """(raw bars, splits) from a recorded daily Yahoo payload, normalized like ingestion does."""
    if name not in _RAW_CACHE:
        from stocks_service.price_basis import Basis, to_raw
        from stocks_service.yahoo import parse_chart
        parsed = parse_chart(load_yahoo(name), symbol=symbol, interval="1d",
                             window_start=dt.datetime(1990, 1, 2, tzinfo=UTC), window_end=NOW, complete_before=NOW)
        bars = [to_raw(b, parsed.splits, price_basis=Basis.SPLIT_ADJUSTED, volume_basis=Basis.SPLIT_ADJUSTED)
                for b in parsed.bars]
        _RAW_CACHE[name] = (bars, parsed.splits)
    return _RAW_CACHE[name]


NVDA_LONG = "NVDA_1d_2020-06-01_2025-06-02"
INTC_LONG = "INTC_1d_2020-06-01_2025-06-02"
