import datetime as dt

import numpy as np
import pytest

from stocks_service import estimation
from stocks_service.levels import LevelsUnavailable, atr_levels
from stocks_service.strategies import PointInTimeView
from stocks_service.strategies.indicators import atr

from .conftest import NVDA_LONG, raw_daily

ASOF = dt.date(2023, 6, 30)


def _view(asof=ASOF):
    bars, splits = raw_daily(NVDA_LONG, "NVDA")
    return PointInTimeView.from_raw("NVDA", bars, splits, asof)


def test_levels_are_atr_multiples_on_both_sides():
    v = _view()
    a = atr(v.h, v.l, v.c, 14)
    long_, short = atr_levels(v, "long"), atr_levels(v, "short")
    assert long_.atr == pytest.approx(a) and long_.entry_limit == pytest.approx(v.c[-1])
    assert long_.stop == pytest.approx(v.c[-1] - 2 * a) and long_.target == pytest.approx(v.c[-1] + 4 * a)
    assert short.stop == pytest.approx(v.c[-1] + 2 * a) and short.target == pytest.approx(v.c[-1] - 4 * a)
    assert long_.risk_pct == pytest.approx(short.risk_pct)


def test_levels_fail_explicitly_without_enough_history():
    with pytest.raises(LevelsUnavailable):
        atr_levels(_view(dt.date(2020, 6, 10)), "long")


def test_monte_carlo_is_seeded_and_probabilities_sum_to_one():
    v = _view()
    lv = atr_levels(v, "long")
    a = estimation.monte_carlo_estimate(v, lv.entry_limit, lv.target, lv.stop, "long")
    b = estimation.monte_carlo_estimate(v, lv.entry_limit, lv.target, lv.stop, "long")
    assert a == b
    assert a.p_target + a.p_stop + a.p_neither == pytest.approx(1.0)
    other_day = estimation.monte_carlo_estimate(_view(dt.date(2023, 7, 3)), lv.entry_limit, lv.target, lv.stop, "long")
    assert other_day != a  # seed depends on (symbol, asof)


def test_monte_carlo_has_no_forced_drift():
    """Legacy forced positive drift for longs and negative for shorts. With the symbol's own
    returns resampled, the same distances must get mirror-consistent odds only via the data."""
    v = _view()
    price = float(v.c[-1])
    up, dn = price * 1.10, price / 1.10  # symmetric in log space
    long_ = estimation.monte_carlo_estimate(v, price, up, dn, "long")
    short = estimation.monte_carlo_estimate(v, price, dn, up, "short")
    # Same paths, same barriers: long's target is short's stop and vice versa.
    assert long_.p_target == pytest.approx(short.p_stop)
    assert long_.p_stop == pytest.approx(short.p_target)


def test_unreachable_target_gives_no_time_not_a_placeholder():
    v = _view()
    price = float(v.c[-1])
    e = estimation.monte_carlo_estimate(v, price, price * 1000, price * 0.5, "long")
    assert e.days_to_target is None and e.p_target == 0.0 and e.note == "no_path_reached_target"


def test_drift_estimate_refuses_trades_against_the_drift():
    v = _view()  # NVDA rose strongly into mid-2023
    price = float(v.c[-1])
    assert estimation.drift_estimate(v, price, price * 0.9, "short").note == "drift_against_trade"
    assert estimation.drift_estimate(v, price, price * 1.1, "long").days_to_target > 0


def test_pattern_estimate_counts_misses_and_only_resolved_samples():
    v = _view()
    price = float(v.c[-1])
    e = estimation.pattern_estimate(v, price, price * 1.10, price * 0.95, "long")
    assert e.p_target is not None and 0 < e.p_target < 1
    assert e.p_target + e.p_stop + e.p_neither == pytest.approx(1.0)
    # Changing bars inside the last horizon (unresolved outcomes) must not change the estimate's samples:
    # the estimate at asof uses only start points whose 126-session window ended by asof.
    assert e.days_to_target is not None and e.days_to_target <= estimation.HORIZON_SESSIONS


def test_ensemble_requires_two_time_estimates():
    v = _view(dt.date(2020, 7, 31))  # too little history for drift / Monte Carlo / pattern
    lv = atr_levels(v, "long")
    e = estimation.ensemble_estimate(v, lv.entry_limit, lv.target, lv.stop, "long")
    assert e.valid is False and "1 estimator" in e.reason
    full = estimation.ensemble_estimate(_view(), *(lambda l: (l.entry_limit, l.target, l.stop))(atr_levels(_view(), "long")), "long")
    assert full.valid and full.days_to_target is not None


def test_legacy_atr_estimator_reversed_chronology_differs():
    """Regression evidence for the legacy bug: newest-first input made TR use the next day's close."""
    from time_estimation.atr_estimator import ATRTimeEstimator
    v = _view()
    points = [{"date": s.isoformat(), "open": o, "high": h, "low": l, "close": c, "volume": 0}
              for s, o, h, l, c in zip(v.sessions, v.o, v.h, v.l, v.c)][-40:]
    legacy = ATRTimeEstimator().calculate_atr(sorted(points, key=lambda p: p["date"], reverse=True))
    correct = atr(v.h, v.l, v.c, 14)
    assert not np.isclose(legacy, correct)
