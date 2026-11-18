import datetime as dt

import numpy as np
import pytest

from stocks_service.research import protocol, tuning

from .conftest import NOW
from .test_research import _load_db


def test_rank_scores_weight_normalized_ranks():
    m = {"a": {"sharpe": 1.0, "cagr": 0.10, "max_drawdown": 0.30},
         "b": {"sharpe": 0.5, "cagr": 0.20, "max_drawdown": 0.10},
         "c": {"sharpe": 0.0, "cagr": 0.00, "max_drawdown": 0.50}}
    s = tuning.rank_scores(m)
    assert s["a"] == pytest.approx(0.5 * 1 + 0.3 * 0.5 + 0.2 * 0.5)
    assert s["b"] == pytest.approx(0.5 * 0.5 + 0.3 * 1 + 0.2 * 1)
    assert s["c"] == pytest.approx(0.0)


def test_folds_expand_and_never_overlap(monkeypatch):
    from stocks_service import sessions
    days = sessions.sessions_between(dt.date(2006, 1, 3), dt.date(2024, 11, 15))
    fs = tuning.folds(days)
    assert days[fs[0][1]].year == 2012
    for (tr, ts, te), nxt in zip(fs, fs[1:] + [None]):
        assert tr == ts and ts < te
        if nxt:
            assert te == nxt[1]                       # contiguous test windows
    assert days[fs[-1][2] - 1] == dt.date(2024, 11, 15)


def test_tuning_records_every_trial_and_selects_on_training_data_only(db, monkeypatch):
    _load_db(db)
    protocol.seal_holdout(db, start=dt.date(2024, 11, 18), end=dt.date(2025, 5, 30), now=NOW)
    with pytest.raises(protocol.HoldoutError):
        tuning.tune(db, strategy="ma_crossover@1", start=dt.date(2021, 6, 1), end=dt.date(2025, 1, 31), now=NOW)
    with pytest.raises(ValueError, match="too short"):
        tuning.tune(db, strategy="ma_crossover@1", start=dt.date(2021, 6, 1), end=dt.date(2024, 11, 15), now=NOW)
    monkeypatch.setattr(tuning, "FIRST_TRAIN_YEARS", 1)
    monkeypatch.setattr(tuning, "FOLD_YEARS", 1)
    monkeypatch.setattr(tuning, "GRID", {"stop_atr": (2.0, 3.0), "target_atr": (4.0, 6.0)})
    d = tuning.tune(db, strategy="ma_crossover@1", start=dt.date(2021, 6, 1), end=dt.date(2024, 11, 15), now=NOW)
    trials = list(db.experiments.find({"params.search": "tuning@1"}))
    assert len(trials) == 4 and {(t["params"]["stop_atr"], t["params"]["target_atr"]) for t in trials} == {
        (2.0, 4.0), (2.0, 6.0), (3.0, 4.0), (3.0, 6.0)}
    assert d["status"] in ("adopt", "research") and d["default"] == "stop=2.0,target=4.0"
    lo, hi = d["paired_excess_annual"]["ci95"]
    assert (d["status"] == "adopt") == (lo > 0)
    assert [f["test_from"][:4] for f in d["folds"]] == ["2022", "2023", "2024"]
    assert db.param_sets.count_documents({}) == 1
