#!/usr/bin/env python3
"""Paper-order sizing arithmetic for the trade-suggestions skill. NOT a trading signal.

It never calls a broker, never submits anything, and never fills in a missing input: every input must
come from a verified source read in the same run (the caller keeps the source links). The server's own
risk check (``place_paper_order``) still applies on top; pass its limit as ``server_max_qty`` when known.

Usage:  python3 paper_limits.py input.json        (or JSON on stdin)   -> JSON result on stdout

Input (all required unless marked optional; money in USD, prices per share):
  side                 "long" | "short"
  entry, stop, target  the server plan's entry limit, stop and target (unrounded as served)
  equity               current paper equity (verified, complete)
  free_cash            verified free cash / collateral available for a new reservation (short proceeds are NOT
                       free cash)
  open_gross           gross notional of the account's open positions plus open/reserved orders
  new_positions_this_decision   orders already placed for this completed-session decision (across reruns)
  costs                {commission_per_share, min_commission, half_spread_bps, slippage_bps,
                        borrow_rate_annual (required for shorts; null means shorting is not allowed)}
  fill_session         ISO date the DAY entry order can fill (the next session)
  time_exit_session    ISO date the server's time exit executes for that fill (open of the 127th session after
                       fill under exec_daily_v1); must be on or before fill_session + 6 calendar months
  server_max_qty       optional int, the server's stated limit for this order

Caps (fixed by the user's policy; inputs cannot change them):
  $1,000 initial notional and 1% of equity per position; 0.25% of equity planned entry-to-stop loss plus modeled
  round-trip costs; 10% aggregate experiment gross exposure; at most 2 new positions per decision.

Output: qty (0 = reject) with every reason, each cap's own limit, the binding cap, and the cost and return
figures. Planned stop loss is not maximum loss: gaps (and shorts) can lose more.
"""
from __future__ import annotations

import calendar
import datetime as dt
import json
import math
import sys

MAX_NOTIONAL = 1_000.0
MAX_POSITION_PCT = 0.01
MAX_STOP_RISK_PCT = 0.0025
MAX_GROSS_PCT = 0.10
MAX_NEW_POSITIONS = 2
TARGET_NET_RETURN = 0.15   # real tactical objective; reported for comparison only, never a paper gate

REQUIRED = ("side", "entry", "stop", "target", "equity", "free_cash", "open_gross", "new_positions_this_decision",
            "costs", "fill_session", "time_exit_session")
COST_FIELDS = ("commission_per_share", "min_commission", "half_spread_bps", "slippage_bps")


class InputError(ValueError):
    pass


def add_calendar_months(d: dt.date, months: int) -> dt.date:
    m = d.month - 1 + months
    y, m = d.year + m // 12, m % 12 + 1
    return dt.date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def _num(x, name: str, *, positive: bool = False, nonneg: bool = False) -> float:
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
        raise InputError(f"{name} must be a finite number, got {x!r}")
    if positive and x <= 0:
        raise InputError(f"{name} must be > 0")
    if nonneg and x < 0:
        raise InputError(f"{name} must be >= 0")
    return float(x)


def _commission(qty: int, c: dict) -> float:
    return max(c["min_commission"], qty * c["commission_per_share"]) if qty > 0 else 0.0


def _leg_cost(qty: int, price: float, c: dict) -> float:
    """One execution: spread + slippage on notional, plus commission."""
    return qty * price * (c["half_spread_bps"] + c["slippage_bps"]) / 10_000 + _commission(qty, c)


def _borrow(qty: int, entry: float, c: dict, side: str, days: int) -> float:
    return qty * entry * c["borrow_rate_annual"] * days / 365 if side == "short" else 0.0


def size(inp: dict) -> dict:
    missing = [k for k in REQUIRED if k not in inp or inp[k] is None]
    if missing:
        raise InputError(f"missing inputs: {', '.join(missing)}")
    side = inp["side"]
    if side not in ("long", "short"):
        raise InputError("side must be long or short")
    entry = _num(inp["entry"], "entry", positive=True)
    stop = _num(inp["stop"], "stop", positive=True)
    target = _num(inp["target"], "target", positive=True)
    equity = _num(inp["equity"], "equity", positive=True)
    free_cash = _num(inp["free_cash"], "free_cash", nonneg=True)
    open_gross = _num(inp["open_gross"], "open_gross", nonneg=True)
    placed = inp["new_positions_this_decision"]
    if not isinstance(placed, int) or isinstance(placed, bool) or placed < 0:
        raise InputError("new_positions_this_decision must be a whole number >= 0")
    raw = inp["costs"]
    if not isinstance(raw, dict):
        raise InputError("costs must be an object")
    c = {k: _num(raw.get(k), f"costs.{k}", nonneg=True) for k in COST_FIELDS}
    if side == "short":
        if raw.get("borrow_rate_annual") is None:
            raise InputError("costs.borrow_rate_annual is unknown: this cost profile cannot short")
        c["borrow_rate_annual"] = _num(raw["borrow_rate_annual"], "costs.borrow_rate_annual", nonneg=True)
    if (side == "long" and not stop < entry < target) or (side == "short" and not target < entry < stop):
        raise InputError(f"plan ordering invalid for a {side}: stop {stop}, entry {entry}, target {target}")
    try:
        fill = dt.date.fromisoformat(inp["fill_session"])
        exit_ = dt.date.fromisoformat(inp["time_exit_session"])
    except (TypeError, ValueError) as e:
        raise InputError(f"fill_session/time_exit_session must be ISO dates: {e}") from None
    if exit_ <= fill:
        raise InputError("time_exit_session must be after fill_session")
    server_max = inp.get("server_max_qty")
    if server_max is not None and (not isinstance(server_max, int) or isinstance(server_max, bool) or server_max < 0):
        raise InputError("server_max_qty must be a whole number >= 0")

    hold_days = (exit_ - fill).days
    six_months = add_calendar_months(fill, 6)
    reasons: list[str] = []
    if exit_ > six_months:
        reasons.append(f"time exit {exit_} is after six calendar months from fill ({six_months}); "
                       "no enforceable exit within the horizon")
    if placed >= MAX_NEW_POSITIONS:
        reasons.append(f"{placed} new positions already placed for this decision (max {MAX_NEW_POSITIONS})")

    stop_dist = abs(entry - stop)

    def entry_cost(q: int) -> float:
        return _leg_cost(q, entry, c)

    def stop_loss(q: int) -> float:   # planned loss at the stop incl. round trip and full-horizon borrow
        return q * stop_dist + entry_cost(q) + _leg_cost(q, stop, c) + _borrow(q, entry, c, side, hold_days)

    def largest(ok, upper: int) -> int:
        q = max(0, upper)
        while q > 0 and not ok(q):
            q -= 1
        return q

    upper = int(MAX_NOTIONAL // entry) + 1
    caps = {
        "notional_1000": int(MAX_NOTIONAL // entry),
        "position_1pct_equity": int(MAX_POSITION_PCT * equity // entry),
        "stop_risk_0.25pct_equity": largest(lambda q: stop_loss(q) <= MAX_STOP_RISK_PCT * equity, upper),
        "gross_10pct_equity": max(0, int((MAX_GROSS_PCT * equity - open_gross) // entry)),
        "free_cash": largest(lambda q: q * entry + entry_cost(q) <= free_cash, upper),
    }
    if server_max is not None:
        caps["server"] = server_max
    binding = min(caps, key=caps.get)
    qty = 0 if reasons else caps[binding]
    if not reasons and qty < 1:
        reasons.append(f"not even one share fits the {binding} cap")

    out = {"qty": qty, "accepted": qty >= 1, "reasons": reasons, "caps": caps, "binding_cap": binding,
           "six_month_deadline": six_months.isoformat(), "time_exit_session": exit_.isoformat(),
           "holding_days_max": hold_days,
           "note": "planned stop loss is not maximum loss; gaps and shorts can lose more"}
    if qty >= 1:
        exit_cost_target = _leg_cost(qty, target, c)
        borrow = _borrow(qty, entry, c, side, hold_days)
        round_trip = entry_cost(qty) + exit_cost_target + borrow
        gross_profit = qty * abs(target - entry)
        denominator = qty * entry + entry_cost(qty) if side == "long" else qty * entry
        net_return = (gross_profit - round_trip) / denominator
        out.update({
            "initial_notional": qty * entry,
            "return_denominator": denominator,
            "return_denominator_basis": ("cash deployed incl. entry costs" if side == "long"
                                         else "initial short notional"),
            "round_trip_cost_reserve": round_trip,
            "borrow_cost_full_horizon": borrow,
            "target_profit_net": gross_profit - round_trip,
            "target_return_net_if_target_hit": net_return,   # target profit, NOT an expected return
            "planned_stop_loss_incl_costs": stop_loss(qty),
            "meets_15pct_target_objective": net_return >= TARGET_NET_RETURN,
        })
    return out


def main(argv: list[str]) -> int:
    try:
        raw = open(argv[1]).read() if len(argv) > 1 else sys.stdin.read()
        print(json.dumps(size(json.loads(raw)), indent=2))
        return 0
    except (InputError, json.JSONDecodeError, OSError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
