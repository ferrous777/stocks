"""Portfolio backtest of a strategy under the reproducible ``baseline_v1`` selection policy.

Daily loop over XNYS sessions. At each close d:
  1. settle exits whose exit session is d and fills/expiries of orders placed at d-1;
  2. mark the portfolio to market (on each trade's decision-date price basis);
  3. accrue the 13-week T-bill rate (^IRX, known at d) on free cash;
  4. decide with only data <= d (``SymbolSeries.view_at``), rank candidates, size them and
     place limit orders for d+1, reserving cash.

Cash flows are booked when they occur: entry costs at the fill, short borrow nightly, dividends
on the ex-date (credited to longs, charged to shorts), exit costs and P&L at the exit. So open
positions carry their costs in equity, and closed trades reconcile exactly with ``net_trade``.

Every session must be backed by data: a missing ^IRX rate (stale by more than a week), a
window ending after the last stored session, or a missing bar for a held position raises
``DataCoverageError`` instead of extending prices or rates.

Each order's path is computed by the shared ``simulate_trade`` (same rules as labels and the
paper broker). Its result is only *applied* when its sessions arrive, so later decisions never
see the future. Shorts are fully collateralized (gross exposure <= equity, no leverage).
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field

from .. import sessions
from ..levels import LevelsUnavailable, atr_levels
from ..sim import CostProfile, ExecutionPolicy, TradePlan, entry_costs, exit_costs, net_trade, simulate_trade
from ..sim.costs import borrow_cost
from ..strategies import decide, get_spec
from .series import SymbolSeries

POLICY_ID = "baseline_v1@1"


@dataclass(frozen=True)
class PolicyParams:
    max_positions: int = 10
    risk_per_trade: float = 0.01      # equity fraction lost if the stop is hit
    max_position_pct: float = 0.10    # equity fraction per position
    min_strength: float = 0.0
    allow_short: bool = True
    levels: tuple = (("atr_period", 14), ("entry_atr", 0.0), ("stop_atr", 2.0), ("target_atr", 4.0))

    @property
    def levels_dict(self) -> dict:
        return dict(self.levels)


@dataclass
class _Order:
    symbol: str
    side: str
    qty: float
    plan: TradePlan
    reserved: float
    outcome: object
    strength: float


@dataclass
class _Position:
    order: _Order
    qty: float           # shares actually filled (decision-date basis)
    fill: float
    notional: float      # fill * qty, set aside as collateral for both sides (no leverage)
    dividends: dict      # ex_date -> amount per decision-basis share
    booked: float = 0.0  # cash flows already booked besides the notional: costs, borrow, dividends, exit P&L

    @property
    def sign(self) -> int:
        return 1 if self.order.side == "long" else -1


@dataclass
class Trade:
    symbol: str
    side: str
    decided: dt.date
    fill_session: dt.date
    exit_session: dt.date
    result: str
    qty: float
    entry: float
    exit: float
    net_return: float
    gross_return: float
    sessions_held: int
    ambiguous: bool
    booked_pnl: float = 0.0  # cash P&L booked day by day by the backtest (equals net_return * notional)


@dataclass
class BacktestResult:
    strategy: str
    policy: str
    cost_profile: str
    execution_policy: str
    start: dt.date
    end: dt.date
    initial: float
    dates: list[dt.date] = field(default_factory=list)
    equity: list[float] = field(default_factory=list)
    exposure: list[float] = field(default_factory=list)  # invested gross / equity, per day
    trades: list[Trade] = field(default_factory=list)
    open_at_end: int = 0
    not_filled: int = 0
    traded_notional: float = 0.0
    min_cash: float = float("inf")  # lowest end-of-session free cash; negative would mean hidden leverage


IRX_MAX_STALENESS_DAYS = 7  # ^IRX skips bond-market holidays when NYSE is open


class DataCoverageError(ValueError):
    """The requested window needs observations that are not stored."""


def _irx_rate(irx: SymbolSeries, d: dt.date) -> float:
    i = irx.count_through(d)
    if i == 0:
        raise DataCoverageError(f"no ^IRX observation on or before {d}; cannot accrue cash interest")
    last = irx.sessions[i - 1]
    if (d - last).days > IRX_MAX_STALENESS_DAYS and i == len(irx.sessions):
        # Past the last stored rate: never extend it. (Interior gaps bounded by real observations, e.g.
        # Yahoo's missing 2020-03-18..30 near-zero yields, carry the last known rate and are listed in
        # the report by ``protocol.check_coverage``.)
        raise DataCoverageError(f"^IRX has no observation after {last}; load rates through {d}")
    return irx.raw[i - 1]["c"] / 100.0


def _max_qty(cost: CostProfile, price: float, budget: float) -> float:
    """Most shares whose notional plus entry costs fit in ``budget`` (commission bounded by min + per-share)."""
    per_share = price * (1 + (cost.half_spread_bps + cost.slippage_bps) / 10_000) + cost.commission_per_share
    return max(0.0, (budget - cost.min_commission) / per_share)


def run_backtest(universe: dict[str, SymbolSeries], tradable: list[str], irx: SymbolSeries, strategy_key: str,
                 start: dt.date, end: dt.date, cost: CostProfile, policy: ExecutionPolicy = ExecutionPolicy(),
                 params: PolicyParams = PolicyParams(), initial: float = 100_000.0) -> BacktestResult:
    spec = get_spec(strategy_key)
    days = sessions.sessions_between(start, end)
    if not days:
        raise ValueError(f"no sessions between {start} and {end}")
    if not any(universe[s].has_bar(days[-1]) for s in tradable):
        last = max((universe[s].sessions[-1] for s in tradable if universe[s].sessions), default=None)
        raise DataCoverageError(f"window ends {days[-1]} but stored market data ends {last}")
    res = BacktestResult(strategy_key, POLICY_ID, cost.key, policy.key, days[0], days[-1], initial)
    cash = initial
    orders: list[_Order] = []
    positions: list[_Position] = []
    allow_short = params.allow_short and cost.borrow_rate_annual is not None
    horizon_bars = policy.timeout_sessions + 3

    for i, d in enumerate(days):
        # 0) dividends with ex-date d on positions held into d (net_trade window: fill < ex <= exit)
        for p in positions:
            amt = p.dividends.get(d)
            if amt:
                flow = p.sign * amt * p.qty
                cash += flow
                p.booked += flow

        # 1) fills / expiries for orders placed at the previous close
        still = []
        for o in orders:
            oc = o.outcome
            if oc.fill_session is not None and oc.fill_session == d:
                cash += o.reserved
                # A short can fill above its limit on an opening gap: never exceed the reserved collateral.
                qty = min(o.qty, _max_qty(cost, oc.fill_price, o.reserved))
                notional = oc.fill_price * qty
                ec = entry_costs(cost, oc.fill_price, qty)
                cash -= notional + ec
                divs = dict(universe[o.symbol].dividends_on_basis(o.plan.decided))
                positions.append(_Position(o, qty, oc.fill_price, notional, divs, booked=-ec))
                res.traded_notional += notional
            elif oc.fill_session is None and o.plan.decided < d:
                cash += o.reserved  # not filled (or cancelled) on its only eligible session
                res.not_filled += 1
            else:
                still.append(o)
        orders = still
        # exits on d
        remaining = []
        for p in positions:
            oc = p.order.outcome
            if oc.exit_session is not None and oc.exit_session == d:
                pnl = p.sign * (oc.exit_price - p.fill) * p.qty - exit_costs(cost, oc.exit_price, p.qty)
                cash += p.notional + pnl
                p.booked += pnl
                res.traded_notional += oc.exit_price * p.qty
                nt = net_trade(oc, p.order.side, p.qty, cost, list(p.dividends.items()))
                res.trades.append(Trade(p.order.symbol, p.order.side, p.order.plan.decided, oc.fill_session,
                                        oc.exit_session, oc.result, p.qty, oc.fill_price, oc.exit_price,
                                        nt.net_return, nt.gross_return, oc.sessions_held, oc.ambiguous, p.booked))
            else:
                remaining.append(p)
        positions = remaining

        # 2) mark to market (costs, borrow and dividends are already in cash)
        invested = 0.0
        value = cash + sum(o.reserved for o in orders)
        for p in positions:
            series = universe[p.order.symbol]
            if not series.has_bar(d):
                raise DataCoverageError(f"{p.order.symbol} has no bar on {d} while a position is open")
            mark = series.close_on_basis(p.order.plan.decided, d)
            value += p.notional + p.sign * (mark - p.fill) * p.qty
            invested += p.notional
        res.min_cash = min(res.min_cash, cash)
        res.dates.append(d)
        res.equity.append(value)
        res.exposure.append(invested / value if value > 0 else 0.0)

        # 3) interest on free cash (overnight, rate known at d)
        if i + 1 < len(days):
            gap_days = (days[i + 1] - d).days
            cash *= 1 + _irx_rate(irx, d) * gap_days / 360
            for p in positions:  # short borrow for the night, on the entry notional (as in net_trade)
                if p.order.side == "short":
                    fee = borrow_cost(cost, p.notional, gap_days)
                    cash -= fee
                    p.booked -= fee

        # 4) decisions for d+1
        if i + 1 >= len(days):
            break
        held = {p.order.symbol for p in positions} | {o.symbol for o in orders}
        slots = params.max_positions - len(held)
        if slots <= 0:
            continue
        candidates = []
        for sym in tradable:
            if sym in held:
                continue
            series = universe[sym]
            if series.count_through(d) < spec.min_bars or series.sessions[series.count_through(d) - 1] != d:
                continue  # no bar today (not yet listed, halted, or data gap): no decision
            view = series.view_at(d)
            dec = decide(view, spec)
            if dec.direction not in ("long", "short") or dec.strength < params.min_strength:
                continue
            if dec.direction == "short" and not allow_short:
                continue
            try:
                lv = atr_levels(view, dec.direction, params.levels_dict)
            except LevelsUnavailable:
                continue
            candidates.append((dec.strength, sym, dec.direction, lv))
        candidates.sort(key=lambda c: (-c[0], c[1]))
        equity = value
        for strength, sym, side, lv in candidates[:slots]:
            risk_per_share = abs(lv.entry_limit - lv.stop)
            qty = min(equity * params.risk_per_trade / risk_per_share,
                      equity * params.max_position_pct / lv.entry_limit)
            qty = min(qty, _max_qty(cost, lv.entry_limit, cash))
            reserve = qty * lv.entry_limit + entry_costs(cost, lv.entry_limit, qty)
            if qty <= 0 or not math.isfinite(qty) or reserve < 1.0:
                continue
            series = universe[sym]
            plan = TradePlan(side, d, lv.entry_limit, lv.stop, lv.target)
            bars = series.bars_after(d, horizon_bars)
            if not bars or bars[0].session != days[i + 1]:
                continue  # no bar on the eligible session (data gap): the order could not be placed
            outcome = simulate_trade(plan, bars, days[i + 1], policy)
            cash -= reserve
            orders.append(_Order(sym, side, qty, plan, reserve, outcome, strength))

    res.open_at_end = len(positions)
    return res
