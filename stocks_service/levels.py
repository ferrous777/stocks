"""ATR-based trade levels (replaces the legacy percentage levels and their made-up ATR default)."""

from __future__ import annotations

from dataclasses import dataclass

from .strategies.indicators import atr
from .strategies.view import PointInTimeView

LEVELS_VERSION = "atr_levels@1"
# Initial multiples; they are parameters to be validated/tuned in phase 3, not established facts.
DEFAULT_PARAMS = {"atr_period": 14, "entry_atr": 0.0, "stop_atr": 2.0, "target_atr": 4.0}


class LevelsUnavailable(ValueError):
    pass


@dataclass(frozen=True)
class Levels:
    side: str
    entry_limit: float
    stop: float
    target: float
    atr: float
    risk_pct: float
    reward_pct: float
    version: str = LEVELS_VERSION


def atr_levels(view: PointInTimeView, side: str, params: dict | None = None) -> Levels:
    """Entry/stop/target from the view's last close (split-adjusted basis as of the view's date)."""
    p = {**DEFAULT_PARAMS, **(params or {})}
    if side not in ("long", "short"):
        raise ValueError(f"side must be long or short, got {side!r}")
    if len(view) < p["atr_period"] + 1:
        raise LevelsUnavailable(f"{view.symbol}: need {p['atr_period'] + 1} bars for ATR, have {len(view)}")
    a = atr(view.h, view.l, view.c, p["atr_period"])
    if not a > 0:
        raise LevelsUnavailable(f"{view.symbol}: ATR is {a}; cannot set levels")
    close = float(view.c[-1])
    sign = 1 if side == "long" else -1
    entry = close - sign * p["entry_atr"] * a
    stop = entry - sign * p["stop_atr"] * a
    target = entry + sign * p["target_atr"] * a
    if min(entry, stop, target) <= 0:
        raise LevelsUnavailable(f"{view.symbol}: levels not positive (entry={entry}, stop={stop}, target={target})")
    return Levels(side, entry, stop, target, a, abs(entry - stop) / entry, abs(target - entry) / entry)
