"""Yahoo Finance chart API client and parser.

The parser is pure (payload in, structured bars/events out) so it can be tested
against recorded real responses. It never invents values: points with missing
OHLC, points outside the requested window, points that do not map to an XNYS
session, and bars not yet complete are dropped and reported with a reason.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Protocol

import requests

from . import sessions
from .price_basis import Split

SOURCE = "yahoo_chart"
SUPPORTED_INTERVALS = ("1d", "1h")
CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"


class YahooError(RuntimeError):
    pass


class ChartFetcher(Protocol):
    def fetch_chart(self, symbol: str, interval: str, period1: int, period2: int) -> dict[str, Any]: ...


class YahooChartClient:
    def __init__(self, user_agent: str, timeout: float = 30.0, session: requests.Session | None = None):
        self._session = session or requests.Session()
        self._session.headers["User-Agent"] = user_agent
        self._timeout = timeout

    def fetch_chart(self, symbol: str, interval: str, period1: int, period2: int) -> dict[str, Any]:
        if interval not in SUPPORTED_INTERVALS:
            raise ValueError(f"unsupported interval {interval!r}")
        resp = self._session.get(
            CHART_URL.format(symbol=symbol),
            params={
                "period1": period1,
                "period2": period2,
                "interval": interval,
                "events": "div,splits",
                "includeAdjustedClose": "true",
            },
            timeout=self._timeout,
        )
        if resp.status_code != 200:
            raise YahooError(f"{symbol} {interval}: HTTP {resp.status_code}: {resp.text[:200]}")
        payload = resp.json()
        err = (payload.get("chart") or {}).get("error")
        if err:
            raise YahooError(f"{symbol} {interval}: {err}")
        return payload


@dataclass(frozen=True)
class Dividend:
    ex_date: dt.date
    amount_source: float  # as reported by the source (on the source's price basis)


@dataclass
class ParsedChart:
    symbol: str
    interval: str
    bars: list[dict] = field(default_factory=list)  # source-basis bars
    splits: list[Split] = field(default_factory=list)
    dividends: list[Dividend] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)


def _utc(epoch: int) -> dt.datetime:
    return dt.datetime.fromtimestamp(epoch, tz=dt.timezone.utc)


def parse_events(result: dict) -> tuple[list[Split], list[Dividend]]:
    events = result.get("events") or {}
    splits = []
    for ev in (events.get("splits") or {}).values():
        num, den = float(ev["numerator"]), float(ev["denominator"])
        if den == 0:
            raise YahooError(f"split with zero denominator: {ev}")
        splits.append(Split(ex_date=sessions.exchange_date(_utc(int(ev["date"]))), ratio=num / den))
    dividends = [
        Dividend(ex_date=sessions.exchange_date(_utc(int(ev["date"]))), amount_source=float(ev["amount"]))
        for ev in (events.get("dividends") or {}).values()
    ]
    splits.sort(key=lambda s: s.ex_date)
    dividends.sort(key=lambda d: d.ex_date)
    return splits, dividends


def parse_chart(
    payload: dict,
    *,
    symbol: str,
    interval: str,
    window_start: dt.datetime,
    window_end: dt.datetime,
    complete_before: dt.datetime,
) -> ParsedChart:
    """Parse a chart payload into source-basis bars.

    Keeps bars with ``window_start <= ts < window_end`` whose end time is
    ``<= complete_before``. Bars carry: ts (bar start, UTC), ts_end, session (date),
    o, h, l, c, v.
    """
    if interval not in SUPPORTED_INTERVALS:
        raise ValueError(f"unsupported interval {interval!r}")
    results = (payload.get("chart") or {}).get("result") or []
    if not results:
        raise YahooError(f"{symbol} {interval}: empty chart result")
    result = results[0]
    out = ParsedChart(symbol=symbol, interval=interval)
    out.splits, out.dividends = parse_events(result)

    timestamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    for i, epoch in enumerate(timestamps):
        ts = _utc(int(epoch))
        vals = {k: (quote.get(name) or [None] * len(timestamps))[i] for k, name in
                (("o", "open"), ("h", "high"), ("l", "low"), ("c", "close"), ("v", "volume"))}

        def reject(reason: str) -> None:
            out.rejected.append({"ts": ts, "reason": reason})

        if not (window_start <= ts < window_end):
            reject("outside_requested_window")
            continue
        if any(vals[k] is None for k in ("o", "h", "l", "c")):
            reject("missing_ohlc")
            continue
        if interval == "1d":
            session = sessions.exchange_date(ts)
            if not sessions.is_session(session):
                reject("not_a_session")
                continue
            bar_start, bar_end = sessions.session_bounds(session)
        else:
            session = sessions.session_containing(ts)
            if session is None:
                reject("outside_session_hours")
                continue
            _, close = sessions.session_bounds(session)
            bar_start, bar_end = ts, min(ts + dt.timedelta(hours=1), close)
        if bar_end > complete_before:
            reject("incomplete")
            continue
        o, h, l, c = (float(vals[k]) for k in ("o", "h", "l", "c"))
        if not (l <= min(o, c) and h >= max(o, c) and l > 0):
            reject("inconsistent_ohlc")
            continue
        out.bars.append({
            "ts": bar_start,
            "ts_end": bar_end,
            "session": session,
            "o": o, "h": h, "l": l, "c": c,
            "v": float(vals["v"]) if vals["v"] is not None else None,
        })
    return out
