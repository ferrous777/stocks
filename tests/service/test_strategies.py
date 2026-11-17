import dataclasses
import datetime as dt

import numpy as np
import pytest

from stocks_service import ingestion
from stocks_service.strategies import (
    CutoffViolation, PointInTimeView, Signal, all_specs, check_parity, decide, get_spec, persist_decision,
    run_decision, sync_strategy_versions,
)
from stocks_service.strategies.indicators import atr, ema_series, true_range

from .conftest import INTC_LONG, NOW, NVDA_LONG, RecordedFetcher, load_yahoo, raw_daily

UTC = dt.timezone.utc
SPLIT_2021, SPLIT_2024 = dt.date(2021, 7, 20), dt.date(2024, 6, 10)


def _view(name, symbol, asof=None):
    bars, splits = raw_daily(name, symbol)
    return PointInTimeView.from_raw(symbol, bars, splits, asof or bars[-1]["session"])


def _sample_asofs(view, start, step):
    return [view.sessions[i] for i in range(start, len(view), step)]


# --- the view ------------------------------------------------------------------

def test_view_rejects_access_after_cutoff():
    v = _view(NVDA_LONG, "NVDA", dt.date(2023, 1, 3))
    assert v.last_session == dt.date(2023, 1, 3)
    with pytest.raises(CutoffViolation):
        v.index_of(dt.date(2023, 1, 4))
    with pytest.raises(CutoffViolation):
        v.truncated(dt.date(2023, 2, 1))
    with pytest.raises(ValueError):
        v.c[-1] = 0.0  # arrays are read-only


def test_view_uses_only_splits_known_at_asof():
    before = _view(NVDA_LONG, "NVDA", dt.date(2024, 6, 7))
    after = _view(NVDA_LONG, "NVDA", dt.date(2024, 6, 10))
    assert before.c[-1] == pytest.approx(1208.88, abs=0.01)  # the later 10:1 split is not yet known
    assert after.c[-2] == pytest.approx(120.888, abs=0.001)  # once known, history is adjusted
    assert after.c[-1] == pytest.approx(121.79, abs=0.01)


# --- the contract -----------------------------------------------------------

@pytest.mark.parametrize("spec", all_specs(), ids=lambda s: s.key)
def test_future_bars_and_later_splits_cannot_change_a_decision(spec):
    """Decision at t from all data (incl. later bars and splits) == decision from data known at t."""
    bars, splits = raw_daily(NVDA_LONG, "NVDA")
    full = _view(NVDA_LONG, "NVDA")
    asofs = _sample_asofs(full, spec.min_bars, 23) + [dt.date(2021, 7, 19), dt.date(2024, 6, 7)]
    for asof in asofs:
        everything = decide(PointInTimeView.from_raw("NVDA", bars, splits, asof), spec)
        known_then = decide(PointInTimeView.from_raw(
            "NVDA", [b for b in bars if b["session"] <= asof], [s for s in splits if s.ex_date <= asof], asof), spec)
        assert everything == known_then, f"{spec.key} at {asof}"


@pytest.mark.parametrize("spec", all_specs(), ids=lambda s: s.key)
def test_decisions_are_deterministic_and_canonical(spec):
    full = _view(NVDA_LONG, "NVDA")
    for asof in _sample_asofs(full, spec.min_bars, 97):
        v = full.truncated(asof)
        a, b = decide(v, spec), decide(v, spec)
        assert a == b
        assert a.direction in ("long", "short", "exit", "hold") and 0.0 <= a.strength <= 1.0


def test_insufficient_history_is_an_explicit_hold():
    d = decide(_view(NVDA_LONG, "NVDA", dt.date(2020, 7, 1)), get_spec("ma_crossover@1"))
    assert (d.direction, d.reasons) == ("hold", ("insufficient_bars",))


def test_signal_validation():
    with pytest.raises(ValueError):
        Signal("buy")  # legacy vocabulary is rejected
    with pytest.raises(ValueError):
        Signal("long", 1.5)
    with pytest.raises(ValueError):
        Signal("long", 0.5, features={"x": float("nan")})


# --- strategy-specific regressions ------------------------------------------

def test_ma_regime_matches_independent_sma():
    full = _view(NVDA_LONG, "NVDA")
    spec = get_spec("ma_crossover@1")
    for asof in _sample_asofs(full, 201, 31):
        v = full.truncated(asof)
        d = decide(v, spec)
        spread = np.mean(v.c[-50:]) / np.mean(v.c[-200:]) - 1
        if d.direction in ("long", "short"):
            assert (d.direction == "long") == (spread > 0)


def test_trend_breakout_is_symmetric_for_longs_and_shorts():
    """Mirroring real prices (p -> K - p) swaps up/down moves and highs/lows but keeps true range,
    so every long must become a short and vice versa. The legacy rule could never short."""
    bars, _ = raw_daily(INTC_LONG, "INTC")
    k = 2 * max(b["h"] for b in bars)
    mirrored = [{**b, "o": k - b["o"], "h": k - b["l"], "l": k - b["h"], "c": k - b["c"]} for b in bars]
    a = PointInTimeView.from_raw("INTC", bars, [], bars[-1]["session"])
    m = PointInTimeView.from_raw("INTC", mirrored, [], bars[-1]["session"])
    spec = get_spec("trend_breakout@1")
    flip = {"long": "short", "short": "long", "exit": "exit", "hold": "hold"}
    shorts = 0
    for i in range(spec.min_bars, len(a)):
        da, dm = decide(a.truncated(a.sessions[i]), spec), decide(m.truncated(m.sessions[i]), spec)
        assert flip[da.direction] == dm.direction
        shorts += dm.direction == "short"
    assert shorts > 0


def test_trend_levels_exclude_the_current_bar():
    v = _view(NVDA_LONG, "NVDA", dt.date(2023, 5, 25))  # NVDA gapped up ~24% on 2023-05-25
    d = decide(v, get_spec("trend_breakout@1"))
    assert d.features["resistance"] == pytest.approx(float(np.max(v.h[-16:-1])))
    assert d.features["resistance"] < float(v.h[-1])


def test_ensemble_counts_only_canonical_votes():
    full = _view(NVDA_LONG, "NVDA")
    spec = get_spec("ensemble@1")
    for asof in _sample_asofs(full, spec.min_bars, 50):
        d = decide(full.truncated(asof), spec)
        assert set(k for k in d.features) == {"vote_long", "vote_short", "vote_exit"}


# --- indicators ----------------------------------------------------------------

def test_true_range_uses_previous_close_in_chronological_order():
    v = _view(NVDA_LONG, "NVDA", dt.date(2023, 1, 10))
    tr = true_range(v.h, v.l, v.c)
    i = len(v) - 1
    expected = max(v.h[i] - v.l[i], abs(v.h[i] - v.c[i - 1]), abs(v.l[i] - v.c[i - 1]))
    assert tr[-1] == pytest.approx(expected)
    assert atr(v.h, v.l, v.c, 14) == pytest.approx(np.mean(tr[-14:]))


def test_ema_is_seeded_with_sma():
    x = _view(NVDA_LONG, "NVDA", dt.date(2023, 1, 10)).c[-40:]
    e = ema_series(x, 12)
    assert e[0] == pytest.approx(np.mean(x[:12]))
    assert e[1] == pytest.approx(e[0] + 2 / 13 * (x[12] - e[0]))


# --- runner: Mongo-backed single entry point and parity -----------------------

def _load_nvda(db):
    db.symbols.insert_one({"_id": "NVDA", "asset_class": "equity", "enabled": True, "ca_version": 0})
    f = RecordedFetcher({("NVDA", "1d"): load_yahoo(NVDA_LONG)})
    ingestion.verify_basis(db, f, interval="1d", symbol="NVDA", split_ex_date=SPLIT_2024, now=NOW)
    ingestion.ingest(db, f, symbol="NVDA", interval="1d", start=dt.datetime(2020, 6, 1, tzinfo=UTC), now=NOW,
                     buffer=dt.timedelta(minutes=20), overlap_tolerance=0.005, gap_threshold=0.47)


def test_run_decision_matches_pure_decision_on_known_data(db):
    _load_nvda(db)
    bars, splits = raw_daily(NVDA_LONG, "NVDA")
    for asof in (dt.date(2021, 7, 19), dt.date(2024, 6, 7), dt.date(2025, 5, 30)):
        known = PointInTimeView.from_raw("NVDA", [b for b in bars if b["session"] <= asof][-400:],
                                         [s for s in splits if s.ex_date <= asof], asof)
        for key in ("ma_crossover@1", "macd@1", "ensemble@1"):
            assert run_decision(db, "NVDA", asof, key) == decide(known, get_spec(key))


def test_parity_check_passes_then_pauses_on_mismatch(db):
    _load_nvda(db)
    sync_strategy_versions(db, NOW)
    assert db.strategy_versions.find_one({"_id": "macd@1"})["status"] == "research"
    asof = dt.date(2025, 5, 30)
    persist_decision(db, run_decision(db, "NVDA", asof, "macd@1"), source="live", now=NOW)
    assert check_parity(db, "macd@1", "NVDA", asof, now=NOW) is True
    db.signals.update_one({"strategy": "macd@1", "symbol": "NVDA"}, {"$set": {"strength": 0.123456}})
    assert check_parity(db, "macd@1", "NVDA", asof, now=NOW) is False
    v = db.parity_violations.find_one({"strategy": "macd@1"})
    assert v["diffs"]["strength"]["live"] == 0.123456
    sv = db.strategy_versions.find_one({"_id": "macd@1"})
    assert (sv["status"], sv["paused_reason"]) == ("paused", "parity_violation")


def test_sync_never_promotes_or_resets_status(db):
    sync_strategy_versions(db, NOW)
    db.strategy_versions.update_one({"_id": "momentum@1"}, {"$set": {"status": "paused"}})
    assert sync_strategy_versions(db, NOW) == []
    assert db.strategy_versions.find_one({"_id": "momentum@1"})["status"] == "paused"


# --- review fixes (PR #13) ----------------------------------------------------

@pytest.mark.parametrize("asof", [dt.date(2021, 7, 19), dt.date(2021, 7, 20), dt.date(2023, 1, 3),
                                  dt.date(2024, 6, 7), dt.date(2024, 6, 10)])
def test_truncated_view_equals_direct_construction_across_splits(asof):
    bars, splits = raw_daily(NVDA_LONG, "NVDA")
    via_truncate = _view(NVDA_LONG, "NVDA").truncated(asof)
    direct = PointInTimeView.from_raw("NVDA", [b for b in bars if b["session"] <= asof],
                                      [s for s in splits if s.ex_date <= asof], asof)
    assert via_truncate.sessions == direct.sessions
    for f in ("o", "h", "l", "c", "v"):
        np.testing.assert_array_equal(getattr(via_truncate, f), getattr(direct, f))
    if asof == dt.date(2024, 6, 7):
        assert via_truncate.c[-1] == pytest.approx(1208.88, abs=0.01)  # not 120.888


def test_missing_volume_is_not_zero_and_blocks_volume_rules():
    bars, splits = raw_daily(NVDA_LONG, "NVDA")
    asof = dt.date(2023, 5, 25)
    holed = [{**b, "v": None} if b["session"] == dt.date(2023, 5, 23) else b for b in bars]
    v = PointInTimeView.from_raw("NVDA", holed, splits, asof)
    assert np.isnan(v.v[v.index_of(dt.date(2023, 5, 23))])
    for key in ("volume_price@1", "trend_breakout@1"):
        d = decide(v, get_spec(key))
        assert (d.direction, d.reasons) == ("hold", ("volume_unavailable",)), key
    # Price-only strategies are unaffected by the missing volume.
    assert decide(v, get_spec("ma_crossover@1")) == decide(_view(NVDA_LONG, "NVDA", asof), get_spec("ma_crossover@1"))


def test_live_decision_is_immutable_and_parity_uses_it(db):
    _load_nvda(db)
    sync_strategy_versions(db, NOW)
    asof = dt.date(2025, 5, 30)
    live = run_decision(db, "NVDA", asof, "macd@1")
    assert persist_decision(db, live, source="live", now=NOW) is True
    altered = dataclasses.replace(live, strength=0.987654)
    assert persist_decision(db, altered, source="live", now=NOW) is False  # first live snapshot kept
    assert persist_decision(db, altered, source="replay", now=NOW) is True  # replays stored separately
    docs = {d["source"]: d["strength"] for d in db.signals.find({"strategy": "macd@1", "symbol": "NVDA"})}
    assert docs == {"live": live.strength, "replay": 0.987654}
    assert check_parity(db, "macd@1", "NVDA", asof, now=NOW) is True  # compared with live, not the replay
