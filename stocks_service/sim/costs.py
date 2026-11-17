"""Explicit, versioned trading-cost profiles and gross -> net conversion.

Every field must be set; there are no hidden defaults. Spread and slippage are
*assumptions* (Yahoo has no historical quotes) and are labelled as such in reports.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from .execution import Outcome, Side


@dataclass(frozen=True)
class CostProfile:
    profile_id: str
    version: int
    commission_per_share: float
    min_commission: float
    half_spread_bps: float  # assumption: paid on entry and exit
    slippage_bps: float     # assumption: paid on entry and exit
    borrow_rate_annual: float | None  # None => shorting not allowed under this profile

    @property
    def key(self) -> str:
        return f"{self.profile_id}@{self.version}"

    def scaled(self, factor: float, suffix: str) -> CostProfile:
        """Stress variant: all cost rates multiplied by ``factor`` (used for 2x/3x cost tests)."""
        return CostProfile(f"{self.profile_id}{suffix}", self.version, self.commission_per_share * factor,
                           self.min_commission * factor, self.half_spread_bps * factor, self.slippage_bps * factor,
                           None if self.borrow_rate_annual is None else self.borrow_rate_annual * factor)


@dataclass(frozen=True)
class NetResult:
    gross_return: float
    net_return: float
    cost_return: float
    commission: float
    spread_slippage: float
    borrow: float
    dividends: float  # positive = received (long), negative = paid (short)


def _commission(profile: CostProfile, qty: float) -> float:
    return max(profile.min_commission, profile.commission_per_share * qty) if qty > 0 else 0.0


def net_trade(outcome: Outcome, side: Side, qty: float, profile: CostProfile,
              dividends: list[tuple[dt.date, float]] = ()) -> NetResult | None:
    """Net result of one simulated trade for ``qty`` shares.

    ``dividends``: (ex_date, raw amount per share). A long receives dividends with ex_date in
    (fill_session, exit_session]; a short pays them. Returns None for unresolved trades.
    """
    if outcome.result == "unresolved":
        return None
    if outcome.result == "not_filled":
        return NetResult(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    if side == "short" and profile.borrow_rate_annual is None:
        raise ValueError(f"cost profile {profile.key} does not allow shorts (no borrow rate)")
    entry, exit_ = outcome.fill_price, outcome.exit_price
    notional = entry * qty
    sign = 1 if side == "long" else -1
    gross_pnl = sign * (exit_ - entry) * qty
    friction_bps = profile.half_spread_bps + profile.slippage_bps
    spread_slip = (entry + exit_) * qty * friction_bps / 10_000
    commission = _commission(profile, qty) * 2
    borrow = 0.0
    if side == "short":
        days = (outcome.exit_session - outcome.fill_session).days
        borrow = notional * profile.borrow_rate_annual * days / 360
    div = sum(a for d, a in dividends if outcome.fill_session < d <= outcome.exit_session) * qty * sign
    net_pnl = gross_pnl - spread_slip - commission - borrow + div
    return NetResult(gross_pnl / notional, net_pnl / notional, (spread_slip + commission + borrow) / notional,
                     commission, spread_slip, borrow, div)
