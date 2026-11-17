"""Performance statistics, bootstrap confidence intervals and overfitting diagnostics."""

from __future__ import annotations

import itertools
import math
from statistics import NormalDist

import numpy as np

TRADING_DAYS = 252
_N = NormalDist()


def daily_returns(equity: list[float]) -> np.ndarray:
    e = np.asarray(equity, dtype=float)
    return e[1:] / e[:-1] - 1


def max_drawdown(equity: list[float]) -> tuple[float, int]:
    e = np.asarray(equity, dtype=float)
    peak = np.maximum.accumulate(e)
    dd = e / peak - 1
    # longest stretch below a prior peak, in sessions
    longest = cur = 0
    for x in dd:
        cur = cur + 1 if x < 0 else 0
        longest = max(longest, cur)
    return float(-dd.min()), longest


def summarize(equity: list[float], cash_daily: np.ndarray) -> dict:
    r = daily_returns(equity)
    years = len(r) / TRADING_DAYS
    total = equity[-1] / equity[0] - 1
    excess = r - cash_daily[: len(r)]
    sd = float(np.std(excess, ddof=1)) if len(r) > 1 else float("nan")
    downside = excess[excess < 0]
    dsd = float(np.sqrt(np.mean(downside ** 2))) if len(downside) else float("nan")
    mdd, dd_len = max_drawdown(equity)
    return {
        "total_return": total,
        "cagr": (1 + total) ** (1 / years) - 1 if years > 0 and total > -1 else float("nan"),
        "volatility": float(np.std(r, ddof=1) * math.sqrt(TRADING_DAYS)) if len(r) > 1 else float("nan"),
        "sharpe": float(np.mean(excess) / sd * math.sqrt(TRADING_DAYS)) if sd and sd > 0 else float("nan"),
        "sortino": float(np.mean(excess) / dsd * math.sqrt(TRADING_DAYS)) if dsd and dsd > 0 else float("nan"),
        "max_drawdown": mdd,
        "max_drawdown_sessions": dd_len,
        "sessions": len(equity),
        "years": years,
    }


def block_bootstrap_mean_ci(x: np.ndarray, block: int = 20, n: int = 2000, alpha: float = 0.05,
                            seed: int = 7) -> tuple[float, float, float]:
    """Annualized mean of daily series ``x`` with a moving-block bootstrap CI (seeded, reproducible)."""
    x = np.asarray(x, dtype=float)
    T = len(x)
    if T < block * 2:
        raise ValueError("series too short for block bootstrap")
    rng = np.random.default_rng(seed)
    k = math.ceil(T / block)
    starts = rng.integers(0, T - block + 1, size=(n, k))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(n, -1)[:, :T]
    means = x[idx].mean(axis=1) * TRADING_DAYS
    lo, hi = np.percentile(means, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return float(x.mean() * TRADING_DAYS), float(lo), float(hi)


def deflated_sharpe(returns: np.ndarray, trial_sharpes: list[float]) -> float:
    """Deflated Sharpe Ratio (Bailey & Lopez de Prado, 2014), per-period Sharpe ratios.

    Probability that the true Sharpe exceeds the expected maximum Sharpe of ``len(trial_sharpes)``
    independent trials, adjusting for skewness, kurtosis and sample length.
    """
    r = np.asarray(returns, dtype=float)
    T = len(r)
    sd = r.std(ddof=1)
    if T < 3 or sd == 0:
        return float("nan")
    sr = r.mean() / sd
    skew = float(((r - r.mean()) ** 3).mean() / sd ** 3)
    kurt = float(((r - r.mean()) ** 4).mean() / sd ** 4)
    n = len(trial_sharpes)
    var_sr = float(np.var(trial_sharpes, ddof=1)) if n > 1 else 0.0
    gamma = 0.5772156649
    sr0 = 0.0 if n <= 1 else math.sqrt(var_sr) * ((1 - gamma) * _N.inv_cdf(1 - 1 / n)
                                                  + gamma * _N.inv_cdf(1 - 1 / (n * math.e)))
    denom = math.sqrt(max(1e-12, 1 - skew * sr + (kurt - 1) / 4 * sr ** 2))
    return float(_N.cdf((sr - sr0) * math.sqrt(T - 1) / denom))


def probability_of_backtest_overfitting(matrix: np.ndarray, splits: int = 16) -> dict:
    """CSCV (Bailey, Borwein, Lopez de Prado & Zhu): T x N matrix of per-period returns for N configs.

    Fraction of in-sample/out-of-sample combinations where the in-sample best configuration ranks
    at or below the median out of sample.
    """
    M = np.asarray(matrix, dtype=float)
    T, N = M.shape
    if N < 2:
        raise ValueError("PBO needs at least two configurations")
    blocks = np.array_split(np.arange(T), splits)
    logits = []
    for is_blocks in itertools.combinations(range(splits), splits // 2):
        is_idx = np.concatenate([blocks[b] for b in is_blocks])
        oos_idx = np.concatenate([blocks[b] for b in range(splits) if b not in is_blocks])

        def sharpe(idx):
            sub = M[idx]
            sd = sub.std(axis=0, ddof=1)
            return np.where(sd > 0, sub.mean(axis=0) / np.where(sd > 0, sd, 1), 0.0)

        best = int(np.argmax(sharpe(is_idx)))
        oos = sharpe(oos_idx)
        rank = (oos < oos[best]).sum() + 0.5 * ((oos == oos[best]).sum() - 1) + 1  # 1..N
        w = rank / (N + 1)
        logits.append(math.log(w / (1 - w)))
    logits = np.array(logits)
    return {"pbo": float((logits <= 0).mean()), "combinations": len(logits), "median_logit": float(np.median(logits))}
