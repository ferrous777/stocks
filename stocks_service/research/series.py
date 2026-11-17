"""Fast point-in-time access to one symbol's daily history for backtests.

A symbol's point-in-time price basis only changes on split ex-dates, so adjusted arrays are
precomputed once per "split era" and sliced per day. ``view_at`` returns exactly what
``PointInTimeView.from_raw`` (and therefore ``run_decision``) builds from the same raw bars,
including the 400-bar lookback window, so backtest decisions equal live decisions.
"""

from __future__ import annotations

import bisect
import datetime as dt
from dataclasses import dataclass

import numpy as np

from ..price_basis import Split, split_factor_after
from ..sim import Bar
from ..strategies.runner import LOOKBACK_BARS
from ..strategies.view import PointInTimeView


def _ro(a: np.ndarray) -> np.ndarray:
    a.setflags(write=False)
    return a


@dataclass
class SymbolSeries:
    symbol: str
    sessions: list[dt.date]
    raw: list[dict]  # session, o, h, l, c, v (raw basis), ascending
    splits: list[Split]
    dividends: list[tuple[dt.date, float]]  # (ex_date, raw amount per share)

    def __post_init__(self) -> None:
        self.splits = sorted(self.splits, key=lambda s: s.ex_date)
        self._split_dates = [s.ex_date for s in self.splits]
        self._eras: dict[int, dict[str, np.ndarray]] = {}

    @classmethod
    def from_db(cls, db, symbol: str) -> SymbolSeries:
        from ..ingestion import load_splits
        docs = db.bars.find({"symbol": symbol, "interval": "1d"},
                            {"session": 1, "o": 1, "h": 1, "l": 1, "c": 1, "v": 1}).sort("session", 1)
        raw = [{"session": d["session"].date(), "o": d["o"], "h": d["h"], "l": d["l"], "c": d["c"], "v": d.get("v")}
               for d in docs]
        divs = [(d["ex_date"].date(), d["amount_raw"]) for d in
                db.corporate_actions.find({"symbol": symbol, "type": "dividend"}).sort("ex_date", 1)]
        return cls(symbol, [b["session"] for b in raw], raw, load_splits(db, symbol), divs)

    # --- views ------------------------------------------------------------------

    def _era(self, asof: dt.date) -> tuple[int, dict[str, np.ndarray]]:
        k = bisect.bisect_right(self._split_dates, asof)  # number of splits known at asof
        if k not in self._eras:
            known = self.splits[:k]
            f = [split_factor_after(b["session"], known) for b in self.raw]
            self._eras[k] = {
                "o": _ro(np.array([b["o"] / x for b, x in zip(self.raw, f)], dtype=float)),
                "h": _ro(np.array([b["h"] / x for b, x in zip(self.raw, f)], dtype=float)),
                "l": _ro(np.array([b["l"] / x for b, x in zip(self.raw, f)], dtype=float)),
                "c": _ro(np.array([b["c"] / x for b, x in zip(self.raw, f)], dtype=float)),
                "v": _ro(np.array([np.nan if b.get("v") is None else b["v"] * x for b, x in zip(self.raw, f)],
                                  dtype=float)),
            }
        return k, self._eras[k]

    def count_through(self, asof: dt.date) -> int:
        return bisect.bisect_right(self.sessions, asof)

    def view_at(self, asof: dt.date, lookback: int = LOOKBACK_BARS) -> PointInTimeView:
        n = self.count_through(asof)
        lo = max(0, n - lookback)
        _, a = self._era(asof)
        return PointInTimeView(self.symbol, asof, tuple(self.sessions[lo:n]),
                               a["o"][lo:n], a["h"][lo:n], a["l"][lo:n], a["c"][lo:n], a["v"][lo:n])

    # --- execution-side access (decision-date basis) ------------------------------

    def _factor_since(self, decided: dt.date, session: dt.date) -> float:
        f = 1.0
        for s in self.splits:
            if decided < s.ex_date <= session:
                f *= s.ratio
        return f

    def bars_after(self, decided: dt.date, max_bars: int) -> list[Bar]:
        i = self.count_through(decided)
        out = []
        for b in self.raw[i:i + max_bars]:
            f = self._factor_since(decided, b["session"])
            out.append(Bar(b["session"], b["o"] * f, b["h"] * f, b["l"] * f, b["c"] * f))
        return out

    def close_on_basis(self, decided: dt.date, session: dt.date) -> float | None:
        """Close at the last bar on or before ``session``, expressed on ``decided``'s basis."""
        i = self.count_through(session)
        if i == 0:
            return None
        b = self.raw[i - 1]
        return b["c"] * self._factor_since(decided, b["session"])

    def dividends_on_basis(self, decided: dt.date) -> list[tuple[dt.date, float]]:
        """Dividends after ``decided`` per decision-basis share."""
        return [(d, a * self._factor_since(decided, d)) for d, a in self.dividends if d > decided]
