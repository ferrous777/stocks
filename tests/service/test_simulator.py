import datetime as dt
import math

import pytest

from stocks_service import sessions
from stocks_service.sim import Bar, CostProfile, ExecutionPolicy, TradePlan, gross_return, net_trade, simulate_trade

from .conftest import NVDA_LONG, raw_daily

DECIDED = dt.date(2023, 3, 1)


def _bars(after: dt.date = DECIDED, n: int = 300) -> list[Bar]:
    bars, _ = raw_daily(NVDA_LONG, "NVDA")
    out = [Bar(b["session"], b["o"], b["h"], b["l"], b["c"]) for b in bars if b["session"] > after]
    return out[:n]


def _sim(plan, bars=None, policy=ExecutionPolicy()):
    bars = bars if bars is not None else _bars(plan.decided)
    return simulate_trade(plan, bars, sessions.next_session(plan.decided), policy)


def _long(entry, stop_frac=0.5, target_frac=2.0, decided=DECIDED):
    return TradePlan("long", decided, entry, entry * stop_frac, entry * target_frac)


def test_first_bar_must_be_the_next_session():
    bars = _bars()
    with pytest.raises(ValueError, match="eligible session"):
        simulate_trade(_long(bars[1].o), bars[1:], sessions.next_session(DECIDED))


def test_limit_must_trade_through_not_just_touch():
    b0 = _bars()[0]
    assert _sim(_long(b0.l)).result == "not_filled"  # touched only
    o = _sim(_long(b0.l * 1.001 if b0.l * 1.001 < b0.o else (b0.l + b0.o) / 2))
    assert o.fill_session == b0.session and not o.gap_fill
    assert o.fill_price < b0.o


def test_open_at_or_through_limit_fills_at_open():
    b0 = _bars()[0]
    o = _sim(_long(b0.o * 1.02))
    assert (o.fill_price, o.gap_fill) == (b0.o, True)


def test_entry_gap_through_stop_policies():
    b0 = _bars()[0]
    plan = TradePlan("long", DECIDED, b0.o * 1.10, b0.o * 1.05, b0.o * 1.30)  # open already below the stop
    o = _sim(plan)
    assert (o.result, o.fill_price, o.exit_price, o.sessions_held) == ("gap_stop", b0.o, b0.o, 0)
    assert _sim(plan, policy=ExecutionPolicy(gap_through_stop="cancel")).result == "not_filled"


def test_target_is_not_credited_on_the_fill_bar():
    b0 = _bars()[0]
    plan = TradePlan("long", DECIDED, b0.o * 1.01, b0.l * 0.5, (b0.o + b0.h) / 2)  # target inside fill bar range
    o = _sim(plan)
    assert o.fill_session == b0.session
    assert not (o.result == "target" and o.exit_session == b0.session)


def test_stop_reached_within_fill_bar_is_ambiguous_stop():
    b0 = _bars()[0]
    plan = TradePlan("long", DECIDED, b0.o * 1.01, (b0.l + b0.o) / 2 * 0.999 if b0.l < b0.o else b0.l, b0.o * 3)
    o = _sim(plan)
    assert (o.result, o.exit_session, o.ambiguous) == ("stop", b0.session, True)


def _all_bars():
    bars, _ = raw_daily(NVDA_LONG, "NVDA")
    return [Bar(b["session"], b["o"], b["h"], b["l"], b["c"]) for b in bars]


def test_bar_spanning_stop_and_target_assumes_stop():
    """Find a real day k=1 whose range exceeds the fill bar's on both sides (an outside bar)."""
    allb = _all_bars()
    for i in range(1, len(allb) - 2):
        b0, b1 = allb[i], allb[i + 1]
        if b1.l < b0.l and b1.h > b0.h and b0.l < b1.o < b0.h and b0.o < b0.h:
            break
    else:
        pytest.fail("no outside bar in fixture")
    decided = allb[i - 1].session
    stop, target = (b1.l + b0.l) / 2, (b1.h + b0.h) / 2  # untouched on the fill bar, both hit on b1
    plan = TradePlan("long", decided, b0.o, stop, target)
    o = simulate_trade(plan, allb[i:], sessions.next_session(decided))
    assert (o.result, o.exit_session, o.exit_price, o.ambiguous) == ("stop", b1.session, stop, True)


def test_gap_through_stop_on_later_bar_exits_at_open():
    """Real gap down: NVDA closed 2022-08-05 and opened 2022-08-08 below the prior low."""
    allb = _all_bars()
    i = next(k for k, b in enumerate(allb) if b.session == dt.date(2022, 8, 5))
    b0, b1 = allb[i], allb[i + 1]
    assert b1.o < b0.l
    stop = (b1.o + b0.l) / 2
    plan = TradePlan("long", allb[i - 1].session, b0.o, stop, b0.h * 2)
    o = simulate_trade(plan, allb[i:], sessions.next_session(plan.decided))
    assert (o.result, o.exit_session, o.exit_price) == ("gap_stop", b1.session, b1.o)
    assert o.exit_price < stop  # filled at the worse open, not at the stop


def test_timeout_triggers_at_close_and_exits_next_open():
    bars = _bars()
    plan = _long(bars[0].o * 1.0001, stop_frac=0.01, target_frac=100)
    o = _sim(plan, policy=ExecutionPolicy(timeout_sessions=5))
    assert (o.result, o.exit_session, o.exit_price, o.sessions_held) == ("timeout", bars[6].session, bars[6].o, 6)
    assert o.fill_session == bars[0].session


def test_running_out_of_bars_is_unresolved_not_invented():
    bars = _bars()[:4]
    o = _sim(_long(bars[0].o * 1.0001, 0.01, 100), bars=bars)
    assert o.result == "unresolved" and o.exit_price is None and o.fill_price is not None


def test_short_is_mirrored():
    b0 = _bars()[0]
    plan = TradePlan("short", DECIDED, b0.o * 0.98, b0.o * 1.5, b0.o * 0.2)
    o = _sim(plan)
    assert (o.fill_price, o.gap_fill) == (b0.o, True)  # opened at/above the short limit
    assert gross_return(o, "short") is None or o.result in ("timeout", "stop", "target", "gap_stop", "unresolved")


def test_invalid_plans_are_rejected():
    with pytest.raises(ValueError):
        TradePlan("long", DECIDED, 100, 110, 120)
    with pytest.raises(ValueError):
        TradePlan("short", DECIDED, 100, 90, 80)


# --- costs ---------------------------------------------------------------------

PROFILE = CostProfile("test", 1, commission_per_share=0.0, min_commission=0.0, half_spread_bps=5,
                      slippage_bps=5, borrow_rate_annual=0.03)


def test_net_return_subtracts_spread_slippage_and_commission():
    bars = _bars()
    o = _sim(_long(bars[0].o * 1.0001, 0.01, 100), policy=ExecutionPolicy(timeout_sessions=5))
    r = net_trade(o, "long", 100, PROFILE)
    expected_friction = (o.fill_price + o.exit_price) * 100 * 10 / 10_000 / (o.fill_price * 100)
    assert r.gross_return == pytest.approx(o.exit_price / o.fill_price - 1)
    assert r.net_return == pytest.approx(r.gross_return - expected_friction)
    worse = net_trade(o, "long", 100, PROFILE.scaled(2, "_x2"))
    assert worse.net_return < r.net_return


def test_short_costs_include_borrow_and_require_a_rate():
    b0 = _bars()[0]
    o = _sim(TradePlan("short", DECIDED, b0.o * 0.99, b0.o * 100, b0.o * 0.01), policy=ExecutionPolicy(timeout_sessions=5))
    r = net_trade(o, "short", 10, PROFILE)
    assert r.borrow > 0 and r.net_return < r.gross_return
    no_short = CostProfile("no_short", 1, 0, 0, 5, 5, None)
    with pytest.raises(ValueError, match="does not allow shorts"):
        net_trade(o, "short", 10, no_short)


def test_dividends_credit_longs_and_charge_shorts_within_holding_window():
    bars = _bars()
    o = _sim(_long(bars[0].o * 1.0001, 0.01, 100), policy=ExecutionPolicy(timeout_sessions=5))
    inside = [(bars[2].session, 0.04)]
    outside = [(bars[0].session, 0.04), (bars[20].session, 0.04)]  # ex on fill day or after exit: not earned
    assert net_trade(o, "long", 100, PROFILE, inside).dividends == pytest.approx(4.0)
    assert net_trade(o, "long", 100, PROFILE, outside).dividends == 0
    assert net_trade(o, "short", 100, PROFILE, inside).dividends == pytest.approx(-4.0)


def test_unresolved_has_no_net_result_and_not_filled_is_zero():
    bars = _bars()[:3]
    o = _sim(_long(bars[0].o * 1.0001, 0.01, 100), bars=bars)
    assert net_trade(o, "long", 10, PROFILE) is None
    nf = _sim(_long(_bars()[0].l))
    assert net_trade(nf, "long", 10, PROFILE).net_return == 0.0


def test_trade_across_a_split_uses_the_decision_basis():
    """Raw bars drop ~10x at NVDA's 2024-06-10 split; that must not look like a stop."""
    from stocks_service.sim import bars_on_decision_basis
    raw, splits = raw_daily(NVDA_LONG, "NVDA")
    decided = dt.date(2024, 6, 5)
    adj = bars_on_decision_basis(raw, splits, decided)
    plan = TradePlan("long", decided, adj[0].o, adj[0].o * 0.85, adj[0].o * 1.6)
    o = simulate_trade(plan, adj, sessions.next_session(decided), ExecutionPolicy(timeout_sessions=20))
    assert o.result != "gap_stop" and o.exit_session > dt.date(2024, 6, 10)
    raw_bars = [Bar(b["session"], b["o"], b["h"], b["l"], b["c"]) for b in raw if b["session"] > decided]
    naive = simulate_trade(plan, raw_bars, sessions.next_session(decided), ExecutionPolicy(timeout_sessions=20))
    assert (naive.result, naive.exit_session) == ("gap_stop", dt.date(2024, 6, 10))  # what the raw basis would do
