"""Point-in-time market view: the only data a strategy may see.

A view for ``asof`` contains daily bars with session <= asof, split-adjusted using
only splits with ex_date <= asof. Later bars and later splits cannot influence it,
so a decision made for ``asof`` is identical whether computed live that evening or
replayed years later.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import numpy as np

from ..price_basis import Split, split_factor_after


class CutoffViolation(LookupError):
    """Raised when code asks a view for data after its as-of date."""


def _ro(values: list[float | None]) -> np.ndarray:
    arr = np.asarray([np.nan if x is None else x for x in values], dtype=float)
    arr.setflags(write=False)
    return arr


@dataclass(frozen=True)
class PointInTimeView:
    symbol: str
    asof: dt.date
    sessions: tuple[dt.date, ...]
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    v: np.ndarray  # NaN where the source had no volume (missing is not zero)
    # Raw inputs, kept so a truncated view can be rebuilt on its own cutoff's adjustment basis.
    _raw: tuple = field(default=(), repr=False, compare=False)
    _splits: tuple = field(default=(), repr=False, compare=False)

    @classmethod
    def from_raw(cls, symbol: str, raw_bars: list[dict], splits: list[Split], asof: dt.date) -> PointInTimeView:
        """Build from raw (as-traded) daily bars: dicts with session (date), o, h, l, c, v."""
        known = [s for s in splits if s.ex_date <= asof]
        rows = sorted((b for b in raw_bars if b["session"] <= asof), key=lambda b: b["session"])
        sessions = tuple(b["session"] for b in rows)
        if len(set(sessions)) != len(sessions):
            raise ValueError(f"{symbol}: duplicate sessions in bar data")
        f = [split_factor_after(b["session"], known) for b in rows]
        return cls(
            symbol=symbol,
            asof=asof,
            sessions=sessions,
            o=_ro([b["o"] / k for b, k in zip(rows, f)]),
            h=_ro([b["h"] / k for b, k in zip(rows, f)]),
            l=_ro([b["l"] / k for b, k in zip(rows, f)]),
            c=_ro([b["c"] / k for b, k in zip(rows, f)]),
            v=_ro([None if b.get("v") is None else b["v"] * k for b, k in zip(rows, f)]),
            _raw=tuple(rows),
            _splits=tuple(splits),
        )

    def __len__(self) -> int:
        return len(self.sessions)

    @property
    def last_session(self) -> dt.date | None:
        return self.sessions[-1] if self.sessions else None

    def index_of(self, session: dt.date) -> int:
        if session > self.asof:
            raise CutoffViolation(f"{self.symbol}: {session} is after the view's as-of date {self.asof}")
        try:
            return self.sessions.index(session)
        except ValueError:
            raise KeyError(f"{self.symbol}: no bar for {session}") from None

    def truncated(self, asof: dt.date) -> PointInTimeView:
        """The view as it would have been built at an earlier cutoff.

        Rebuilt from the raw bars, so splits after ``asof`` are not applied (same result as
        ``from_raw`` with data up to ``asof``).
        """
        if asof > self.asof:
            raise CutoffViolation(f"cannot extend a view from {self.asof} to {asof}")
        return PointInTimeView.from_raw(self.symbol, list(self._raw), list(self._splits), asof)
