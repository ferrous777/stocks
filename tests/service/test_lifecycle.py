import dataclasses
import datetime as dt

import pytest

from stocks_service import lifecycle, sessions
from stocks_service.outlook import build, calibration
from stocks_service.paper import broker
from stocks_service.research import protocol
from stocks_service.research.series import SymbolSeries
from stocks_service.sim import ExecutionPolicy, TradePlan, net_trade, simulate_trade

from .conftest import NOW
from .test_paper import EVENING, LATER, world  # noqa: F401  (fixture)

UTC = dt.timezone.utc


@pytest.fixture(autouse=True)
def _versions(db):
    from stocks_service.strategies import sync_strategy_versions
    sync_strategy_versions(db, NOW)   # done by the app at startup


def test_outlook_decisions_are_replayed_and_a_mismatch_pauses_the_version(db, world):  # noqa: F811
    live = db.signals.count_documents({"source": "live"})
    assert live > 0
    assert lifecycle.run_parity(db, NOW) == {"checked": live, "violations": 0}
    assert lifecycle.run_parity(db, NOW)["checked"] == 0           # each live decision is checked once
    s = db.signals.find_one({"source": "live"})
    db.signals.update_one({"_id": s["_id"]}, {"$set": {"strength": s["strength"] + 0.5},
                                              "$unset": {"parity_checked_at": ""}})
    assert lifecycle.run_parity(db, NOW) == {"checked": 1, "violations": 1}
    assert db.strategy_versions.find_one({"_id": s["strategy"]})["status"] == "paused"
    assert db.parity_violations.count_documents({"strategy": s["strategy"]}) == 1


def test_forecasts_are_scored_with_the_label_rules_once_resolved(db, world):  # noqa: F811
    assert lifecycle.track_forecasts(db, NOW)["resolved"] == 0       # later bars not stored yet: pending
    db.bars.insert_many(world)
    first = lifecycle.track_forecasts(db, NOW)
    assert first["resolved"] > 0 and first["data_gaps"] == 0
    assert lifecycle.track_forecasts(db, NOW)["resolved"] == 0       # once per row
    o = build.latest_outlook(db)
    cost = build.cost_profile_from_doc(o["cost"])
    irx = SymbolSeries.from_db(db, "^IRX")
    for f in db.forecast_outcomes.find():
        row = next(r for r in o["rows"] if r["symbol"] == f["symbol"] and r["side"] == f["side"])
        assert f["predicted_mean_excess"] == row["estimate"]["mean_excess"] and f["source"] == row["source"]
        s = SymbolSeries.from_db(db, f["symbol"])
        d = dt.date.fromisoformat(f["asof"])
        p = row["plan"]
        oc = simulate_trade(TradePlan(f["side"], d, round(p["entry_limit"], 2), round(p["stop"], 2),
                                      round(p["target"], 2)), s.bars_after(d, 129), sessions.next_session(d),
                            ExecutionPolicy())
        assert f["result"] == oc.result
        if oc.result != "not_filled":
            nt = net_trade(oc, f["side"], 10_000.0 / oc.fill_price, cost, s.dividends_on_basis(d))
            cash = irx.raw[irx.count_through(d) - 1]["c"] / 100 * (oc.exit_session - oc.fill_session).days / 360
            assert f["realized_excess"] == pytest.approx(nt.net_return - cash)


def test_monitor_statistics_and_breach(db, world, monkeypatch):  # noqa: F811
    db.bars.insert_many(world)
    lifecycle.track_forecasts(db, NOW)
    src = "base_rate"
    n = db.forecast_outcomes.count_documents({"source": src})
    assert lifecycle.monitor(db, src)["status"] == "insufficient"    # fewer than 30 resolved
    monkeypatch.setattr(lifecycle, "WINDOW", n)
    m = lifecycle.monitor(db, src)
    xs = list(db.forecast_outcomes.find({"source": src}))
    assert m["realized_mean"] == pytest.approx(sum(x["realized_excess"] for x in xs) / n)
    assert m["status"] in ("ok", "breach") and (m["status"] == "breach") == bool(m["breaches"])


def _signal_world(db, world, monkeypatch):  # noqa: F811
    monkeypatch.setattr(calibration, "MIN_SKILL", -1.0)   # test configuration: let signal buckets publish
    cal = build.run_calibration(db, now=NOW)
    o = build.build_outlook(db, now=EVENING + dt.timedelta(seconds=1), calibration=cal)
    row = next(r for r in o["rows"] if r["source"].startswith("signal:") and r.get("plan"))
    return row, row["source"].removeprefix("signal:")


def test_transitions_require_evidence_and_are_recorded(db, world, monkeypatch):  # noqa: F811
    row, key = _signal_world(db, world, monkeypatch)
    with pytest.raises(lifecycle.LifecycleError, match="not an allowed transition"):
        lifecycle.transition(db, key, "active", reason="skip ahead", now=NOW)
    with pytest.raises(lifecycle.LifecycleError, match="no development research result"):
        lifecycle.transition(db, key, "candidate", reason="looks good", now=NOW)
    protocol.run_development(db, start=dt.date(2021, 6, 1), end=dt.date(2024, 11, 15), now=NOW, strategies=[key])
    with pytest.raises(lifecycle.LifecycleError, match="development gate failed"):
        lifecycle.transition(db, key, "candidate", reason="looks good", now=NOW)
    # Make the stored report say it passed (test input) to exercise the next gate.
    db.research_reports.update_one({}, {"$set": {f"results.{key}.gate.eligible": True}})
    assert lifecycle.transition(db, key, "candidate", reason="passed dev gate", now=NOW)["to"] == "candidate"
    with pytest.raises(lifecycle.LifecycleError, match="no holdout evaluation"):
        lifecycle.transition(db, key, "active", reason="ship it", now=NOW)
    events = list(db.lifecycle_events.find({"strategy": key}))
    assert [(e["from"], e["to"]) for e in events] == [("research", "candidate")] and events[0]["evidence"]
    assert lifecycle.transition(db, key, "retired", reason="superseded", now=NOW)["to"] == "retired"


def test_pause_blocks_new_entries_only(db, world, monkeypatch):  # noqa: F811
    row, key = _signal_world(db, world, monkeypatch)
    db.strategy_versions.update_one({"_id": key}, {"$set": {"status": "active"}})
    broker.create_paper_account(db, account_id="p", name="P", starting_cash=100_000.0, risk_profile="default@1",
                                now=EVENING)
    broker.place_order(db, "p", symbol=row["symbol"], side=row["side"], qty=1, idempotency_key="signal-order",
                       decided_by={}, now=EVENING)
    other = next(r for r in build.latest_outlook(db)["rows"] if r["source"] == "base_rate"
                 and r["symbol"] != row["symbol"] and r.get("plan"))
    broker.place_order(db, "p", symbol=other["symbol"], side=other["side"], qty=1, idempotency_key="base-order",
                       decided_by={}, now=EVENING)
    res = lifecycle.transition(db, key, "paused", reason="manual review", now=NOW)
    assert res["cancelled_entry_orders"] == 1
    assert db.orders.find_one({"idempotency_key": "signal-order"})["status"] == "cancelled"
    assert db.orders.find_one({"idempotency_key": "base-order"})["status"] == "open"   # other sources untouched
    o = build.build_outlook(db, now=EVENING + dt.timedelta(seconds=2))
    assert not any(r["source"] == f"signal:{key}" for r in o["rows"])                   # no new estimates from it


def test_monitor_breach_pauses_an_active_version(db, world, monkeypatch):  # noqa: F811
    row, key = _signal_world(db, world, monkeypatch)
    db.strategy_versions.update_one({"_id": key}, {"$set": {"status": "active"}})
    db.bars.insert_many(world)
    lifecycle.track_forecasts(db, NOW)
    monkeypatch.setattr(lifecycle, "monitor", lambda db_, source: (
        {"source": source, "status": "breach", "breaches": ["test breach"]} if source == f"signal:{key}"
        else {"source": source, "status": "ok", "breaches": []}))
    lifecycle.run_monitors(db, NOW)
    v = db.strategy_versions.find_one({"_id": key})
    assert v["status"] == "paused" and v["paused_reason"] == "test breach"
    assert db.lifecycle_events.find_one({"strategy": key, "to": "paused", "by": "monitor"})
