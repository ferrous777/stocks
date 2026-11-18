"""Trade-filter "umpires" (ideas from abu; concepts only, no code copied). They **annotate** outlook rows
(``favorable`` / ``neutral`` / ``veto`` and loss-cluster flags) and never hide them.

Features at the decision close (point-in-time view, split-adjusted as of that date):
21- and 63-session regression slopes of log price, 252-session price-rank percentile, the 20/60
volatility ratio, ATR(14) as % of price, the last overnight gap and the 5-session return.

Training data are the base-rate labels' outcomes (same plans, simulator and costs as calibration),
sampled every 5 sessions, resolved before the sealed holdout. Per side:

* **kNN vote** — standardize features; among the ``K`` nearest training examples, if >= 61.8% are
  "losers" (bottom 23.6% of training excess) the row gets ``veto``; >= 61.8% "winners" (top 23.6%)
  ``favorable``; otherwise ``neutral``.
* **Loss-cluster detector** — a seeded diagonal Gaussian mixture (EM); components with at least
  ``MIN_COMPONENT`` training members and a loser share >= ``LOSS_CLUSTER_SHARE`` are loss clusters.

Walk-forward evaluation: for each year T, train on labels resolved before T and annotate labels
decided in that year; compare the mean realized excess of vetoed vs. not-vetoed labels with a
seeded **block bootstrap over decision dates** (labels overlap in time and share market dates).
Verdict ``useful`` only if the CI of (not vetoed - vetoed) is above 0.
"""

from __future__ import annotations

import datetime as dt
import io

import numpy as np
from bson import Binary
from pymongo.database import Database

from .levels import LevelsUnavailable
from .outlook.labels import STRIDE, _label, sample_sessions
from .research.backtest import PolicyParams
from .research.series import SymbolSeries
from .sim import CostProfile, DataGapError, ExecutionPolicy
from .strategies.indicators import atr

VERSION = "umpires@1"
FEATURES = ("slope21", "slope63", "rank252", "vol_ratio", "atr_pct", "gap", "ret5")
K = 50
VOTE = 0.618
TAIL = 0.236
GMM_K = 8
MIN_COMPONENT = 30
LOSS_CLUSTER_SHARE = 0.5
MIN_BARS = 253


def features(view) -> np.ndarray | None:
    if len(view) < MIN_BARS:
        return None
    c = np.asarray(view.c, dtype=float)
    o = np.asarray(view.o, dtype=float)
    lc = np.log(c)

    def slope(n):
        y = lc[-n:]
        x = np.arange(n, dtype=float)
        return float(np.polyfit(x, y, 1)[0] * n)

    r = np.diff(lc)
    v20, v60 = float(np.std(r[-20:], ddof=1)), float(np.std(r[-60:], ddof=1))
    a = atr(np.asarray(view.h, dtype=float), np.asarray(view.l, dtype=float), c, 14)
    f = np.array([slope(21), slope(63), float(np.mean(c[-252:] <= c[-1])), v20 / v60 if v60 > 0 else np.nan,
                  a / c[-1], o[-1] / c[-2] - 1, c[-1] / c[-6] - 1])
    return f if np.all(np.isfinite(f)) else None


def build_training(universe: dict[str, SymbolSeries], symbols: list[str], irx: SymbolSeries, start: dt.date,
                   end: dt.date, cost: CostProfile, *, resolved_before: dt.date, log=None) -> dict:
    """Features and outcomes of base-rate plans (both sides) for sampled sessions in [start, end]."""
    params, policy = PolicyParams(), ExecutionPolicy()
    out = {s: {"X": [], "y": [], "decided": [], "resolved": []} for s in ("long", "short")}
    for n, sym in enumerate(symbols):
        series = universe[sym]
        for d in sample_sessions(start, end):
            if d >= resolved_before or not series.has_bar(d):
                continue
            view = series.view_at(d)
            f = features(view)
            if f is None:
                continue
            for side in ("long", "short"):
                if side == "short" and cost.borrow_rate_annual is None:
                    continue
                try:
                    lab = _label(series, irx, "base_rate", side, d, view, params.levels_dict, cost, policy,
                                 policy.timeout_sessions + 3)
                except (LevelsUnavailable, DataGapError):
                    continue
                if lab is None or lab.resolved >= resolved_before:
                    continue
                o = out[side]
                o["X"].append(f)
                o["y"].append(lab.excess)
                o["decided"].append(d)
                o["resolved"].append(lab.resolved)
        if log and (n + 1) % 10 == 0:
            log(step="umpire_training", symbols_done=n + 1)
    for o in out.values():
        o["X"] = np.asarray(o["X"], dtype=float).reshape(-1, len(FEATURES))
        o["y"] = np.asarray(o["y"], dtype=float)
    return out


# --- models --------------------------------------------------------------------------------------

class SideModel:
    def __init__(self, X: np.ndarray, y: np.ndarray, seed: int = 7):
        if len(y) < max(K, GMM_K * MIN_COMPONENT):
            raise ValueError(f"not enough training examples ({len(y)})")
        self.mu, self.sd = X.mean(axis=0), X.std(axis=0)
        self.sd[self.sd == 0] = 1.0
        self.Z = ((X - self.mu) / self.sd).astype(np.float32)
        self.lo, self.hi = np.quantile(y, TAIL), np.quantile(y, 1 - TAIL)
        self.loser = y <= self.lo
        self.winner = y >= self.hi
        self.n = len(y)
        self._fit_gmm(seed)

    # kNN ---------------------------------------------------------------------------------------
    def knn(self, X: np.ndarray, chunk: int = 512) -> tuple[np.ndarray, np.ndarray]:
        Q = ((X - self.mu) / self.sd).astype(np.float32)
        lose, win = np.empty(len(Q)), np.empty(len(Q))
        zz = (self.Z ** 2).sum(axis=1)
        for i in range(0, len(Q), chunk):
            q = Q[i:i + chunk]
            d = (q ** 2).sum(axis=1)[:, None] + zz[None, :] - 2 * q @ self.Z.T
            idx = np.argpartition(d, K - 1, axis=1)[:, :K]
            lose[i:i + chunk] = self.loser[idx].mean(axis=1)
            win[i:i + chunk] = self.winner[idx].mean(axis=1)
        return lose, win

    # GMM (diagonal, EM, seeded) -----------------------------------------------------------------
    def _fit_gmm(self, seed: int, iters: int = 60) -> None:
        rng = np.random.default_rng(seed)
        Z = self.Z.astype(float)
        k = GMM_K
        means = Z[rng.choice(len(Z), k, replace=False)]
        var = np.tile(Z.var(axis=0) + 1e-6, (k, 1))
        w = np.full(k, 1.0 / k)
        for _ in range(iters):
            ll = self._log_resp(Z, means, var, w)
            r = np.exp(ll - ll.max(axis=1, keepdims=True))
            r /= r.sum(axis=1, keepdims=True)
            nk = r.sum(axis=0) + 1e-9
            means = (r.T @ Z) / nk[:, None]
            var = (r.T @ (Z ** 2)) / nk[:, None] - means ** 2 + 1e-6
            w = nk / nk.sum()
        self.means, self.var, self.w = means, var, w
        comp = self._assign(Z)
        self.comp_n = np.bincount(comp, minlength=k)
        self.comp_loss = np.array([self.loser[comp == j].mean() if self.comp_n[j] else 0.0 for j in range(k)])
        self.loss_clusters = (self.comp_n >= MIN_COMPONENT) & (self.comp_loss >= LOSS_CLUSTER_SHARE)

    @staticmethod
    def _log_resp(Z, means, var, w):
        return (np.log(w)[None, :] - 0.5 * (np.log(2 * np.pi * var).sum(axis=1)[None, :]
                                          + (((Z[:, None, :] - means[None, :, :]) ** 2) / var[None, :, :]).sum(axis=2)))

    def _assign(self, Z) -> np.ndarray:
        return np.argmax(self._log_resp(Z, self.means, self.var, self.w), axis=1)

    def annotate(self, X: np.ndarray) -> list[dict]:
        lose, win = self.knn(X)
        comp = self._assign(((X - self.mu) / self.sd).astype(float))
        out = []
        for i in range(len(X)):
            vote = "veto" if lose[i] >= VOTE else "favorable" if win[i] >= VOTE else "neutral"
            out.append({"knn": vote, "loser_share": float(lose[i]), "winner_share": float(win[i]),
                        "loss_cluster": bool(self.loss_clusters[comp[i]]), "component": int(comp[i]),
                        "component_loser_share": float(self.comp_loss[comp[i]])})
        return out

    # persistence ---------------------------------------------------------------------------------
    def to_doc(self, X: np.ndarray, y: np.ndarray) -> dict:
        buf = io.BytesIO()
        np.savez_compressed(buf, X=X.astype(np.float32), y=y.astype(np.float32))
        return {"n": self.n, "data": Binary(buf.getvalue()), "loss_clusters": int(self.loss_clusters.sum()),
                "tail_lo": float(self.lo), "tail_hi": float(self.hi)}

    @classmethod
    def from_doc(cls, doc: dict) -> SideModel:
        z = np.load(io.BytesIO(bytes(doc["data"])))
        return cls(z["X"].astype(float), z["y"].astype(float))


# --- evaluation and training job -----------------------------------------------------------------

BLOCK_DATES = 26   # ~6 months of 5-session samples: longer than the 126-session outcome horizon


def _block_bootstrap_diff(keep_dates, keep_y, veto_dates, veto_y, seed: int, n: int = 1000) -> tuple[float, float]:
    """95% CI of mean(not vetoed) - mean(vetoed), resampling contiguous blocks of decision dates
    jointly for both groups and all symbols (outcomes overlap in time and share market dates)."""
    rng = np.random.default_rng(seed)
    dates = np.array(sorted(set(keep_dates) | set(veto_dates)))
    pos = {d: i for i, d in enumerate(dates)}
    ki = np.array([pos[d] for d in keep_dates])
    vi = np.array([pos[d] for d in veto_dates])
    k_sum = np.bincount(ki, weights=keep_y, minlength=len(dates))
    k_n = np.bincount(ki, minlength=len(dates))
    v_sum = np.bincount(vi, weights=veto_y, minlength=len(dates))
    v_n = np.bincount(vi, minlength=len(dates))
    nb = int(np.ceil(len(dates) / BLOCK_DATES))
    diffs = []
    for _ in range(n):
        starts = rng.integers(0, max(1, len(dates) - BLOCK_DATES + 1), size=nb)
        idx = (starts[:, None] + np.arange(BLOCK_DATES)[None, :]).ravel()
        idx = idx[idx < len(dates)]
        kn, vn = k_n[idx].sum(), v_n[idx].sum()
        if kn == 0 or vn == 0:
            continue
        diffs.append(k_sum[idx].sum() / kn - v_sum[idx].sum() / vn)
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    return float(lo), float(hi)


def walk_forward(data: dict, holdout_start: dt.date, seed: int = 11) -> dict:
    out = {}
    for side, o in data.items():
        if len(o["y"]) == 0:
            continue
        dec = np.array(o["decided"])
        res = np.array(o["resolved"])
        years = sorted({d.year for d in dec})
        vet, keep, vet_d, keep_d = [], [], [], []
        for yr in years[3:]:
            T = dt.date(yr, 1, 1)
            T1 = min(dt.date(yr + 1, 1, 1), holdout_start)
            tr = res < T
            te = (dec >= T) & (dec < T1)
            if tr.sum() < GMM_K * MIN_COMPONENT or te.sum() == 0:
                continue
            m = SideModel(o["X"][tr], o["y"][tr])
            ann = m.annotate(o["X"][te])
            yt = o["y"][te]
            v = np.array([a["knn"] == "veto" for a in ann])
            dt_te = dec[te]
            vet += list(yt[v])
            keep += list(yt[~v])
            vet_d += list(dt_te[v])
            keep_d += list(dt_te[~v])
        r = {"vetoed": len(vet), "not_vetoed": len(keep)}
        if len(vet) >= 30 and len(keep) >= 30:
            vet_a, keep_a = np.array(vet), np.array(keep)
            lo, hi = _block_bootstrap_diff(np.array(keep_d), keep_a, np.array(vet_d), vet_a, seed)
            r.update(mean_vetoed=float(vet_a.mean()), mean_not_vetoed=float(keep_a.mean()),
                     difference=float(keep_a.mean() - vet_a.mean()), ci95=[float(lo), float(hi)],
                     verdict="useful" if lo > 0 else "not_useful")
        else:
            r["verdict"] = "insufficient"
        out[side] = r
    return out


def train(db: Database, *, now: dt.datetime, log=None) -> dict:
    from .outlook.build import latest_cost_profile
    from .research.protocol import holdout_window, load_universe
    cost = latest_cost_profile(db, "market")
    hw = holdout_window(db)
    if cost is None or hw is None:
        raise ValueError("needs the market cost profile and a sealed holdout")
    uni, tradable = load_universe(db)
    data = build_training(uni, tradable, uni["^IRX"], dt.date(1990, 1, 2), hw[0], cost, resolved_before=hw[0], log=log)
    evaluation = walk_forward(data, hw[0])
    sides = {}
    for side, o in data.items():
        if len(o["y"]) >= max(K, GMM_K * MIN_COMPONENT):
            sides[side] = SideModel(o["X"], o["y"]).to_doc(o["X"], o["y"])
    doc = {"created_at": now, "version": VERSION, "stride": STRIDE, "cost_profile": cost.key,
           "resolved_before": hw[0].isoformat(), "features": list(FEATURES), "sides": sides,
           "evaluation": evaluation}
    db.umpire_models.insert_one(doc)
    return {"evaluation": evaluation, "trained_sides": sorted(sides)}


_loaded: dict = {}


def latest_models(db: Database, cost_profile: str | None = None) -> tuple[str | None, dict[str, SideModel], dict]:
    """(model id, side models, walk-forward evaluation per side) of the latest model trained under
    ``cost_profile`` (outcomes, and so votes and verdicts, depend on the costs)."""
    q = {"cost_profile": cost_profile} if cost_profile else {}
    doc = db.umpire_models.find_one(q, sort=[("created_at", -1), ("_id", -1)], projection={"_id": 1, "evaluation": 1})
    if doc is None:
        return None, {}, {}
    key = (db.name, str(doc["_id"]))
    if key not in _loaded:
        full = db.umpire_models.find_one({"_id": doc["_id"]})
        _loaded.clear()
        _loaded[key] = {s: SideModel.from_doc(d) for s, d in full["sides"].items()}
    return str(doc["_id"]), _loaded[key], doc.get("evaluation", {})
