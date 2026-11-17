import copy
import datetime as dt

import pytest

from stocks_service.yahoo import YahooError, parse_chart

from .conftest import NOW, load_yahoo

UTC = dt.timezone.utc
START = dt.datetime(2025, 6, 3, tzinfo=UTC)
END = dt.datetime(2025, 6, 17, tzinfo=UTC)


def _reasons(parsed):
    return [r["reason"] for r in parsed.rejected]


def test_stray_point_outside_window_is_rejected():
    parsed = parse_chart(load_yahoo("ORLY_1h_2025-06-03_2025-06-17"), symbol="ORLY", interval="1h",
                         window_start=START, window_end=END, complete_before=NOW)
    assert _reasons(parsed) == ["outside_requested_window"]
    assert parsed.rejected[0]["ts"] == dt.datetime(2026, 11, 16, 21, 0, tzinfo=UTC)


def test_hourly_bars_end_at_session_close():
    parsed = parse_chart(load_yahoo("ORLY_1h_2025-06-03_2025-06-17"), symbol="ORLY", interval="1h",
                         window_start=START, window_end=END, complete_before=NOW)
    last_of_day = [b for b in parsed.bars if b["session"] == dt.date(2025, 6, 3)][-1]
    assert last_of_day["ts"] == dt.datetime(2025, 6, 3, 19, 30, tzinfo=UTC)
    assert last_of_day["ts_end"] == dt.datetime(2025, 6, 3, 20, 0, tzinfo=UTC)  # half bar to the EDT close
    assert all(b["ts_end"] - b["ts"] <= dt.timedelta(hours=1) for b in parsed.bars)


def test_incomplete_bars_are_rejected():
    cutoff = dt.datetime(2025, 6, 16, 18, 0, tzinfo=UTC)
    parsed = parse_chart(load_yahoo("ORLY_1h_2025-06-03_2025-06-17"), symbol="ORLY", interval="1h",
                         window_start=START, window_end=END, complete_before=cutoff)
    assert all(b["ts_end"] <= cutoff for b in parsed.bars)
    assert "incomplete" in _reasons(parsed)


def test_missing_ohlc_point_is_rejected_not_filled():
    payload = copy.deepcopy(load_yahoo("ORLY_1d_2025-06-03_2025-06-17"))
    payload["chart"]["result"][0]["indicators"]["quote"][0]["close"][2] = None
    parsed = parse_chart(payload, symbol="ORLY", interval="1d", window_start=START, window_end=END,
                         complete_before=NOW)
    assert "missing_ohlc" in _reasons(parsed)
    assert dt.date(2025, 6, 5) not in {b["session"] for b in parsed.bars}


def test_daily_bars_span_the_session():
    parsed = parse_chart(load_yahoo("ORLY_1d_2025-06-03_2025-06-17"), symbol="ORLY", interval="1d",
                         window_start=START, window_end=END, complete_before=NOW)
    b = parsed.bars[0]
    assert (b["session"], b["ts"], b["ts_end"]) == (
        dt.date(2025, 6, 3), dt.datetime(2025, 6, 3, 13, 30, tzinfo=UTC), dt.datetime(2025, 6, 3, 20, 0, tzinfo=UTC))


def test_empty_result_is_an_error():
    with pytest.raises(YahooError):
        parse_chart({"chart": {"result": []}}, symbol="X", interval="1d", window_start=START, window_end=END,
                    complete_before=NOW)
