"""Portfolio backtest of a strategy under the reproducible ``baseline_v1`` selection policy.

Daily loop over XNYS sessions. At each close d:
  1. settle exits whose exit session is d and fills/expiries of orders placed at d-1;
  2. mark the portfolio to market (on each trade's decision-date price basis);
  3. accrue the 13-week T-bill rate (^IRX, known at d) on free cash;
  4. decide with only data <= d (``SymbolSeries.view_at``), rank candidates, size them and
     place limit orders for d+1, reserving cash.

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
from ..sim import CostProfile, ExecutionPolicy, TradePlan, net_trade, simulate_trade
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
    notional: float


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


def _irx_rate(irx: SymbolSeries, d: dt.date) -> float:
    i = irx.count_through(d)
    if i == 0:
        raise ValueError(f"no ^IRX observation on or before {d}; cannot accrue cash interest")
    return irx.raw[i - 1]["c"] / 100.0


def run_backtest(universe: dict[str, SymbolSeries], tradable: list[str], irx: SymbolSeries, strategy_key: str,
                 start: dt.date, end: dt.date, cost: CostProfile, policy: ExecutionPolicy = ExecutionPolicy(),
                 params: PolicyParams = PolicyParams(), initial: float = 100_000.0) -> BacktestResult:
    spec = get_spec(strategy_key)
    days = sessions.sessions_between(start, end)
    res = BacktestResult(strategy_key, POLICY_ID, cost.key, policy.key, days[0], days[-1], initial)
    cash = initial
    orders: list[_Order] = []
    positions: list[_Position] = []
    allow_short = params.allow_short and cost.borrow_rate_annual is not None
    horizon_bars = policy.timeout_sessions + 3

    for i, d in enumerate(days):
        # 1) fills / expiries for orders placed at the previous close
        still = []
        for o in orders:
            oc = o.outcome
            if oc.fill_session is not None and oc.fill_session == d:
                cash += o.reserved
                notional = oc.fill_price * o.qty
                cash -= notional
                positions.append(_Position(o, notional))
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
                series = universe[p.order.symbol]
                nt = net_trade(oc, p.order.side, p.order.qty, cost, series.dividends_on_basis(p.order.plan.decided))
                cash += p.notional * (1 + nt.net_return)
                res.traded_notional += oc.exit_price * p.order.qty
                res.trades.append(Trade(p.order.symbol, p.order.side, p.order.plan.decided, oc.fill_session,
                                        oc.exit_session, oc.result, p.order.qty, oc.fill_price, oc.exit_price,
                                        nt.net_return, nt.gross_return, oc.sessions_held, oc.ambiguous))
            else:
                remaining.append(p)
        positions = remaining

        # 2) mark to market
        invested = 0.0
        value = cash + sum(o.reserved for o in orders)
        for p in positions:
            series = universe[p.order.symbol]
            mark = series.close_on_basis(p.order.plan.decided, d)
            sign = 1 if p.order.side == "long" else -1
            value += p.notional + sign * (mark - p.order.outcome.fill_price) * p.order.qty
            invested += p.notional
        res.dates.append(d)
        res.equity.append(value)
        res.exposure.append(invested / value if value > 0 else 0.0)

        # 3) interest on free cash (overnight, rate known at d)
        if i + 1 < len(days):
            gap_days = (days[i + 1] - d).days
            cash *= 1 + _irx_rate(irx, d) * gap_days / 360

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
            reserve = qty * lv.entry_limit
            if reserve > cash:
                qty = cash / lv.entry_limit
                reserve = qty * lv.entry_limit
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
