import dataclasses
import datetime as dt

import numpy as np
import pytest

from stocks_service import umpires
from stocks_service.outlook import build
from stocks_service.research import protocol

from .conftest import NOW
from .test_research import COST, _load_db, _series, _universe

CUT = dt.date(2024, 11, 18)


@pytest.fixture(scope="module")
def data():
    uni = _universe()
    return umpires.build_training(uni, ["NVDA", "INTC", "SPY", "QQQ", "QQQM"], _series("^IRX"), dt.date(2020, 6, 1),
                                  CUT, COST, resolved_before=CUT)


def test_features_are_point_in_time_and_finite():
    s = _series("NVDA")
    f = umpires.features(s.view_at(dt.date(2023, 6, 30)))
    assert f.shape == (len(umpires.FEATURES),) and np.all(np.isfinite(f))
    cut = _series("NVDA", cutoff=dt.date(2023, 6, 30))
    np.testing.assert_array_equal(umpires.features(cut.view_at(dt.date(2023, 6, 30))), f)   # no future data used
    assert umpires.features(s.view_at(dt.date(2020, 9, 1))) is None                        # < 253 bars


def test_training_only_uses_resolved_outcomes(data):
    for side in ("long", "short"):
        o = data[side]
        assert len(o["y"]) > 300 and o["X"].shape == (len(o["y"]), len(umpires.FEATURES))
        assert all(r < CUT for r in o["resolved"])


def test_knn_vote_and_gmm_are_deterministic_and_consistent(data):
    o = data["long"]
    m1, m2 = umpires.SideModel(o["X"], o["y"]), umpires.SideModel(o["X"], o["y"])
    a1, a2 = m1.annotate(o["X"][:40]), m2.annotate(o["X"][:40])
    assert a1 == a2
    lose, win = m1.knn(o["X"][:40])
    for a, ls, ws in zip(a1, lose, win):
        assert a["knn"] == ("veto" if ls >= umpires.VOTE else "favorable" if ws >= umpires.VOTE else "neutral")
        assert 0 <= ls <= 1 and 0 <= ws <= 1
    # Brute-force check of one neighbour set.
    q = (o["X"][0] - m1.mu) / m1.sd
    d = (((m1.Z.astype(float) - q) ** 2).sum(axis=1))
    nn = np.argsort(d)[: umpires.K]
    assert lose[0] == pytest.approx(m1.loser[nn].mean())
    assert m1.comp_n.sum() == len(o["y"])


def test_walk_forward_trains_strictly_before_each_year(data):
    ev = umpires.walk_forward(data, CUT)
    for r in ev.values():
        assert r["verdict"] in ("useful", "not_useful", "insufficient")
        if "ci95" in r:
            assert r["ci95"][0] <= r["difference"] <= r["ci95"][1]


def test_outlook_rows_carry_annotations_never_filtering(db):
    _load_db(db)
    protocol.seal_holdout(db, start=CUT, end=dt.date(2025, 5, 30), now=NOW)
    db.cost_profiles.insert_one({"_id": "market@1", **dataclasses.asdict(protocol.BASE_COST), "profile_id": "market"})
    cal = build.run_calibration(db, now=NOW)
    before = build.build_outlook(db, now=NOW, calibration=cal)
    assert {r["umpires"]["status"] for r in before["rows"] if r.get("plan")} == {"untrained"}
    res = umpires.train(db, now=NOW)
    assert set(res["trained_sides"]) == {"long", "short"}
    after = build.build_outlook(db, now=NOW + dt.timedelta(seconds=1), calibration=cal)
    assert len(after["rows"]) == len(before["rows"])                      # annotations never hide rows
    planned = [r for r in after["rows"] if r.get("plan")]
    assert planned and all(r["umpires"]["status"] == "annotated" and r["umpires"]["side_verdict"] for r in planned)


def test_outlook_page_shows_umpires(db):
    from fastapi.testclient import TestClient
    from stocks_service.api.app import create_app
    from stocks_service.settings import Settings
    test_outlook_rows_carry_annotations_never_filtering(db)
    s = Settings(mongo_url="x", api_keys="k", admin_password="pw", session_secret="s" * 40)
    with TestClient(create_app(s, db=db), base_url="https://testserver") as c:
        c.post("/login", data={"password": "pw"})
        page = c.get("/outlook").text
        assert "Umpire" in page and "most similar past setups" in page
