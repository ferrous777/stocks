"""Pure ledger core: holdings and cash of an account as of a time, from its recorded history.

History items, applied in time order:
* ``LedgerEvent`` — non-trade changes: opening balances, transfers, manual adjustments
  (a position change with its cost basis, or a cash amount when ``symbol`` is None).
* ``Execution`` — confirmed fills: buy / sell / short / cover.
* Splits — applied at the ex-date session open (quantity x ratio, cost basis unchanged).

Positions are signed (short < 0) with an average-cost basis; reducing a position realizes
P&L against that average. Fees reduce cash and are reported separately, never folded into
realized P&L. Nothing here touches the database, so backtests, tests and the API share it.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field

from .. import sessions

QTY_TOL = 1e-6
CASH_TOL = 0.005
SIDES = {"buy": 1, "cover": 1, "sell": -1, "short": -1}


@dataclass(frozen=True)
class LedgerEvent:
    ts: dt.datetime
    kind: str               # opening_balance | transfer_in | transfer_out | manual_adjustment
    symbol: str | None      # None => cash
    qty: float = 0.0        # signed position change (short < 0)
    cost_basis: float = 0.0  # total cost of shares added (qty * price paid; negative for shorts). Shares
                             # removed leave at the current average cost, so it is ignored for them.
    amount: float = 0.0     # cash change when symbol is None


@dataclass(frozen=True)
class Execution:
    ts: dt.datetime
    symbol: str
    side: str     # buy | sell | short | cover
    qty: float    # positive share count
    price: float
    fees: float = 0.0

    def __post_init__(self) -> None:
        if self.side not in SIDES:
            raise ValueError(f"side must be one of {sorted(SIDES)}, got {self.side!r}")
        if not all(math.isfinite(v) for v in (self.qty, self.price, self.fees)):
            raise ValueError("qty, price and fees must be finite numbers")
        if not self.qty > 0 or not self.price > 0 or self.fees < 0:
            raise ValueError("qty and price must be positive and fees non-negative")


@dataclass
class Holding:
    qty: float = 0.0
    basis: float = 0.0       # signed: qty * average cost
    realized: float = 0.0
    fees: float = 0.0

    @property
    def avg_cost(self) -> float | None:
        return self.basis / self.qty if abs(self.qty) > QTY_TOL else None


@dataclass
class LedgerState:
    as_of: dt.datetime
    cash: float = 0.0
    holdings: dict[str, Holding] = field(default_factory=dict)

    def qty(self, symbol: str) -> float:
        h = self.holdings.get(symbol)
        return h.qty if h else 0.0

    def open_positions(self) -> dict[str, Holding]:
        return {s: h for s, h in self.holdings.items() if abs(h.qty) > QTY_TOL}


def _trade(h: Holding, d: float, price: float) -> None:
    """Apply a signed quantity change ``d`` at ``price`` with average-cost accounting."""
    if abs(h.qty) <= QTY_TOL or (h.qty > 0) == (d > 0):
        h.qty += d
        h.basis += d * price
        return
    close = -h.qty if abs(d) >= abs(h.qty) else d   # part of d that reduces the position
    avg = h.basis / h.qty
    h.realized += -close * (price - avg)
    h.qty += close
    h.basis = avg * h.qty
    rest = d - close
    if abs(rest) > QTY_TOL:                          # flipped through zero: open the other side
        h.qty, h.basis = rest, rest * price


def split_time(ex_date: dt.date) -> dt.datetime:
    """When a split takes effect: the open of its ex-date, or of the first session after it when the
    source dates it on a day the exchange was closed (Yahoo dates NVDA's 2001 2:1 split 2001-09-12,
    when NYSE was shut after 9/11). Range checks elsewhere (``ex_date <= session``) agree with this."""
    effective = ex_date if sessions.is_session(ex_date) else sessions.next_session(ex_date)
    return sessions.session_bounds(effective)[0]


def state_as_of(as_of: dt.datetime, events: list[LedgerEvent], executions: list[Execution],
                splits: dict[str, list[tuple[dt.date, float]]]) -> LedgerState:
    """Holdings and cash including every item with ts <= ``as_of``."""
    items: list[tuple[dt.datetime, int, object]] = []
    for e in events:
        if e.ts <= as_of:
            # Opening balances precede fills at the same instant; break resolutions are computed from a
            # snapshot state that already includes same-time fills, so they replay after them.
            items.append((e.ts, 1 if e.kind == "opening_balance" else 3, e))
    for x in executions:
        if x.ts <= as_of:
            items.append((x.ts, 2, x))
    for sym, ss in splits.items():
        for ex_date, ratio in ss:
            t = split_time(ex_date)
            if t <= as_of:
                items.append((t, 0, (sym, ratio)))   # before anything else at the same instant
    items.sort(key=lambda it: (it[0], it[1]))
    st = LedgerState(as_of)
    for _, kind, it in items:
        if kind == 0:
            sym, ratio = it
            h = st.holdings.get(sym)
            if h:
                h.qty *= ratio
        elif kind in (1, 3):
            if it.symbol is None:
                st.cash += it.amount
            else:
                h = st.holdings.setdefault(it.symbol, Holding())
                reducing = abs(h.qty) > QTY_TOL and (h.qty > 0) != (it.qty > 0)
                if reducing and abs(it.qty) <= abs(h.qty) + QTY_TOL:
                    avg = h.basis / h.qty       # shares leaving at average cost: no realized P&L
                    h.qty += it.qty
                    h.basis = avg * h.qty if abs(h.qty) > QTY_TOL else 0.0
                else:
                    h.qty += it.qty
                    h.basis += it.cost_basis
        else:
            h = st.holdings.setdefault(it.symbol, Holding())
            sign = SIDES[it.side]
            _trade(h, sign * it.qty, it.price)
            st.cash += -sign * it.qty * it.price - it.fees
            h.fees += it.fees
    return st


@dataclass(frozen=True)
class Difference:
    symbol: str          # "$CASH" for cash
    expected: float
    reported: float

    @property
    def diff(self) -> float:
        return self.reported - self.expected


CASH = "$CASH"


def reconcile(state: LedgerState, reported_cash: float, reported_positions: dict[str, float]) -> list[Difference]:
    """Differences between the ledger and a broker snapshot (never turned into trades)."""
    out = []
    for sym in sorted(set(state.open_positions()) | set(reported_positions)):
        exp, rep = state.qty(sym), reported_positions.get(sym, 0.0)
        if abs(rep - exp) > QTY_TOL:
            out.append(Difference(sym, exp, rep))
    if abs(reported_cash - state.cash) > CASH_TOL:
        out.append(Difference(CASH, state.cash, reported_cash))
    return out
