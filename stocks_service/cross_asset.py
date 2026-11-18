"""Cross-asset layer (plan §8, phase 9): relationships between symbols and a group-consensus overlay.

* **Relationships** (daily, latest kept per pair and window): for every pair of watched symbols,
  over 60 and 252 sessions of calendar-aligned daily log returns — Pearson, Spearman, sign
  correlation (mean of sign products), the beta of ``a`` on ``b``, and the lead/lag in -5..+5
  sessions with the strongest Pearson correlation (positive lag: ``b`` leads ``a``).
* **Similar symbols**: the strongest 252-session correlations, flagging pairs that share no group
  (link candidates for you to approve; nothing is linked automatically).
* **Overlay** ``cross_asset@1``: a symbol's score = its own signed strategy strength + ``weight`` x
  the mean signed strength of the other members of its groups that day (point-in-time). It is an
  overlay version: promoted only if a paired comparison against the same strategy *without* it
  shows a significant improvement (``research.overlays``).
"""

from __future__ import annotations

import datetime as dt
import itertools

import numpy as np
from pymongo.database import Database

from . import sessions
from .research.series import SymbolSeries

WINDOWS = (60, 252)
MAX_LAG = 5


def aligned_returns(series: dict[str, SymbolSeries], symbols: list[str], asof: dt.date,
                    window: int) -> dict[str, np.ndarray]:
    """Log returns over the last ``window`` XNYS sessions to ``asof``; only symbols with every bar."""
    if sessions.session_number(asof) < window + MAX_LAG:
        return {}
    grid = tuple(sessions.session_after_n(asof, k) for k in range(-(window + MAX_LAG), 1))
    out = {}
    for s in symbols:
        v = series[s].view_at(asof, lookback=len(grid))
        if tuple(v.sessions) == grid:
            out[s] = np.diff(np.log(np.asarray(v.c, dtype=float)))
    return out


def _rank(x: np.ndarray) -> np.ndarray:
    """Average ranks (ties share the mean of their positions), as Spearman's rho requires."""
    order = np.argsort(x, kind="mergesort")
    xs = x[order]
    ranks = np.empty(len(x))
    i = 0
    while i < len(x):
        j = i
        while j + 1 < len(x) and xs[j + 1] == xs[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0
        i = j + 1
    return ranks


def _corr(x: np.ndarray, y: np.ndarray) -> float | None:
    """Pearson correlation, or None when undefined (a constant series)."""
    if np.std(x) == 0 or np.std(y) == 0:
        return None
    return float(np.corrcoef(x, y)[0, 1])


def lagged(a: np.ndarray, b: np.ndarray, window: int, lag: int) -> tuple[np.ndarray, np.ndarray]:
    """Pairs (a_t, b_{t-lag}) over ``window`` consecutive t. lag > 0: b leads a. Arrays carry MAX_LAG
    extra leading returns, so every lag in -MAX_LAG..MAX_LAG uses only observed returns."""
    n = len(a)
    if lag >= 0:
        return a[n - window:], b[n - window - lag: n - lag]
    return a[n - window + lag: n + lag], b[n - window:]


def pair_stats(a: np.ndarray, b: np.ndarray, window: int) -> dict:
    """Statistics of the last ``window`` returns of a vs b."""
    x, y = a[-window:], b[-window:]
    pear = _corr(x, y)
    spear = _corr(_rank(x), _rank(y))
    sign = float(np.mean(np.sign(x) * np.sign(y)))
    beta = float(np.cov(x, y, ddof=1)[0, 1] / np.var(y, ddof=1)) if np.var(y) > 0 else None
    best_lag, best = (0, pear) if pear is not None else (None, None)
    for lag in range(-MAX_LAG, MAX_LAG + 1):
        if lag:
            xa, yb = lagged(a, b, window, lag)
            c = _corr(xa, yb)
            if c is not None and (best is None or abs(c) > abs(best) + 1e-12):
                best_lag, best = lag, c
    return {"pearson": pear, "spearman": spear, "sign": sign, "beta": beta, "best_lag": best_lag,
            "best_lag_corr": best, "n": window}


def compute_relationships(series: dict[str, SymbolSeries], symbols: list[str], asof: dt.date) -> list[dict]:
    out = []
    for w in WINDOWS:
        rets = aligned_returns(series, symbols, asof, w)
        for a, b in itertools.combinations(sorted(rets), 2):
            out.append({"a": a, "b": b, "window": w, "asof": asof.isoformat(), **pair_stats(rets[a], rets[b], w)})
    return out


def _watched_series(db: Database) -> dict[str, SymbolSeries]:
    """Every enabled symbol with stored daily bars, whatever its asset class or tradability."""
    have = set(db.bars.distinct("symbol", {"interval": "1d"}))
    return {s["_id"]: SymbolSeries.from_db(db, s["_id"])
            for s in db.symbols.find({"enabled": {"$ne": False}}, {"_id": 1}) if s["_id"] in have}


def run_relationships(db: Database, now: dt.datetime) -> dict:
    """Recompute when the latest session or the set of symbols with a bar on it changed (late arrivals,
    interrupted runs); the completion marker is written only after every pair is stored."""
    uni = _watched_series(db)
    if not uni:
        return {"status": "skipped", "reason": "no price history"}
    asof = max(s.sessions[-1] for s in uni.values())
    syms = sorted(s for s, ser in uni.items() if ser.has_bar(asof))
    marker = db.relationship_runs.find_one({"_id": "latest"})
    if marker and marker.get("asof") == asof.isoformat() and marker.get("symbols") == syms and marker.get("complete"):
        return {"status": "current", "asof": marker["asof"]}
    db.relationship_runs.update_one({"_id": "latest"}, {"$set": {"asof": asof.isoformat(), "symbols": syms,
                                                                 "complete": False, "started_at": now}}, upsert=True)
    docs = compute_relationships(uni, syms, asof)
    for d in docs:
        db.relationships.update_one({"a": d["a"], "b": d["b"], "window": d["window"]},
                                    {"$set": {**d, "computed_at": now}}, upsert=True)
    current = set(uni)
    removed = db.relationships.delete_many({"$or": [{"a": {"$nin": list(current)}},
                                                   {"b": {"$nin": list(current)}}]}).deleted_count
    db.relationship_runs.update_one({"_id": "latest"}, {"$set": {"complete": True, "completed_at": now}})
    return {"status": "computed", "asof": asof.isoformat(), "pairs": len(docs), "removed_obsolete": removed}


def similar(db: Database, symbol: str, n: int = 10) -> dict:
    groups = {s["_id"]: set(s.get("groups", [])) for s in db.symbols.find({}, {"groups": 1})}
    rows = list(db.relationships.find({"window": 252, "$or": [{"a": symbol}, {"b": symbol}],
                                       "pearson": {"$ne": None}}))
    out = []
    for r in rows:
        other = r["b"] if r["a"] == symbol else r["a"]
        if other not in groups:      # deleted from the universe since the last refresh
            continue
        lag = None if r["best_lag"] is None else (r["best_lag"] if r["a"] == symbol else -r["best_lag"])
        out.append({"symbol": other, "pearson": r["pearson"], "spearman": r["spearman"], "sign": r["sign"],
                    "best_lag": lag, "shared_groups": sorted(groups.get(symbol, set()) & groups.get(other, set())),
                    "asof": r["asof"]})
    out.sort(key=lambda x: -abs(x["pearson"]))
    for x in out:
        x["link_candidate"] = not x["shared_groups"] and abs(x["pearson"]) >= 0.6
    return {"symbol": symbol, "similar": out[:n]}


class GroupConsensus:
    """Overlay: own signed strength + weight x mean signed strength of the symbol's group peers."""

    def __init__(self, groups: dict[str, list[str]], weight: float = 0.5, threshold: float = 0.05):
        self.groups, self.weight, self.threshold = groups, weight, threshold
        self.key = f"cross_asset@1(w={weight})"

    @staticmethod
    def _signed(dec) -> float:
        return dec.strength if dec.direction == "long" else -dec.strength if dec.direction == "short" else 0.0

    def adjust(self, symbol: str, decisions: dict) -> tuple[str, float]:
        own = self._signed(decisions[symbol])
        peers = {p for g in self.groups.get(symbol, []) for p, gs in self.groups.items() if g in gs} - {symbol}
        vals = [self._signed(decisions[p]) for p in sorted(peers) if p in decisions]
        score = own + (self.weight * float(np.mean(vals)) if vals else 0.0)
        if score > self.threshold:
            return "long", min(1.0, score)
        if score < -self.threshold:
            return "short", min(1.0, -score)
        return "neutral", 0.0
