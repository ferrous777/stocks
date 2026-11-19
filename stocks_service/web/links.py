"""Canonical website paths, shared by the templates' callers and the MCP tools that hand links to an
LLM (so a link an agent surfaces always points at a page and view that exists).

Every builder returns a path; ``absolute(base, path)`` joins it to the site's public URL.
"""

from __future__ import annotations

from urllib.parse import quote, urlencode

CHART_RANGES = ("6M", "YTD", "1Y", "3Y", "5Y", "All")
MAX_COMPARE_YEARS = 8   # the chart offers the most recent eight calendar years


def absolute(base: str, path: str) -> str:
    return base.rstrip("/") + path


def _with(path: str, params: dict) -> str:
    q = {k: v for k, v in params.items() if v is not None}
    return path + ("?" + urlencode(q, safe=",") if q else "")


def dashboard() -> str:
    return "/"


def symbol(sym: str, *, range: str | None = None, from_year: int | None = None,
           compare: list[int] | None = None) -> str:
    """The symbol page; at most one chart view: a preset range, ``from_year`` to present, or ``compare``
    calendar years overlaid (each as % change from the previous year's last close)."""
    if sum(x is not None for x in (range, from_year, compare)) > 1:
        raise ValueError("choose one chart view: range, from_year or compare")
    if range is not None and range not in CHART_RANGES:
        raise ValueError(f"range must be one of {', '.join(CHART_RANGES)}")
    if compare is not None and not 1 <= len(compare) <= MAX_COMPARE_YEARS:
        raise ValueError(f"compare takes 1 to {MAX_COMPARE_YEARS} years")
    return _with(f"/symbol/{quote(sym, safe='')}", {
        "range": range, "from": from_year,
        "compare": ",".join(str(y) for y in sorted(set(compare))) if compare else None})


def outlook(side: str | None = None) -> str:
    if side not in (None, "long", "short"):
        raise ValueError("side must be long or short")
    return _with("/outlook", {"side": side})


def accounts() -> str:
    return "/accounts"


def account(account_id: str, kind: str) -> str:
    """A real account's page (holdings, snapshots, reconciliation) or a paper account's page."""
    return (f"/paper/{quote(account_id, safe='')}" if kind == "paper"
            else f"/accounts/{quote(account_id, safe='')}")


def paper() -> str:
    return "/paper"


def research() -> str:
    return "/research"


def connect() -> str:
    return "/connect"


def api_docs() -> str:
    return "/docs"


# What each page shows; the MCP ``get_links`` tool lists these with absolute URLs.
CATALOG = [
    {"page": "dashboard", "path": "/", "shows": "every watched symbol: last close, daily change, today's strategy decisions"},
    {"page": "symbol", "path": "/symbol/{symbol}",
     "shows": "interactive price chart (views: ?range=6M|YTD|1Y|3Y|5Y|All, ?from=<year> to present, "
              "?compare=<year>,<year>,... calendar years overlaid), calendar-year returns, strategy decisions, "
              "ATR levels with Monte Carlo odds, corporate actions"},
    {"page": "outlook", "path": "/outlook", "shows": "six-month outlook for every symbol and side (?side=long|short)"},
    {"page": "accounts", "path": "/accounts", "shows": "real brokerage accounts"},
    {"page": "account", "path": "/accounts/{account_id}",
     "shows": "a real account: holdings, snapshots, reconciliation breaks, order tickets, alerts"},
    {"page": "paper", "path": "/paper", "shows": "paper-account leaderboard and agent-vs-baseline comparisons"},
    {"page": "paper_account", "path": "/paper/{account_id}",
     "shows": "a paper account: equity chart, positions, orders, transactions, comparison with its baseline"},
    {"page": "research", "path": "/research", "shows": "strategy validation report, lifecycle, overlays and umpires"},
    {"page": "connect", "path": "/connect", "shows": "how to connect an AI agent to the MCP server"},
    {"page": "api_docs", "path": "/docs", "shows": "REST API reference (OpenAPI)"},
]
