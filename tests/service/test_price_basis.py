import datetime as dt

import pytest

from stocks_service import ingestion
from stocks_service.price_basis import (
    Basis, BasisInconclusive, Split, classify_across_split, to_raw, to_split_adjusted,
)
from stocks_service.yahoo import parse_chart

from .conftest import NOW, load_yahoo

UTC = dt.timezone.utc


def _parse(name, symbol, interval, start, end):
    return parse_chart(load_yahoo(name), symbol=symbol, interval=interval,
                       window_start=dt.datetime.fromisoformat(start).replace(tzinfo=UTC),
                       window_end=dt.datetime.fromisoformat(end).replace(tzinfo=UTC), complete_before=NOW)


def test_daily_basis_is_split_adjusted_prices_and_volumes():
    parsed = _parse("NVDA_1d_2024-05-01_2024-07-15", "NVDA", "1d", "2024-05-01", "2024-07-16")
    v = ingestion.verify_basis_from_chart(parsed, dt.date(2024, 6, 10))
    assert v.split == Split(dt.date(2024, 6, 10), 10.0)
    assert v.price_basis is Basis.SPLIT_ADJUSTED
    assert v.volume_basis is Basis.SPLIT_ADJUSTED


def test_hourly_basis_has_adjusted_prices_but_raw_volumes():
    parsed = _parse("ORLY_1h_2025-06-03_2025-06-17", "ORLY", "1h", "2025-06-03", "2025-06-17")
    v = ingestion.verify_basis_from_chart(parsed, dt.date(2025, 6, 10))
    assert v.split.ratio == 15.0
    assert v.price_basis is Basis.SPLIT_ADJUSTED
    assert v.volume_basis is Basis.RAW


def test_normalized_raw_prices_match_as_traded_values():
    parsed = _parse("NVDA_1d_2024-05-01_2024-07-15", "NVDA", "1d", "2024-05-01", "2024-07-16")
    raw = {b["session"]: to_raw(b, parsed.splits, price_basis=Basis.SPLIT_ADJUSTED,
                                volume_basis=Basis.SPLIT_ADJUSTED) for b in parsed.bars}
    pre, post = raw[dt.date(2024, 6, 7)], raw[dt.date(2024, 6, 10)]
    assert pre["c"] == pytest.approx(1208.88, abs=0.01)  # NVDA's as-traded close before the 10:1 split
    assert pre["split_factor_applied"] == 10.0 and post["split_factor_applied"] == 1.0
    assert post["c"] == pytest.approx(121.79, abs=0.01)
    assert pre["v"] == pytest.approx(41_238_600, rel=1e-6)  # 412,386,000 adjusted / 10


def test_point_in_time_adjusted_view_only_uses_known_splits():
    split = Split(dt.date(2024, 6, 10), 10.0)
    raw_bar = {"session": dt.date(2024, 6, 7), "o": 1197.7, "h": 1216.92, "l": 1180.22, "c": 1208.88, "v": 41238600.0}
    after = to_split_adjusted(raw_bar, [split], asof=dt.date(2024, 6, 10))
    before = to_split_adjusted(raw_bar, [split], asof=dt.date(2024, 6, 7))
    assert after["c"] == pytest.approx(120.888)
    assert before["c"] == raw_bar["c"]  # a later split cannot change an earlier point-in-time view


def test_classification_refuses_ambiguous_evidence():
    with pytest.raises(BasisInconclusive):
        classify_across_split([100.0], [100.0 / 10 ** 0.5], 10.0, kind="price")  # halfway between hypotheses
    with pytest.raises(ValueError):
        classify_across_split([100.0], [50.0], 1.0, kind="price")
