"""NYSE trading-session calendar (holidays, early closes, DST) via ``exchange_calendars``.

Replaces the legacy ``market_calendar`` package, whose ``is_market_open`` ignored
early closes. All datetimes returned here are timezone-aware UTC.
"""

from __future__ import annotations

import datetime as dt
from functools import lru_cache
from zoneinfo import ZoneInfo

import exchange_calendars as xc
import pandas as pd

EXCHANGE_TZ = ZoneInfo("America/New_York")
CAL_START = dt.date(1980, 1, 2)
_CAL_START = CAL_START.isoformat()


class SessionError(ValueError):
    """Raised for dates/timestamps that do not map to a valid trading session."""


@lru_cache(maxsize=1)
def calendar() -> xc.ExchangeCalendar:
    end = (dt.date.today() + dt.timedelta(days=366)).isoformat()
    return xc.get_calendar("XNYS", start=_CAL_START, end=end)


def _ts(d: dt.date) -> pd.Timestamp:
    return pd.Timestamp(d.isoformat())


def _to_utc(ts: pd.Timestamp) -> dt.datetime:
    return ts.tz_convert("UTC").to_pydatetime() if ts.tzinfo else ts.tz_localize("UTC").to_pydatetime()


def is_session(d: dt.date) -> bool:
    cal = calendar()
    if not (cal.first_session.date() <= d <= cal.last_session.date()):
        raise SessionError(f"{d.isoformat()} is outside the calendar range "
                           f"{cal.first_session.date()}..{cal.last_session.date()}")
    return bool(cal.is_session(_ts(d)))


def session_bounds(d: dt.date) -> tuple[dt.datetime, dt.datetime]:
    """(open, close) in UTC for session ``d``; raises SessionError if ``d`` is not a session."""
    cal = calendar()
    t = _ts(d)
    if not cal.is_session(t):
        raise SessionError(f"{d.isoformat()} is not an XNYS trading session")
    return _to_utc(cal.session_open(t)), _to_utc(cal.session_close(t))


def exchange_date(ts: dt.datetime) -> dt.date:
    """Calendar date of ``ts`` in the exchange's time zone."""
    if ts.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return ts.astimezone(EXCHANGE_TZ).date()


def session_containing(ts: dt.datetime) -> dt.date | None:
    """The session whose [open, close) window contains ``ts``, or None."""
    d = exchange_date(ts)
    if not is_session(d):
        return None
    open_, close = session_bounds(d)
    return d if open_ <= ts < close else None


def next_session(d: dt.date) -> dt.date:
    """First session strictly after date ``d``."""
    if is_session(d):
        return calendar().next_session(_ts(d)).date()
    return calendar().date_to_session(_ts(d), "next").date()


def nth_session_after(d: dt.date, n: int) -> dt.date:
    """The n-th session strictly after session ``d`` (n >= 1)."""
    if n < 1:
        raise ValueError("n must be >= 1")
    if not is_session(d):
        raise SessionError(f"{d.isoformat()} is not an XNYS trading session")
    window = calendar().sessions_window(_ts(d), n + 1)
    return window[-1].date()


def sessions_between(start: dt.date, end: dt.date) -> list[dt.date]:
    """Sessions in [start, end] inclusive."""
    if end < start:
        return []
    return [s.date() for s in calendar().sessions_in_range(_ts(start), _ts(end))]


@lru_cache(maxsize=1)
def _session_index() -> tuple[tuple[dt.date, ...], dict[dt.date, int]]:
    days = tuple(s.date() for s in calendar().sessions)
    return days, {d: i for i, d in enumerate(days)}


def session_after_n(d: dt.date, n: int) -> dt.date | None:
    """Fast lookup of the n-th session after session ``d`` (n >= 0); None past the calendar end."""
    days, idx = _session_index()
    if d not in idx:
        raise SessionError(f"{d.isoformat()} is not an XNYS trading session")
    j = idx[d] + n
    return days[j] if j < len(days) else None
