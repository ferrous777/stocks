import datetime as dt

import pytest
from fastapi.testclient import TestClient

from stocks_service import sessions
from stocks_service.api.app import create_app
from stocks_service.outlook import build, calibration
from stocks_service.outlook.labels import BASE, STRIDE, build_labels, sample_sessions
from stocks_service.research import protocol
from stocks_service.research.backtest import _irx_rate
from stocks_service.settings import Settings
from stocks_service.sim import CostProfile

from .conftest import NOW
from .test_research import _load_db, _series, _universe

COST = CostProfile("market", 1, 0.0, 0.0, 2.0, 3.0, 0.005)
CUT = dt.date(2024, 11, 18)
SYMS = ["NVDA", "INTC", "SPY", "QQQ"]
KEYS = ["ma_crossover@1", "momentum@1"]


@pytest.fixture(scope="module")
def labels():
    labs, stats = build_labels(_universe(), SYMS, _series("^IRX"), KEYS, dt.date(2020, 6, 1), CUT, COST,
                               resolved_before=CUT)
    return labs, stats


def test_sampling_is_anchored_and_strided():
    a = sample_sessions(dt.date(2021, 1, 4), dt.date(2021, 12, 31))
    b = sample_sessions(dt.date(2021, 3, 1), dt.date(2021, 12, 31))
    assert set(b) <= set(a) and all(sessions.session_number(d) % STRIDE == 0 for d in a)
    assert 45 <= len(a) <= 55


def test_labels_resolve_before_the_cutoff_and_measure_excess_over_tbills(labels):
    labs, stats = labels
    assert stats["data_gaps"] == 0 and len(labs) > 500
    assert all(lab.decided < CUT and lab.resolved < CUT for lab in labs)
    assert {lab.strategy for lab in labs} == {BASE, *KEYS}
    irx = _series("^IRX")
    for lab in labs[:300]:
        if lab.result == "not_filled":
            assert lab.excess == 0.0 and lab.net_return == 0.0
        else:
            days = (lab.resolved - sessions.next_session(lab.decided)).days  # fill session -> exit session
            assert lab.excess == pytest.approx(lab.net_return - _irx_rate(irx, lab.decided) * days / 360)
    # Signal labels are copies of the base-rate plan for the same (symbol, date, side).
    base = {(lab.symbol, lab.decided, lab.side): lab for lab in labs if lab.strategy == BASE}
    for lab in labs:
        if lab.strategy != BASE:
            b = base[(lab.symbol, lab.decided, lab.side)]
            assert (b.result, b.excess) == (lab.result, lab.excess)


def test_labels_do_not_depend_on_data_after_the_cutoff(labels):
    labs, _ = labels
    cut = dt.date(2023, 6, 30)
    early, _ = build_labels(_universe(cut), SYMS, _series("^IRX", cutoff=cut), KEYS, dt.date(2020, 6, 1), cut, COST,
                            resolved_before=cut)
    key = lambda lab: (lab.strategy, lab.symbol, lab.side, lab.decided)  # noqa: E731
    full = {key(lab): lab for lab in labs if lab.resolved < cut}
    assert {key(lab) for lab in early} == set(full)
    for lab in early:
        assert lab == full[key(lab)]


def test_walk_forward_split_never_trains_on_unresolved_outcomes(labels):
    labs, _ = labels
    for T in (dt.date(2022, 1, 1), dt.date(2023, 1, 1), dt.date(2024, 1, 1)):
        train, test = calibration.walk_forward_split(labs, T, CUT)
        assert train and test
        assert all(lab.resolved < T for lab in train)
        assert all(T <= lab.decided < dt.date(T.year + 1, 1, 1) for lab in test)
        # Some labels were decided before T but resolved after it: they must be in neither set.
        straddling = [lab for lab in labs if lab.decided < T <= lab.resolved]
        assert straddling and not set(map(id, straddling)) & set(map(id, train + test))


def test_unpublished_buckets_withhold_expected_values(labels):
    buckets = calibration.calibrate(labels[0], CUT)
    assert {b["status"] for b in buckets} <= {"calibrated", "unreliable", "insufficient", "base_rate"}
    for b in buckets:
        published = b["status"] in ("calibrated", "base_rate")
        assert (b["mean_excess"] is not None) == published
        if b["status"] == "calibrated":
            assert b["n"] >= calibration.MIN_N and b["brier_skill"] >= calibration.MIN_SKILL
    assert any(b["strategy"] == BASE and b["status"] == "base_rate" for b in buckets)


def _client(db):
    s = Settings(mongo_url="x", api_keys="k", admin_password="pw", session_secret="s" * 40)
    return TestClient(create_app(s, db=db), base_url="https://testserver")


def test_outlook_end_to_end(db):
    from stocks_service.jobs import get_job
    _load_db(db)
    protocol.seal_holdout(db, start=CUT, end=dt.date(2025, 5, 30), now=NOW)
    H = {"X-API-Key": "k"}
    with _client(db) as c:
        assert c.get("/api/v1/outlook", headers=H).status_code == 404
        # No market cost profile: the job fails with an actionable message (no invented costs).
        job = build.start_outlook_job(db, steps=["calibrate", "outlook"], run_in_thread=False)
        assert "cost profile" in get_job(db, job)["error"]
        body = {"profile_id": "market", "version": 1, "commission_per_share": 0, "min_commission": 0,
                "half_spread_bps": 2, "slippage_bps": 3, "borrow_rate_annual": 0.005, "note": "test assumptions"}
        assert c.post("/api/v1/cost-profiles", json=body, headers=H).status_code == 201
        assert c.post("/api/v1/cost-profiles", json=body, headers=H).status_code == 409  # immutable
        job = build.start_outlook_job(db, steps=["calibrate", "outlook"], run_in_thread=False)
        assert get_job(db, job)["status"] == "completed", get_job(db, job).get("error")
        o = c.get("/api/v1/outlook", headers=H).json()
        tradable = sorted(s for s in ("NVDA", "INTC", "SPY", "QQQ", "QQQM"))
        assert sorted({r["symbol"] for r in o["rows"]}) == tradable and len(o["rows"]) == 2 * len(tradable)
        for r in o["rows"]:
            assert r["grade"] in ("A", "B", "C", "insufficient")
            assert not r["validated"]  # no strategy version is active
            if r["grade"] == "insufficient":
                assert r["reasons"] and r.get("exp_return_6m") is None
            else:
                assert r["exp_return_6m"] == pytest.approx(r["exp_excess_6m"] + o["cash_return_6m"])
                assert r["p10_return_6m"] <= r["exp_return_6m"] + 1e-12 or r["p10_return_6m"] <= r["p90_return_6m"]
                assert r["plan"]["stop"] != r["plan"]["entry_limit"]
        rets = [r["exp_return_6m"] for r in o["rows"] if r.get("exp_return_6m") is not None]
        assert rets == sorted(rets, reverse=True)
        shorts = c.get("/api/v1/outlook?side=short&sort=downside", headers=H).json()["rows"]
        assert shorts and all(r["side"] == "short" for r in shorts)
        assert c.get("/api/v1/outlook/calibration", headers=H).json()["cost_profile"] == "market@1"
        c.post("/login", data={"password": "pw"})
        page = c.get("/outlook").text
        assert "As of close" in page and "NVDA" in page


# --- review fixes (PR #19) ---------------------------------------------------------------

def test_missing_entry_session_is_counted_as_a_data_gap():
    from stocks_service.research.series import SymbolSeries
    full = _series("NVDA")
    d = sample_sessions(dt.date(2022, 3, 1), dt.date(2022, 3, 31))[0]
    drop = sessions.next_session(d)
    keep = [i for i, s in enumerate(full.sessions) if s != drop]
    gapped = SymbolSeries("NVDA", [full.sessions[i] for i in keep], [full.raw[i] for i in keep], full.splits,
                          full.dividends)
    _, stats = build_labels({"NVDA": gapped}, ["NVDA"], _series("^IRX"), [], d, d, COST, resolved_before=CUT)
    assert stats["data_gaps"] == 2 and stats["labels"] == 0  # both sides, recorded rather than silently dropped


def test_profile_without_borrow_rate_produces_no_short_labels():
    no_borrow = CostProfile("market", 2, 0.0, 0.0, 2.0, 3.0, None)
    labs, _ = build_labels(_universe(), ["NVDA"], _series("^IRX"), KEYS, dt.date(2021, 1, 4), dt.date(2021, 12, 31),
                           no_borrow, resolved_before=CUT)
    assert labs and {lab.side for lab in labs} == {"long"}


def test_outlook_rows_for_unloaded_symbols_no_shorts_and_step_validation(db):
    from stocks_service.jobs import get_job
    _load_db(db)
    protocol.seal_holdout(db, start=CUT, end=dt.date(2025, 5, 30), now=NOW)
    db.symbols.insert_one({"_id": "FCX", "asset_class": "equity", "tradable": True, "enabled": True, "ca_version": 0})
    H = {"X-API-Key": "k"}
    with _client(db) as c:
        assert c.post("/api/v1/outlook/run", json={"steps": []}, headers=H).status_code == 422
        body = {"profile_id": "market", "version": 1, "commission_per_share": 0, "min_commission": 0,
                "half_spread_bps": 2, "slippage_bps": 3, "borrow_rate_annual": None, "note": "no shorting"}
        assert c.post("/api/v1/cost-profiles", json=body, headers=H).status_code == 201
        job = build.start_outlook_job(db, steps=["calibrate", "outlook"], run_in_thread=False)
        assert get_job(db, job)["status"] == "completed", get_job(db, job).get("error")
        o = c.get("/api/v1/outlook", headers=H).json()
        assert o["shorts_enabled"] is False
        fcx = [r for r in o["rows"] if r["symbol"] == "FCX"]
        assert len(fcx) == 2 and all(r["grade"] == "insufficient" and "no price history" in r["reasons"][0] for r in fcx)
        shorts = [r for r in o["rows"] if r["side"] == "short"]
        assert shorts and all(r["grade"] == "insufficient" for r in shorts)
        assert any("borrow" in r["reasons"][0] for r in shorts)
        assert {k for r in o["rows"] for k in ("placeable_until", "valid_until", "plan", "estimate")} <= set(fcx[0])
        c.post("/login", data={"password": "pw"})
        assert c.get("/outlook?side=short").status_code == 200  # all-insufficient view renders
