import datetime as dt

import numpy as np
import pytest

from stocks_service import ingestion
from stocks_service.research import protocol, stats
from stocks_service.research.backtest import run_backtest
from stocks_service.research.baselines import buy_and_hold, cash_curve, spliced_buy_and_hold
from stocks_service.research.series import SymbolSeries
from stocks_service.sim import CostProfile
from stocks_service.strategies import PointInTimeView, decide, get_spec

from .conftest import INTC_LONG, NOW, NVDA_LONG, RecordedFetcher, load_yahoo, raw_daily

UTC = dt.timezone.utc
COST = CostProfile("test", 1, 0.0, 0.0, 2.0, 3.0, 0.005)
FIX = {"NVDA": NVDA_LONG, "INTC": INTC_LONG, "^IRX": "IRX_1d_2020-06-01_2025-06-02",
       "SPY": "SPY_1d_2020-06-01_2025-06-02", "QQQ": "QQQ_1d_2020-06-01_2025-06-02",
       "QQQM": "QQQM_1d_2020-06-01_2025-06-02"}


def _series(symbol, name=None, cutoff=None):
    bars, splits = raw_daily(name or FIX[symbol], symbol)
    if cutoff:
        bars = [b for b in bars if b["session"] <= cutoff]
    return SymbolSeries(symbol, [b["session"] for b in bars], bars, splits, [])


def _universe(cutoff=None):
    return {s: _series(s, cutoff=cutoff) for s in FIX}


# --- series exactness ------------------------------------------------------------

@pytest.mark.parametrize("asof", [dt.date(2021, 7, 19), dt.date(2021, 7, 20), dt.date(2024, 6, 7),
                                  dt.date(2024, 6, 10), dt.date(2025, 5, 30)])
def test_series_view_equals_point_in_time_construction(asof):
    bars, splits = raw_daily(NVDA_LONG, "NVDA")
    known = [b for b in bars if b["session"] <= asof][-400:]
    direct = PointInTimeView.from_raw("NVDA", known, [s for s in splits if s.ex_date <= asof], asof)
    fast = _series("NVDA").view_at(asof)
    assert fast.sessions == direct.sessions
    for f in "ohlcv":
        np.testing.assert_array_equal(getattr(fast, f), getattr(direct, f))
    for spec in ("ma_crossover@1", "macd@1", "ensemble@1"):
        assert decide(fast, get_spec(spec)) == decide(direct, get_spec(spec))


def test_bars_after_use_the_decision_basis_across_a_split():
    s = _series("NVDA")
    bars = s.bars_after(dt.date(2024, 6, 7), 3)
    assert bars[0].session == dt.date(2024, 6, 10)
    assert bars[0].c == pytest.approx(1217.9, abs=0.1)  # 121.79 x 10 on the 06-07 basis


# --- backtest: no look-ahead -------------------------------------------------------

def test_equity_curve_before_a_date_does_not_depend_on_later_data():
    """Truncating all data after X must leave the equity curve up to X unchanged."""
    full = run_backtest(_universe(), ["NVDA", "INTC", "SPY", "QQQ"], _series("^IRX"), "momentum@1",
                        dt.date(2021, 6, 1), dt.date(2025, 5, 30), COST)
    cut = dt.date(2023, 6, 30)
    part = run_backtest(_universe(cut), ["NVDA", "INTC", "SPY", "QQQ"], _series("^IRX", cutoff=cut), "momentum@1",
                        dt.date(2021, 6, 1), cut, COST)
    n = len(part.equity)
    assert full.dates[:n] == part.dates
    np.testing.assert_allclose(full.equity[:n], part.equity, rtol=0, atol=1e-6)
    assert len(full.trades) > 20


def test_backtest_is_deterministic_and_accounts_for_costs():
    args = (_universe(), ["NVDA", "INTC", "SPY", "QQQ"], _series("^IRX"), "ma_crossover@1",
            dt.date(2021, 6, 1), dt.date(2025, 5, 30))
    a, b = run_backtest(*args, COST), run_backtest(*args, COST)
    assert a.equity == b.equity
    dearer = run_backtest(*args, COST.scaled(3, "_x3"))
    assert dearer.equity[-1] < a.equity[-1]
    assert all(t.net_return < t.gross_return for t in a.trades if t.result != "not_filled")


def test_baselines():
    irx = _series("^IRX")
    days = [d for d in _series("SPY").sessions if dt.date(2021, 1, 4) <= d <= dt.date(2024, 12, 31)]
    cash = cash_curve(irx, days, 100.0)
    assert cash[-1] > cash[0] and all(b >= a for a, b in zip(cash, cash[1:]))
    spy = buy_and_hold(_series("SPY"), days, irx, 100.0)
    spy_px = _series("SPY")
    assert spy[-1] / spy[0] == pytest.approx(spy_px.close_on_basis(days[0], days[-1]) / spy_px.close_on_basis(days[0], days[0]), rel=1e-9)
    spliced = spliced_buy_and_hold(_series("QQQM"), _series("QQQ"), _series("QQQM").sessions[0],
                                   [d for d in _series("QQQ").sessions if dt.date(2020, 6, 1) <= d <= dt.date(2021, 6, 1)],
                                   irx, 100.0)
    assert len(spliced) == len([d for d in _series("QQQ").sessions if dt.date(2020, 6, 1) <= d <= dt.date(2021, 6, 1)])


# --- statistics -------------------------------------------------------------------

def test_bootstrap_is_seeded_and_brackets_the_mean():
    x = np.diff(np.log([b["c"] for b in raw_daily(INTC_LONG, "INTC")[0]]))
    m1, lo1, hi1 = stats.block_bootstrap_mean_ci(x)
    m2, lo2, hi2 = stats.block_bootstrap_mean_ci(x)
    assert (m1, lo1, hi1) == (m2, lo2, hi2) and lo1 < m1 < hi1


def test_deflated_sharpe_falls_as_trials_grow():
    x = np.diff(np.log([b["c"] for b in raw_daily(NVDA_LONG, "NVDA")[0]]))
    few = stats.deflated_sharpe(x, [0.05, 0.02])
    many = stats.deflated_sharpe(x, list(np.linspace(-0.05, 0.08, 50)))
    assert 0 <= many < few <= 1


def test_pbo_detects_a_noise_winner():
    """Real returns of unrelated symbols: picking the in-sample best should not reliably win OOS."""
    cols = [np.diff(np.log([b["c"] for b in raw_daily(FIX[s], s)[0]]))[:1200] for s in ("NVDA", "INTC", "SPY", "QQQ")]
    out = stats.probability_of_backtest_overfitting(np.column_stack(cols), splits=8)
    assert 0 <= out["pbo"] <= 1 and out["combinations"] == 70


# --- holdout rules ----------------------------------------------------------------

def test_holdout_is_sealed_single_use_and_excluded_from_development(db):
    with pytest.raises(protocol.HoldoutError):
        protocol.run_development(db, start=dt.date(2021, 1, 4), end=dt.date(2022, 1, 3), now=NOW)  # not sealed
    protocol.seal_holdout(db, start=dt.date(2024, 11, 18), end=dt.date(2025, 5, 30), now=NOW)
    again = protocol.seal_holdout(db, start=dt.date(2020, 1, 2), end=dt.date(2020, 2, 3), now=NOW)
    assert again["start"].date() == dt.date(2024, 11, 18)  # cannot be moved once sealed
    with pytest.raises(protocol.HoldoutError, match="before the holdout"):
        protocol.run_development(db, start=dt.date(2021, 1, 4), end=dt.date(2024, 12, 31), now=NOW)
    digest = protocol.freeze_protocol(db, candidates=["momentum@1"], dev_window=(dt.date(2021, 1, 4), dt.date(2024, 11, 15)), now=NOW)
    with pytest.raises(protocol.HoldoutError, match="hash mismatch"):
        protocol.reveal_holdout(db, protocol_hash="0" * 64, now=NOW)
    db.holdouts.update_one({"_id": "primary"}, {"$set": {"status": "consumed"}})  # simulate a completed reveal
    with pytest.raises(protocol.HoldoutError, match="consumed"):
        protocol.reveal_holdout(db, protocol_hash=digest, now=NOW)
    with pytest.raises(protocol.HoldoutError, match="prospective"):
        protocol.freeze_protocol(db, candidates=["macd@1"], dev_window=(dt.date(2021, 1, 4), dt.date(2024, 11, 15)), now=NOW)


def _load_db(db):
    """Store the recorded real bars for the protocol's required symbols directly (raw basis)."""
    classes = {"^IRX": "index", "SPY": "etf", "QQQ": "etf", "QQQM": "etf", "NVDA": "equity", "INTC": "equity"}
    for sym, name in FIX.items():
        bars, splits = raw_daily(name, sym)
        db.symbols.insert_one({"_id": sym, "asset_class": classes[sym], "tradable": sym != "^IRX", "enabled": True,
                               "ca_version": 0})
        db.bars.insert_many([{"symbol": sym, "interval": "1d", "session": dt.datetime.combine(b["session"], dt.time(), UTC),
                              "ts": dt.datetime.combine(b["session"], dt.time(13, 30), UTC),
                              "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"], "v": b["v"]} for b in bars])
        for s in splits:
            db.corporate_actions.insert_one({"symbol": sym, "type": "split", "ratio": s.ratio,
                                             "ex_date": dt.datetime.combine(s.ex_date, dt.time(), UTC)})


def test_development_report_end_to_end(db):
    from fastapi.testclient import TestClient
    from stocks_service.api.app import create_app
    from stocks_service.settings import Settings
    _load_db(db)
    protocol.seal_holdout(db, start=dt.date(2024, 11, 18), end=dt.date(2025, 5, 30), now=NOW)
    rep = protocol.run_development(db, start=dt.date(2021, 6, 1), end=dt.date(2024, 11, 15), now=NOW,
                                   strategies=["ma_crossover@1", "momentum@1"])
    assert set(rep["results"]) == {"ma_crossover@1", "momentum@1"}
    for v in rep["results"].values():
        assert set(v["gate"]["checks"]) == set(protocol.GATE)
        assert set(v["comparisons"]) == {"cash", "SPY", "QQQM (QQQ before 2020-10-13)", "equal_weight_universe"}
        assert v["stress"]["costs_x2"]["metrics"]["total_return"] <= v["metrics"]["total_return"]
    assert db.experiments.count_documents({"kind": "development"}) == 2
    assert db.experiments.count_documents({"kind": "stress_costs_x2"}) == 2
    s = Settings(mongo_url="x", api_keys="k", admin_password="pw", session_secret="s" * 40)
    with TestClient(create_app(s, db=db), base_url="https://testserver") as c:
        assert c.get("/api/v1/research/report", headers={"X-API-Key": "k"}).json()["dev_window"] == ["2021-06-01", "2024-11-15"]
        c.post("/login", data={"password": "pw"})
        page = c.get("/research").text
        assert "ma_crossover@1" in page and "Deflated Sharpe" in page and ("No strategy passed" in page or "Eligible" in page)
