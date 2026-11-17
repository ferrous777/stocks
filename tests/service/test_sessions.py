import datetime as dt

import pytest

from stocks_service import sessions

UTC = dt.timezone.utc


def test_early_close_day_after_thanksgiving_2026():
    open_, close = sessions.session_bounds(dt.date(2026, 11, 27))
    assert open_ == dt.datetime(2026, 11, 27, 14, 30, tzinfo=UTC)
    assert close == dt.datetime(2026, 11, 27, 18, 0, tzinfo=UTC)  # 1:00 p.m. ET
    # The legacy calendar reported the market open at 2 p.m. ET (19:00Z) on this day.
    assert sessions.session_containing(dt.datetime(2026, 11, 27, 19, 0, tzinfo=UTC)) is None
    assert sessions.session_containing(dt.datetime(2026, 11, 27, 17, 30, tzinfo=UTC)) == dt.date(2026, 11, 27)


def test_closes_follow_dst():
    assert sessions.session_bounds(dt.date(2026, 1, 15))[1] == dt.datetime(2026, 1, 15, 21, 0, tzinfo=UTC)  # EST
    assert sessions.session_bounds(dt.date(2026, 7, 2))[1] == dt.datetime(2026, 7, 2, 20, 0, tzinfo=UTC)  # EDT


def test_holiday_is_not_a_session():
    assert not sessions.is_session(dt.date(2026, 11, 26))
    with pytest.raises(sessions.SessionError):
        sessions.session_bounds(dt.date(2026, 11, 26))


def test_session_boundary_is_half_open():
    _, close = sessions.session_bounds(dt.date(2026, 1, 15))
    assert sessions.session_containing(close) is None
    assert sessions.session_containing(close - dt.timedelta(seconds=1)) == dt.date(2026, 1, 15)


def test_nth_session_after_counts_sessions_not_days():
    start = dt.date(2026, 1, 2)
    end = sessions.nth_session_after(start, 126)
    assert len(sessions.sessions_between(start, end)) == 127  # start + 126 following sessions
    assert sessions.next_session(dt.date(2026, 11, 25)) == dt.date(2026, 11, 27)  # skips Thanksgiving


def test_out_of_calendar_range_is_explicit():
    with pytest.raises(sessions.SessionError):
        sessions.is_session(dt.date(1970, 1, 2))
