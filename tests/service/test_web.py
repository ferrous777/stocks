import datetime as dt

import pytest
from fastapi.testclient import TestClient

from stocks_service import ingestion
from stocks_service.api.app import create_app
from stocks_service.settings import Settings
from stocks_service.strategies import sync_strategy_versions

from .conftest import NOW, NVDA_LONG, RecordedFetcher, load_yahoo

UTC = dt.timezone.utc
SECRET = "s" * 40


def _client(db, password="pw-123", https_only=True):
    s = Settings(mongo_url="mongodb://unused", api_keys="k", admin_password=password,
                 session_secret=SECRET if password else "", session_https_only=https_only)
    return TestClient(create_app(s, db=db), base_url="https://testserver" if https_only else "http://testserver")


def _login(c, password="pw-123"):
    return c.post("/login", data={"password": password}, follow_redirects=False)


def _load_nvda(db):
    db.symbols.insert_one({"_id": "NVDA", "asset_class": "equity", "sector": "Technology", "groups": ["technology"],
                           "enabled": True, "ca_version": 0})
    db.symbols.insert_one({"_id": "GLD", "asset_class": "etf", "groups": [], "enabled": True, "ca_version": 0})
    f = RecordedFetcher({("NVDA", "1d"): load_yahoo(NVDA_LONG)})
    ingestion.verify_basis(db, f, interval="1d", symbol="NVDA", split_ex_date=dt.date(2024, 6, 10), now=NOW)
    ingestion.ingest(db, f, symbol="NVDA", interval="1d", start=dt.datetime(2020, 6, 1, tzinfo=UTC), now=NOW,
                     buffer=dt.timedelta(minutes=20), overlap_tolerance=0.005, gap_threshold=0.47)


def test_website_disabled_without_password(db):
    with _client(db, password="") as c:
        assert c.get("/").status_code == 503
        assert c.get("/login").status_code == 503
        assert c.get("/health").status_code == 200  # API unaffected


def test_password_requires_session_secret(db):
    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        create_app(Settings(mongo_url="x", api_keys="k", admin_password="pw", session_secret="short"), db=db)


def test_login_flow(db):
    with _client(db) as c:
        r = c.get("/", follow_redirects=False)
        assert (r.status_code, r.headers["location"]) == (303, "/login")
        assert "Incorrect password" in _login(c, "wrong").text
        assert c.get("/", follow_redirects=False).status_code == 303
        r = _login(c)
        assert (r.status_code, r.headers["location"]) == (303, "/")
        assert c.get("/").status_code == 200
        c.post("/logout")
        assert c.get("/", follow_redirects=False).status_code == 303


def test_dashboard_empty_state_is_explicit(db):
    db.symbols.insert_one({"_id": "GLD", "asset_class": "etf", "groups": [], "enabled": True, "ca_version": 0})
    with _client(db) as c:
        _login(c)
        html = c.get("/").text
        assert "No price history loaded yet" in html and "GLD" in html and "no price history" in html


def test_dashboard_and_symbol_pages_show_real_data(db):
    _load_nvda(db)
    sync_strategy_versions(db, NOW)
    with _client(db) as c:
        _login(c)
        html = c.get("/").text
        assert "/symbol/NVDA" in html and "2025-06-02" in html  # last session of the recorded data
        assert "not recommendations" in html
        page = c.get("/symbol/NVDA").text
        assert "<polyline" in page and "macd@1" in page and "10:1" in page  # chart, decisions, the 2024 split
        assert "Entry limit" in page and "Target first" in page
        assert c.get("/symbol/ZZZZ").status_code == 404
        research = c.get("/research").text
        assert "No research report yet" in research and "ma_crossover@1" in research
        assert "No outlook yet" in c.get("/outlook").text


def test_session_cookie_is_secure_by_default(db):
    with _client(db) as c:
        cookie = _login(c).headers["set-cookie"].lower()
        assert "secure" in cookie and "httponly" in cookie and "samesite=lax" in cookie
    with _client(db, https_only=False) as c:  # explicit local-development opt-out
        assert "secure" not in _login(c).headers["set-cookie"].lower()


def test_non_ascii_passwords_are_compared_safely(db):
    with _client(db, password="pässwörd-✓") as c:
        assert "Incorrect password" in _login(c, "wrönġ").text  # no 500
        r = _login(c, "pässwörd-✓")
        assert (r.status_code, r.headers["location"]) == (303, "/")


def test_daily_change_is_not_distorted_by_a_split(db):
    """Raw closes 1208.88 -> 121.79 across NVDA's 10:1 split; the real move was about +0.75%."""
    _load_nvda(db)
    db.bars.delete_many({"symbol": "NVDA", "session": {"$gt": dt.datetime(2024, 6, 10, tzinfo=UTC)}})
    with _client(db) as c:
        _login(c)
        html = c.get("/").text
        assert "+0.75%" in html and "-89.9" not in html
