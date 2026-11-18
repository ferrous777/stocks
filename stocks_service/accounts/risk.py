"""Risk profiles, correlated clusters and order-ticket sizing for real accounts (plan §E, §F).

Activation gate: tickets (and suggested quantities) are produced only for outlook rows backed by an
``active`` strategy version (grade A). Every other row is informational and says why it has no
ticket. Sizing is the minimum of:

* risk per trade: loss at the stop **plus a gap-stress move** (``gap_stress_atr`` x ATR) <= R% of equity;
* position cap: notional <= P% of equity;
* cluster cap: |exposure| of the symbol's correlated cluster (explicit groups + 252-day return
  correlation >= threshold) <= C% of equity, counting holdings and tickets already sized;
* portfolio heat: total loss-at-stop incl. gap stress of protected holdings + tickets <= H% of equity;
* gross exposure <= G x equity; short exposure <= S% of equity;
* cash: a long's notional <= free cash (no margin for real accounts);
* liquidity: 20-day average dollar volume >= a floor, and qty <= x% of it.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np

from ..research.series import SymbolSeries


@dataclass(frozen=True)
class RiskProfile:
    profile_id: str
    version: int
    risk_per_trade: float      # fraction of equity lost at the stop incl. gap stress
    max_position_pct: float
    max_cluster_pct: float
    max_heat_pct: float
    gap_stress_atr: float
    max_gross: float           # gross exposure / equity
    max_short_pct: float
    corr_threshold: float      # 252-day correlation that puts two symbols in one cluster
    min_adv_usd: float
    max_adv_pct: float

    @property
    def key(self) -> str:
        return f"{self.profile_id}@{self.version}"

    @classmethod
    def from_doc(cls, d: dict) -> RiskProfile:
        return cls(**{k: d[k] for k in cls.__dataclass_fields__})

    def as_dict(self) -> dict:
        return asdict(self)


def correlation_clusters(series: dict[str, SymbolSeries], symbols: list[str], asof, threshold: float,
                         window: int = 252) -> dict[str, int]:
    """Single-linkage clusters of daily log returns over the last ``window`` sessions up to ``asof``."""
    rets = {}
    for s in symbols:
        v = series[s].view_at(asof, lookback=window + 1)
        if len(v) == window + 1 and v.sessions[-1] == asof:
            rets[s] = np.diff(np.log(np.asarray(v.c, dtype=float)))
    names = sorted(rets)
    parent = {s: s for s in names}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    if len(names) > 1:
        corr = np.corrcoef(np.vstack([rets[s] for s in names]))
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                if corr[i, j] >= threshold:
                    parent[find(names[i])] = find(names[j])
    roots = sorted({find(s) for s in names})
    return {s: roots.index(find(s)) for s in names}


def cluster_keys(symbol: str, groups: dict[str, list[str]], corr_cluster: dict[str, int]) -> set[str]:
    keys = {f"group:{g}" for g in groups.get(symbol, [])}
    if symbol in corr_cluster:
        keys.add(f"corr:{corr_cluster[symbol]}")
    return keys


def avg_dollar_volume(series: SymbolSeries, asof, n: int = 20) -> float | None:
    v = series.view_at(asof, lookback=n)
    vol = np.asarray(v.v, dtype=float)
    if len(v) < n or np.isnan(vol).any():
        return None
    return float(np.mean(np.asarray(v.c, dtype=float) * vol))


@dataclass
class Book:
    """Exposure already committed: current holdings plus tickets sized earlier in the ranking."""
    equity: float
    cash: float
    gross: float = 0.0
    short: float = 0.0
    heat: float = 0.0
    clusters: dict | None = None

    def __post_init__(self):
        self.clusters = self.clusters or {}


def size_ticket(row: dict, book: Book, profile: RiskProfile, *, keys: set[str], adv_usd: float | None,
                shortable: bool) -> tuple[int, list[str], dict]:
    """Shares for one ticket and the binding constraints. Updates ``book`` when qty > 0."""
    plan = row["plan"]
    entry, stop, atr = plan["entry_limit"], plan["stop"], plan["atr"]
    side = row["side"]
    reasons: list[str] = []
    if side == "short" and not shortable:
        return 0, ["symbol is not marked shortable"], {}
    if adv_usd is None or adv_usd < profile.min_adv_usd:
        return 0, [f"average dollar volume {adv_usd or 0:,.0f} below the {profile.min_adv_usd:,.0f} floor"], {}
    loss_ps = abs(entry - stop) + profile.gap_stress_atr * atr
    e = book.equity
    limits = {
        "risk_per_trade": e * profile.risk_per_trade / loss_ps,
        "position_cap": e * profile.max_position_pct / entry,
        "heat_cap": max(0.0, e * profile.max_heat_pct - book.heat) / loss_ps,
        "gross_cap": max(0.0, e * profile.max_gross - book.gross) / entry,
        "liquidity": adv_usd * profile.max_adv_pct / entry,
    }
    for k in keys:
        limits[f"cluster_cap({k})"] = max(0.0, e * profile.max_cluster_pct - book.clusters.get(k, 0.0)) / entry
    if side == "long":
        limits["cash"] = max(0.0, book.cash) / entry
    else:
        limits["short_cap"] = max(0.0, e * profile.max_short_pct - book.short) / entry
    binding = min(limits, key=limits.get)
    qty = int(math.floor(limits[binding] + 1e-9))
    if qty < 1:
        return 0, [f"no room under {binding}"], limits
    notional = qty * entry
    book.gross += notional
    book.heat += qty * loss_ps
    if side == "long":
        book.cash -= notional
    else:
        book.short += notional
    for k in keys:
        book.clusters[k] = book.clusters.get(k, 0.0) + notional
    reasons.append(f"sized by {binding}")
    return qty, reasons, limits
