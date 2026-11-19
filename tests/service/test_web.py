import datetime as dt
import re

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


TOKEN = "t" * 40


def _link_client(db, password=""):
    s = Settings(mongo_url="mongodb://unused", api_keys="k", admin_password=password, login_token=TOKEN,
                 session_secret=SECRET)
    return TestClient(create_app(s, db=db), base_url="https://testserver")


def test_sign_in_link(db):
    with _link_client(db) as c:
        assert c.get("/", follow_redirects=False).headers["location"] == "/login"
        page = c.get("/login").text
        assert "sign-in link" in page and 'type="password"' not in page  # no password form without a password
        assert 'action="/login/link"' in page and "location.hash" in page  # token read from the fragment
        bad = c.post("/login/link", data={"token": "x" * 40}, follow_redirects=False)
        assert bad.status_code == 200 and "not valid" in bad.text
        assert c.get("/", follow_redirects=False).status_code == 303
        assert c.get("/login/" + TOKEN).status_code in (404, 405)  # never accepted in the URL path (logged)
        r = c.post("/login/link", data={"token": TOKEN}, follow_redirects=False)
        assert (r.status_code, r.headers["location"]) == (303, "/")
        assert "max-age=7776000" in r.headers["set-cookie"].lower()  # 90 days
        assert c.get("/", follow_redirects=False).status_code == 200
        assert c.post("/login", data={"password": "anything"}).status_code == 404  # password sign-in disabled


@pytest.mark.parametrize("token", ["short", "a/b" + "c" * 40, "+" * 40, "x" * 31])
def test_sign_in_token_must_be_long_and_url_safe(db, token):
    with pytest.raises(RuntimeError, match="URL-safe"):
        create_app(Settings(mongo_url="x", api_keys="k", login_token=token, session_secret=SECRET), db=db)


def _current_nav(html):
    """Labels of the main-nav links marked as the current page."""
    import re
    nav = html.split('aria-label="Main"', 1)[1].split("</nav>", 1)[0]
    return re.findall(r'<a class="nav__link" href="[^"]*" aria-current="page">([^<]+)</a>', nav)


def test_navigation_marks_the_current_page(db):
    _load_nvda(db)
    with _client(db) as c:
        _login(c)
        assert _current_nav(c.get("/").text) == ["Dashboard"]
        assert _current_nav(c.get("/symbol/NVDA").text) == ["Dashboard"]   # a symbol page belongs to the dashboard
        assert _current_nav(c.get("/outlook").text) == ["Outlook"]
        assert _current_nav(c.get("/accounts").text) == ["Accounts"]
        assert _current_nav(c.get("/paper").text) == ["Paper"]
        assert _current_nav(c.get("/research").text) == ["Research"]


def test_outlook_side_filter_marks_the_selection(db, monkeypatch):
    from stocks_service.web import data
    outlook = {"asof": "2026-11-17", "placeable_until": "2026-11-18T14:30:00+00:00", "cash_return_6m": 0.02,
            "cost_profile": "market@1", "cost": {"half_spread_bps": 2, "slippage_bps": 3}, "rows": []}
    monkeypatch.setattr(data, "outlook_status", lambda db, side: {"outlook": outlook, "side": side})
    with _client(db) as c:
        _login(c)
        html = c.get("/outlook?side=short").text
    assert '<a class="segmented__item" href="/outlook?side=short" aria-current="true">Short</a>' in html
    assert html.count('aria-current="true"') == 1   # only the selected filter, not "Both"


def test_stylesheet_is_served_with_a_content_hash(db):
    import hashlib
    from stocks_service.web.routes import STATIC_DIR
    css = (STATIC_DIR / "app.css").read_bytes()
    with _client(db) as c:
        html = c.get("/login").text
        url = f"/static/app.css?v={hashlib.sha256(css).hexdigest()[:12]}"
        assert f'href="{url}"' in html
        r = c.get(url)   # public: the login page needs it before sign-in
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/css")
    assert b"--color-accent" in r.content and b'[data-theme="dark"]' in r.content


def test_symbol_page_carries_full_history_and_calendar_years(db):
    import json
    import re
    from stocks_service.strategies.runner import load_view
    from stocks_service.web.data import yearly_summary
    _load_nvda(db)
    with _client(db) as c:
        _login(c)
        page = c.get("/symbol/NVDA").text
    assert "<polyline" in page                                           # no-JS fallback stays
    assert re.search(r'src="/static/chart\.js\?v=\w{12}"', page)
    hist = json.loads(re.search(r'<script type="application/json" id="price-history">(.*?)</script>', page, re.S).group(1))
    full = load_view(db, "NVDA", dt.date(2025, 6, 2), lookback=0)
    assert len(hist["dates"]) == len(full) > 400                        # whole history, not the 400-bar strategy window
    assert hist["dates"][0] == full.sessions[0].isoformat() and hist["dates"][-1] == "2025-06-02"
    # Split-adjusted: no 10x cliff across the 2024-06-10 split.
    i = hist["dates"].index("2024-06-10")
    assert 0.8 < hist["closes"][i] / hist["closes"][i - 1] < 1.2
    years = yearly_summary(full)
    assert "Calendar years" in page and f"{years[0]['year']}" in page and "to date" in page
    by = {y["year"]: y for y in years}
    # Each year is measured from the previous year's last close; the first year from its own first close.
    assert by[2024]["base"] == by[2023]["close"]
    assert by[2024]["return"] == pytest.approx(by[2024]["close"] / by[2023]["close"] - 1)
    first = years[-1]
    assert first["partial"] and first["base"] == float(full.c[0])
    assert years[0]["to_date"] and not years[1]["to_date"]


def test_only_identifier_columns_are_pinned_on_phones(db):
    _load_nvda(db)
    with _client(db) as c:
        _login(c)
        dashboard, research = c.get("/").text, c.get("/research").text
    assert 'class="table table--pin-first"' in dashboard          # symbol column stays visible
    assert "table--pin-first" not in research                       # long descriptive first cells scroll normally


def test_connect_page_documents_the_live_mcp_server(db):
    from stocks_service.paper import broker
    db.risk_profiles.insert_one({"_id": "default@1"})
    db.cost_profiles.insert_one({"_id": "market@1"})
    broker.create_paper_account(db, account_id="paper-agent", name="AI agent", starting_cash=100_000.0,
                                risk_profile="default@1", now=NOW)
    db.accounts.insert_one({"_id": "fidelity", "kind": "real", "name": "Brokerage"})
    with _client(db) as c:
        _login(c)
        page = c.get("/connect").text
        mcp = c.app.state.mcp
        import anyio
        live = anyio.run(mcp.list_tools)
    assert _current_nav(page) == ["Connect"]
    nav = page.split('aria-label="Main"', 1)[1].split("</nav>", 1)[0]
    assert re.findall(r'class="nav__link" href="([^"]+)"', nav)[-2:] == ["/docs", "/connect"]   # Connect follows API
    endpoint = "https://testserver/mcp"
    assert page.count(endpoint) >= 5                          # every snippet points at this server
    for t in live:                                              # the tool table is the server's own registry
        assert f"<code>{t.name}</code>" in page
    assert "<code>idempotency_key</code>" in page and "<code>agent_id</code>, <code>model_id</code>, <code>prompt_version</code>" in page
    assert "claude mcp add --transport http stocks " + endpoint in page
    assert "mcp-client-2025-11-20" in page and "mcp_toolset" in page
    assert "<code>paper-agent</code>" in page and "<code>fidelity</code>" not in page   # the real account is never offered for trading
    assert "no baseline: " in page                                          # unpaired: says why, invents nothing
    # With a baseline of identical capital and profiles, the agent's row names the same pairing the gate uses.
    from stocks_service.paper import baseline as bl
    broker.create_paper_account(db, account_id="paper-baseline", name="Baseline", starting_cash=100_000.0,
                                risk_profile="default@1", policy=bl.POLICY_ID, now=NOW)
    with _client(db) as c:
        _login(c)
        page = c.get("/connect").text
    assert "<code>paper-baseline</code>" in page and "no baseline: " not in page
    assert "1 key(s) configured" in page
    assert "Bearer k" not in page and "Bearer $STOCKS_API_KEY" in page    # the real key is never rendered
    # The curl sample's single quotes are escaped text inside <code>, not markup.
    assert "-d &#39;{&#34;jsonrpc&#34;: &#34;2.0&#34;" in page


def test_code_samples_are_escaped(db):
    from stocks_service.web.routes import templates
    html = templates.env.from_string('{% import "components.html" as ui %}{{ ui.code_block("<b>x</b> & y") }}').render()
    assert "&lt;b&gt;x&lt;/b&gt; &amp; y" in html and "<b>" not in html
