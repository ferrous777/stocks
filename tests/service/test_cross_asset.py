import dataclasses
import datetime as dt

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from stocks_service import cross_asset
from stocks_service.api.app import create_app
from stocks_service.research import protocol
from stocks_service.research.backtest import run_backtest
from stocks_service.research.overlays import evaluate_overlay
from stocks_service.research.series import SymbolSeries
from stocks_service.settings import Settings
from stocks_service.strategies import decide, get_spec

from .conftest import NOW
from .test_research import COST, _load_db, _series, _universe

ASOF = dt.date(2024, 11, 15)


def test_pair_statistics_match_reference_formulas():
    uni = _universe()
    rets = cross_asset.aligned_returns(uni, ["SPY", "QQQ", "NVDA"], ASOF, 252)
    a, b = rets["SPY"], rets["QQQ"]
    st = cross_asset.pair_stats(a, b, 252)
    x, y = pd.Series(a[-252:]), pd.Series(b[-252:])
    assert st["pearson"] == pytest.approx(x.corr(y)) and st["spearman"] == pytest.approx(x.corr(y, method="spearman"))
    assert st["sign"] == pytest.approx(float(np.mean(np.sign(x) * np.sign(y))))
    assert st["beta"] == pytest.approx(x.cov(y) / y.var())


def test_lead_lag_is_detected_on_shifted_real_returns():
    r = cross_asset.aligned_returns(_universe(), ["NVDA"], ASOF, 252)["NVDA"]
    a, b = r[2:], r[:-2]          # a_k = r_{k+2} = b_{k+2}: b *lags* a by 2 sessions
    st = cross_asset.pair_stats(a, b, 240)
    assert st["best_lag"] == -2 and st["best_lag_corr"] == pytest.approx(1.0)


def test_alignment_requires_every_session():
    uni = _universe()
    spy = uni["SPY"]
    hole = dt.date(2024, 8, 5)
    keep = [i for i, d in enumerate(spy.sessions) if d != hole]
    holed = SymbolSeries("SPY", [spy.sessions[i] for i in keep], [spy.raw[i] for i in keep], spy.splits, spy.dividends)
    rets = cross_asset.aligned_returns({**uni, "SPY": holed}, ["SPY", "QQQ"], ASOF, 252)
    assert set(rets) == {"QQQ"}


def test_group_consensus_overlay_combines_own_and_peer_strength():
    uni = _universe()
    spec = get_spec("ensemble@1")
    decs = {s: decide(uni[s].view_at(ASOF), spec) for s in ("NVDA", "INTC", "SPY")}
    ov = cross_asset.GroupConsensus({"NVDA": ["semis"], "INTC": ["semis"], "SPY": []}, weight=0.5)
    signed = {s: cross_asset.GroupConsensus._signed(d) for s, d in decs.items()}
    score = signed["NVDA"] + 0.5 * signed["INTC"]
    direction, strength = ov.adjust("NVDA", decs)
    expected = "long" if score > 0.05 else "short" if score < -0.05 else "neutral"
    assert direction == expected and (strength == pytest.approx(min(1, abs(score))) or direction == "neutral")
    assert ov.adjust("SPY", decs)[0] in ("long", "short", "neutral")   # no peers: own signal only


def test_overlay_backtest_has_no_look_ahead():
    ov = cross_asset.GroupConsensus({"NVDA": ["semis"], "INTC": ["semis"]}, weight=0.5)
    tr = ["NVDA", "INTC", "SPY", "QQQ"]
    full = run_backtest(_universe(), tr, _series("^IRX"), "ensemble@1", dt.date(2021, 6, 1), dt.date(2025, 5, 30),
                        COST, overlay=ov)
    cut = dt.date(2023, 6, 30)
    part = run_backtest(_universe(cut), tr, _series("^IRX", cutoff=cut), "ensemble@1", dt.date(2021, 6, 1), cut,
                        COST, overlay=ov)
    n = len(part.equity)
    np.testing.assert_allclose(full.equity[:n], part.equity, rtol=0, atol=1e-6)
    assert full.strategy == "ensemble@1+cross_asset@1(w=0.5)"


def test_overlay_evaluation_records_a_trial_and_a_verdict(db):
    _load_db(db)
    protocol.seal_holdout(db, start=dt.date(2024, 11, 18), end=dt.date(2025, 5, 30), now=NOW)
    groups = {"NVDA": ["semis"], "INTC": ["semis"]}
    with pytest.raises(protocol.HoldoutError):
        evaluate_overlay(db, strategy="ensemble@1", overlay=cross_asset.GroupConsensus(groups), start=dt.date(2021, 6, 1),
                         end=dt.date(2025, 1, 31), now=NOW)
    res = evaluate_overlay(db, strategy="ensemble@1", overlay=cross_asset.GroupConsensus(groups),
                           start=dt.date(2021, 6, 1), end=dt.date(2024, 11, 15), now=NOW)
    lo, hi = res["paired_excess_annual"]["ci95"]
    assert lo <= res["paired_excess_annual"]["mean"] <= hi
    assert res["verdict"] == ("adds_value" if lo > 0 and res["with"]["metrics"]["max_drawdown"]
                              <= res["without"]["metrics"]["max_drawdown"] else "no_added_value")
    assert db.experiments.count_documents({"strategy": "ensemble@1+cross_asset@1(w=0.5)", "kind": "development"}) == 1


def test_similar_api(db):
    _load_db(db)
    s = Settings(mongo_url="x", api_keys="k")
    with TestClient(create_app(s, db=db), base_url="https://testserver") as c:
        H = {"X-API-Key": "k"}
        assert c.get("/api/v1/analytics/similar/SPY", headers=H).status_code == 404   # not computed yet
        res = cross_asset.run_relationships(db, NOW)
        assert res["status"] == "computed" and cross_asset.run_relationships(db, NOW)["status"] == "current"
        sim = c.get("/api/v1/analytics/similar/SPY", headers=H).json()["similar"]
        assert sim[0]["symbol"] in ("QQQ", "QQQM") and sim[0]["pearson"] > 0.8 and sim[0]["link_candidate"]
        assert c.get("/api/v1/analytics/correlations?symbol=SPY&window=60", headers=H).json()


# --- review fixes (PR #29) ---------------------------------------------------------------------

def test_spearman_uses_average_ranks_and_constant_series_are_undefined():
    r = cross_asset.aligned_returns(_universe(), ["SPY", "QQQ"], ASOF, 252)
    a = np.round(r["SPY"], 3)        # rounding creates many real ties
    b = np.round(r["QQQ"], 3)
    st = cross_asset.pair_stats(a, b, 252)
    assert st["spearman"] == pytest.approx(pd.Series(a[-252:]).corr(pd.Series(b[-252:]), method="spearman"))
    flat = np.zeros_like(a)
    st = cross_asset.pair_stats(a, flat, 252)
    assert st["pearson"] is None and st["spearman"] is None and st["best_lag"] is None


def test_relationships_cover_watched_symbols_refresh_on_late_arrivals_and_drop_deleted(db):
    _load_db(db)
    db.symbols.update_one({"_id": "^IRX"}, {"$set": {"enabled": True}})          # an index, not tradable
    last = dt.datetime(2025, 6, 2, tzinfo=dt.timezone.utc)
    held = db.bars.find_one({"symbol": "INTC", "session": last})
    db.bars.delete_one({"_id": held["_id"]})
    first = cross_asset.run_relationships(db, NOW)
    syms = db.relationship_runs.find_one({"_id": "latest"})["symbols"]
    assert "^IRX" in syms and "INTC" not in syms
    assert cross_asset.run_relationships(db, NOW)["status"] == "current"
    db.bars.insert_one(held)                                                       # INTC's close arrives later
    again = cross_asset.run_relationships(db, NOW)
    assert again["status"] == "computed" and "INTC" in db.relationship_runs.find_one({"_id": "latest"})["symbols"]
    db.symbols.delete_one({"_id": "QQQM"})
    out = cross_asset.run_relationships(db, NOW)
    assert out["removed_obsolete"] > 0
    assert not db.relationships.find_one({"$or": [{"a": "QQQM"}, {"b": "QQQM"}]})
    assert all(x["symbol"] != "QQQM" for x in cross_asset.similar(db, "SPY", 20)["similar"])
    assert first["pairs"] > 0
