"""Single-trade execution simulator for the validated daily policy (``exec_daily_v1``).

Shared by backtests, calibration labels and the paper broker so they cannot disagree.
All prices are raw (as traded); callers pass bars on one consistent basis.

Rules (plan §1, §F):
* A plan created at the close of session d may only fill on session d+1's bar.
* Long entry (short mirrored): open <= limit fills at the open; otherwise the low must trade
  strictly through the limit (low < limit) and fills at the limit; otherwise not filled.
* Entry gap through the stop (open already beyond the stop): policy ``fill_and_exit`` fills
  and exits at that open (outcome ``gap_stop``); policy ``cancel`` leaves it unfilled.
* Fill bar: the target is never credited; if the bar's range reaches the stop after the
  fill, the trade stops at the stop price and is flagged ambiguous.
* Later bars: a gap through the stop or target exits at the open; a bar spanning both
  stop and target assumes the stop (flagged ambiguous).
* Timeout: triggered at the close of the N-th session after the fill session; exits at the
  next session's open.
* Running out of bars before resolution returns ``unresolved`` — never an invented exit.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Literal

Side = Literal["long", "short"]
Result = Literal["target", "stop", "gap_stop", "timeout", "not_filled", "unresolved"]


@dataclass(frozen=True)
class ExecutionPolicy:
    id: str = "exec_daily_v1"
    version: int = 1
    gap_through_stop: Literal["fill_and_exit", "cancel"] = "fill_and_exit"
    timeout_sessions: int = 126

    @property
    def key(self) -> str:
        return f"{self.id}@{self.version}"


DEFAULT_POLICY = ExecutionPolicy()


@dataclass(frozen=True)
class Bar:
    session: dt.date
    o: float
    h: float
    l: float
    c: float


@dataclass(frozen=True)
class TradePlan:
    side: Side
    decided: dt.date  # session whose close produced the plan
    entry_limit: float
    stop: float
    target: float

    def __post_init__(self) -> None:
        if self.side == "long" and not (self.stop < self.entry_limit < self.target):
            raise ValueError(f"long plan needs stop < entry < target: {self}")
        if self.side == "short" and not (self.target < self.entry_limit < self.stop):
            raise ValueError(f"short plan needs target < entry < stop: {self}")


@dataclass(frozen=True)
class Outcome:
    result: Result
    fill_session: dt.date | None = None
    fill_price: float | None = None
    exit_session: dt.date | None = None
    exit_price: float | None = None
    sessions_held: int | None = None  # sessions from fill session to exit session
    ambiguous: bool = False
    gap_fill: bool = False
    note: str = ""

    @property
    def resolved(self) -> bool:
        return self.result != "unresolved"


def _gross(side: Side, entry: float, exit_: float) -> float:
    return exit_ / entry - 1 if side == "long" else entry / exit_ - 1


def gross_return(o: Outcome, side: Side) -> float | None:
    if o.fill_price is None or o.exit_price is None:
        return None if o.result != "not_filled" else 0.0
    return _gross(side, o.fill_price, o.exit_price)


def simulate_trade(plan: TradePlan, bars: list[Bar], next_session: dt.date,
                   policy: ExecutionPolicy = DEFAULT_POLICY) -> Outcome:
    """Simulate ``plan`` over ``bars`` (sessions strictly after ``plan.decided``, ascending).

    ``next_session`` is the calendar session after ``plan.decided``; the first bar must be
    that session (a missing bar is a data gap and raises, rather than silently skipping).
    """
    if not bars:
        return Outcome("unresolved", note="no bars after decision")
    if bars[0].session != next_session:
        raise ValueError(f"first bar {bars[0].session} is not the eligible session {next_session}")
    long = plan.side == "long"

    def beyond_stop(price: float) -> bool:
        return price <= plan.stop if long else price >= plan.stop

    def beyond_target(price: float) -> bool:
        return price >= plan.target if long else price <= plan.target

    b0 = bars[0]
    # --- entry -----------------------------------------------------------------
    if (b0.o <= plan.entry_limit) if long else (b0.o >= plan.entry_limit):
        fill, gap_fill = b0.o, True
    elif (b0.l < plan.entry_limit) if long else (b0.h > plan.entry_limit):
        fill, gap_fill = plan.entry_limit, False
    else:
        return Outcome("not_filled", note="limit not traded through")

    if gap_fill and beyond_stop(b0.o):
        if policy.gap_through_stop == "cancel":
            return Outcome("not_filled", note="gap_through_stop_cancelled")
        return Outcome("gap_stop", b0.session, fill, b0.session, b0.o, 0, gap_fill=True, note="gap_through_stop")

    # Fill bar: target not credited; stop is assumed hit if the range reached it after the fill.
    if beyond_stop(b0.l if long else b0.h):
        return Outcome("stop", b0.session, fill, b0.session, plan.stop, 0, ambiguous=True, gap_fill=gap_fill,
                       note="stop within fill bar")

    # --- holding ---------------------------------------------------------------
    timeout_exit_pending = False
    for k, b in enumerate(bars[1:], start=1):
        if timeout_exit_pending:
            return Outcome("timeout", b0.session, fill, b.session, b.o, k, gap_fill=gap_fill)
        if beyond_stop(b.o):
            return Outcome("gap_stop", b0.session, fill, b.session, b.o, k, gap_fill=gap_fill, note="gap through stop")
        if beyond_target(b.o):
            return Outcome("target", b0.session, fill, b.session, b.o, k, gap_fill=gap_fill, note="gap through target")
        hit_stop = beyond_stop(b.l if long else b.h)
        hit_target = beyond_target(b.h if long else b.l)
        if hit_stop:
            return Outcome("stop", b0.session, fill, b.session, plan.stop, k, ambiguous=hit_target, gap_fill=gap_fill)
        if hit_target:
            return Outcome("target", b0.session, fill, b.session, plan.target, k, gap_fill=gap_fill)
        if k >= policy.timeout_sessions:
            timeout_exit_pending = True  # decided at this close; executes at the next open
    return Outcome("unresolved", b0.session, fill, gap_fill=gap_fill, note="bars ended before resolution")


def bars_on_decision_basis(raw_bars: list[dict], splits, decided: dt.date) -> list[Bar]:
    """Bars after ``decided`` expressed on the decision date's price basis.

    Plans are priced from a point-in-time view at ``decided``. A split after that date makes
    raw prices drop by the ratio, which would look like a gap through any long stop; scaling
    later bars by the splits with decided < ex_date <= bar session keeps one consistent basis
    (returns are unchanged). Share quantities scale inversely; callers sizing in shares use
    the decision-date quantity.
    """
    out = []
    for b in sorted((b for b in raw_bars if b["session"] > decided), key=lambda b: b["session"]):
        f = 1.0
        for s in splits:
            if decided < s.ex_date <= b["session"]:
                f *= s.ratio
        out.append(Bar(b["session"], b["o"] * f, b["h"] * f, b["l"] * f, b["c"] * f))
    return out
