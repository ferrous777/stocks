"""Price-basis normalization.

Yahoo's chart API does not return as-traded ("raw") prices: its OHLC are adjusted
for every split known at fetch time. Verified empirically per interval:

* ``1d``: prices and volumes are split-adjusted.
* ``1h``: prices are split-adjusted, volumes are raw.

Bars are stored on the raw basis so that orders, stops and fills use the prices
that actually traded. Signal/indicator code reads a point-in-time adjusted view
derived from raw bars plus corporate actions known as of the cutoff.
"""

from __future__ import annotations

import datetime as dt
import math
import statistics
from dataclasses import dataclass
from enum import Enum


class Basis(str, Enum):
    RAW = "raw"
    SPLIT_ADJUSTED = "split_adjusted"


@dataclass(frozen=True)
class Split:
    ex_date: dt.date
    ratio: float  # new shares per old share (numerator / denominator), e.g. 10.0 for 10:1

    def __post_init__(self) -> None:
        if not (self.ratio > 0 and math.isfinite(self.ratio)):
            raise ValueError(f"invalid split ratio {self.ratio!r}")


def split_factor_after(session: dt.date, splits: list[Split], *, through: dt.date | None = None) -> float:
    """Product of ratios of splits with ex_date in (session, through]."""
    f = 1.0
    for s in splits:
        if s.ex_date > session and (through is None or s.ex_date <= through):
            f *= s.ratio
    return f


PRICE_FIELDS = ("o", "h", "l", "c")


def to_raw(bar: dict, splits: list[Split], *, price_basis: Basis, volume_basis: Basis) -> dict:
    """Convert a source bar (fields o,h,l,c,v and ``session`` date) to the raw basis.

    The source's adjustment reflects all splits known when it was fetched, so ``splits``
    must contain every split with an ex_date after the bar's session up to fetch time.
    """
    f = split_factor_after(bar["session"], splits)
    out = dict(bar)
    if price_basis is Basis.SPLIT_ADJUSTED:
        for k in PRICE_FIELDS:
            out[k] = bar[k] * f
    if volume_basis is Basis.SPLIT_ADJUSTED and bar.get("v") is not None:
        out["v"] = bar["v"] / f
    out["split_factor_applied"] = f
    return out


def to_split_adjusted(bar: dict, splits: list[Split], *, asof: dt.date) -> dict:
    """Point-in-time split-adjusted view of a raw bar, using only splits with ex_date <= asof."""
    f = split_factor_after(bar["session"], splits, through=asof)
    out = dict(bar)
    for k in PRICE_FIELDS:
        out[k] = bar[k] / f
    if bar.get("v") is not None:
        out["v"] = bar["v"] * f
    return out


class BasisInconclusive(ValueError):
    """The data around a split did not clearly indicate either basis."""


def classify_across_split(pre: list[float], post: list[float], ratio: float, *, kind: str) -> Basis:
    """Decide whether a series is raw or split-adjusted from values around a split.

    For prices: compare the last pre-split value to the first post-split value.
    For volumes: compare medians of the pre and post windows (volumes are noisy).
    A raw series shows a jump of ~``ratio`` (prices fall by it, volumes rise by it);
    an adjusted series shows no systematic jump. The observed log change must be
    clearly closer to one hypothesis (within a third of log(ratio)) or this raises.
    """
    if ratio <= 1.0:
        raise ValueError("classification needs a forward split (ratio > 1)")
    if not pre or not post:
        raise BasisInconclusive(f"{kind}: need values on both sides of the split")
    if kind == "price":
        observed = math.log(pre[-1] / post[0])  # raw price falls by ~ratio
    elif kind == "volume":
        pre_m, post_m = statistics.median(pre), statistics.median(post)
        if pre_m <= 0 or post_m <= 0:
            raise BasisInconclusive("volume: non-positive median")
        observed = math.log(post_m / pre_m)  # raw volume rises by ~ratio
    else:
        raise ValueError(f"unknown kind {kind!r}")
    log_ratio = math.log(ratio)
    margin = log_ratio / 3
    d_adjusted = abs(observed)
    d_raw = abs(observed - log_ratio)
    if d_adjusted <= margin and d_adjusted < d_raw:
        return Basis.SPLIT_ADJUSTED
    if d_raw <= margin and d_raw < d_adjusted:
        return Basis.RAW
    raise BasisInconclusive(
        f"{kind}: observed log change {observed:.3f} is not clearly 0 (adjusted) or {log_ratio:.3f} (raw)"
    )
