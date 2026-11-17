"""Pure indicator functions over 1-D numpy arrays (oldest first)."""

from __future__ import annotations

import numpy as np


def sma(x: np.ndarray, n: int) -> float:
    if len(x) < n:
        raise ValueError(f"sma({n}) needs {n} values, got {len(x)}")
    return float(np.mean(x[-n:]))


def ema_series(x: np.ndarray, n: int) -> np.ndarray:
    """EMA seeded with the SMA of the first n values; output aligned to x[n-1:]."""
    if len(x) < n:
        raise ValueError(f"ema({n}) needs {n} values, got {len(x)}")
    alpha = 2.0 / (n + 1)
    out = np.empty(len(x) - n + 1)
    out[0] = np.mean(x[:n])
    for i, price in enumerate(x[n:], start=1):
        out[i] = out[i - 1] + alpha * (price - out[i - 1])
    return out


def true_range(h: np.ndarray, l: np.ndarray, c: np.ndarray) -> np.ndarray:
    """TR for bars 1..n-1 (each uses the previous close); chronological input required."""
    if len(c) < 2:
        raise ValueError("true range needs at least 2 bars")
    prev = c[:-1]
    return np.maximum.reduce([h[1:] - l[1:], np.abs(h[1:] - prev), np.abs(l[1:] - prev)])


def atr(h: np.ndarray, l: np.ndarray, c: np.ndarray, n: int) -> float:
    """Simple-average ATR of the last n true ranges."""
    tr = true_range(h, l, c)
    if len(tr) < n:
        raise ValueError(f"atr({n}) needs {n + 1} bars, got {len(c)}")
    return float(np.mean(tr[-n:]))


def rsi_sma(c: np.ndarray, n: int) -> float:
    """RSI using simple averages of the last n gains/losses (not Wilder smoothing)."""
    if len(c) < n + 1:
        raise ValueError(f"rsi({n}) needs {n + 1} closes, got {len(c)}")
    d = np.diff(c[-(n + 1):])
    gain, loss = np.mean(np.clip(d, 0, None)), np.mean(np.clip(-d, 0, None))
    if loss == 0:
        return 100.0 if gain > 0 else 50.0
    return float(100 - 100 / (1 + gain / loss))


def roc(c: np.ndarray, n: int) -> float:
    if len(c) < n + 1:
        raise ValueError(f"roc({n}) needs {n + 1} closes, got {len(c)}")
    return float(c[-1] / c[-(n + 1)] - 1)
