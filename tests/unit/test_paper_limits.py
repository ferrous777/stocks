"""Sizing arithmetic used by the trade-suggestions skill (.claude/skills/trade-suggestions/scripts/paper_limits.py)."""
import importlib.util
import json
import pathlib
import subprocess
import sys

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parents[2] / ".claude/skills/trade-suggestions/scripts/paper_limits.py"
spec = importlib.util.spec_from_file_location("paper_limits", SCRIPT)
pl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pl)

COSTS = {"commission_per_share": 0.0, "min_commission": 0.0, "half_spread_bps": 5.0, "slippage_bps": 5.0,
         "borrow_rate_annual": 0.03}


def inp(**kw):
    base = {"side": "long", "entry": 100.0, "stop": 95.0, "target": 120.0, "equity": 100_000.0,
            "free_cash": 50_000.0, "open_gross": 0.0, "new_positions_this_decision": 0, "costs": dict(COSTS),
            "fill_session": "2027-03-01", "time_exit_session": "2027-08-31"}
    return {**base, **kw}


def test_long_takes_the_smallest_cap_and_reports_unrounded_returns():
    r = pl.size(inp())
    assert r["caps"]["notional_1000"] == 10 and r["caps"]["position_1pct_equity"] == 10
    assert r["qty"] == 10 and r["accepted"] and r["reasons"] == []
    entry_cost = 10 * 100 * 10 / 10_000
    assert r["return_denominator"] == pytest.approx(1000 + entry_cost)
    round_trip = entry_cost + 10 * 120 * 10 / 10_000
    assert r["target_profit_net"] == pytest.approx(200 - round_trip)
    assert r["target_return_net_if_target_hit"] == pytest.approx((200 - round_trip) / (1000 + entry_cost))
    assert r["meets_15pct_target_objective"] is True
    assert "not maximum loss" in r["note"]


def test_stop_risk_cap_includes_round_trip_costs():
    r = pl.size(inp(stop=50.0, target=200.0))                    # $250 budget, $50 stop distance per share
    q = r["caps"]["stop_risk_0.25pct_equity"]
    loss = lambda n: n * 50 + n * 100 * 10 / 10_000 + n * 50 * 10 / 10_000   # noqa: E731
    assert q == 4 and loss(q) <= 250 < loss(q + 1)
    assert r["binding_cap"] == "stop_risk_0.25pct_equity" and r["qty"] == q


def test_minimum_commission_counts_in_the_stop_budget():
    r = pl.size(inp(equity=10_000.0, costs={**COSTS, "min_commission": 10.0}))
    assert r["qty"] == 0 and "not even one share" in r["reasons"][0]   # 5 + 2*$10 commissions > $25 budget


def test_time_exit_after_six_calendar_months_rejects():
    r = pl.size(inp(fill_session="2026-11-23", time_exit_session="2027-05-27"))
    assert r["qty"] == 0 and not r["accepted"]
    assert r["six_month_deadline"] == "2027-05-23" and "six calendar months" in r["reasons"][0]


def test_month_end_clamps():
    assert pl.add_calendar_months(pl.dt.date(2026, 8, 31), 6).isoformat() == "2027-02-28"


def test_short_needs_borrow_rate_and_uses_short_notional_denominator():
    with pytest.raises(pl.InputError, match="cannot short"):
        pl.size(inp(side="short", entry=100.0, stop=105.0, target=80.0, costs={**COSTS, "borrow_rate_annual": None}))
    r = pl.size(inp(side="short", entry=100.0, stop=105.0, target=80.0))
    assert r["return_denominator"] == pytest.approx(r["qty"] * 100) and r["borrow_cost_full_horizon"] > 0


def test_short_collateral_is_free_cash_not_proceeds():
    r = pl.size(inp(side="short", entry=100.0, stop=105.0, target=80.0, free_cash=350.0))
    assert r["caps"]["free_cash"] == 3 and r["qty"] == 3


def test_gross_exposure_includes_open_and_reserved():
    r = pl.size(inp(open_gross=9_700.0))
    assert r["caps"]["gross_10pct_equity"] == 3 and r["qty"] == 3


def test_server_limit_and_two_positions_per_decision():
    assert pl.size(inp(server_max_qty=4))["qty"] == 4
    r = pl.size(inp(new_positions_this_decision=2))
    assert r["qty"] == 0 and "already placed" in r["reasons"][0]


def test_one_share_must_fit():
    r = pl.size(inp(entry=1500.0, stop=1400.0, target=1800.0))
    assert r["qty"] == 0 and r["binding_cap"] == "notional_1000"


def test_caps_cannot_be_loosened_by_input():
    assert pl.size(inp(MAX_NOTIONAL=1e9, caps={"notional_1000": 999}))["qty"] == 10


@pytest.mark.parametrize("bad,match", [
    ({"equity": None}, "missing inputs: equity"),
    ({"stop": 130.0}, "plan ordering"),
    ({"entry": float("nan")}, "finite"),
    ({"costs": {**COSTS, "slippage_bps": None}}, "costs.slippage_bps"),
    ({"time_exit_session": "2027-02-01"}, "after fill_session"),
    ({"new_positions_this_decision": True}, "whole number"),
    ({"entry": 0.004, "stop": 0.001, "target": 0.01}, "rounds to"),
])
def test_missing_or_invalid_inputs_fail_explicitly(bad, match):
    with pytest.raises(pl.InputError, match=match):
        pl.size(inp(**bad))


def test_cli_round_trip(tmp_path):
    f = tmp_path / "in.json"
    f.write_text(json.dumps(inp()))
    ok = subprocess.run([sys.executable, "-I", str(SCRIPT), str(f)], capture_output=True, text=True)
    assert ok.returncode == 0 and json.loads(ok.stdout)["qty"] == 10
    f.write_text(json.dumps(inp(equity=None)))
    bad = subprocess.run([sys.executable, "-I", str(SCRIPT), str(f)], capture_output=True, text=True)
    assert bad.returncode == 2 and "missing inputs" in json.loads(bad.stderr)["error"]


def test_non_object_input_fails_explicitly(tmp_path):
    for bad in (None, 42, [inp()]):
        with pytest.raises(pl.InputError, match="JSON object"):
            pl.size(bad)
    f = tmp_path / "null.json"
    f.write_text("null")
    out = subprocess.run([sys.executable, "-I", str(SCRIPT), str(f)], capture_output=True, text=True)
    assert out.returncode == 2 and "JSON object" in json.loads(out.stderr)["error"]


def test_borrow_uses_the_brokers_360_day_basis():
    r = pl.size(inp(side="short", entry=100.0, stop=105.0, target=80.0))
    days = (pl.dt.date(2027, 8, 31) - pl.dt.date(2027, 3, 1)).days
    assert r["borrow_cost_full_horizon"] == pytest.approx(r["qty"] * 100 * 0.03 * days / 360)


def test_sizes_on_the_cent_rounded_prices_the_broker_executes():
    r = pl.size(inp(entry=100.004, stop=94.996, target=120.006))
    assert r["plan_execution"] == {"entry": 100.0, "stop": 95.0, "target": 120.01}
    assert r["plan_served"]["entry"] == 100.004 and r["initial_notional"] == 1000.0
    with pytest.raises(pl.InputError, match="plan ordering"):          # levels that collapse after rounding
        pl.size(inp(entry=100.001, stop=99.999, target=120.0))
