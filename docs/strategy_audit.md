# Strategy audit (phase 2)

Audit of the legacy `strategies/` package before porting to the point-in-time contract in
`stocks_service/strategies/`. Line references are to the legacy files at commit `5d17f8f`.

**Common findings (all strategies)**

- `generate_signals(data_points, index)` slices `[.. : index+1]`, so no strategy reads bars *after* `index`.
  Look-ahead instead came from elsewhere: the legacy backtest fills at the **same bar's close** that produced the
  signal (`strategy.py:236-241`), and live `analyze()` paths compute differently from `generate_signals`.
- Inputs were whatever the cache held (Yahoo split-adjusted as of fetch time). Volume-based rules saw split-day
  volume jumps when data was raw. The port reads a point-in-time split-adjusted view (`PointInTimeView`).
- Confidence values are arbitrary scalings (e.g. `abs(spread) * 100`), not probabilities. The port keeps them as
  **strength** in [0, 1]; probabilities come only from calibration (plan §7).
- Legacy base backtest: short stop/target sign bug (`strategy.py:242-243`), returns summed instead of compounded
  (`strategy.py:304`). The legacy backtest is retired; phase 3 replaces it with the shared simulator.

| Strategy | Logic | Defects found | Verdict |
|---|---|---|---|
| Moving average (`moving_average.py`) | SMA50/SMA200 regime + crossover | Exit branch unreachable (every non-zero spread returns long/short first, `:46-60`); live `analyze()` divides by `min(50, len)` and has a different exit rule (`:79-112`). | **Fix**: one function; crossover vs regime reported as reasons; exit when the spread narrows toward zero. |
| Volume–price (`volume_price.py`) | Volume spike ≥2× 20-bar avg with ≥2% move | Raw volume → split days look like spikes; exit on any quiet day (`volume_ratio < 0.5`) is noise. | **Fix**: adjusted volume; exit only after the spike's direction reverses. |
| Bollinger (`bollinger.py`) | Long near lower band, short near upper | Window is `period + 1` closes (`:6`); divide-by-zero when band width is 0. | **Fix**: exact 20-bar window; explicit `hold` on zero width. Absorbs mean reversion. |
| Mean reversion (`mean_reversion.py`) | Bollinger + %-deviation filter | Duplicate `analyze` / `_calculate_strategy_metrics` / `get_min_required_points`; emits `buy`/`sell` (crashes ensemble); no exit; same Bollinger logic as above. | **Merge** into Bollinger as an optional deviation filter; not ported separately. |
| Momentum (`momentum.py`) | RSI(14) ≥ 55 and ROC(10) ≥ 2% (and mirrored) | Emits `buy`/`sell`; duplicate `get_min_required_points` (`:30`, `:110`); RSI is a simple-average RSI (not Wilder) — fine, but labelled. | **Fix**: canonical vocabulary; RSI documented as SMA-RSI. |
| Trend (`trend.py`) | Breakout beyond support/resistance ± k·ATR, trend strength, volume confirmation | Support/resistance include the current bar, so `close > resistance + k·ATR` is **impossible** (`:44`, `:129-141`); short branch requires `strong_trend and not uptrend`, which contradict (strength > 0.78 vs ≤ 0.5) — the strategy **never shorts** (`:65-69`); "trend strength" only measures up-days; raw volume; custom `backtest` duplicates logic (`:220`). | **Fix**: levels from prior bars only; symmetric strength (up-day fraction vs down-day fraction); adjusted volume. |
| MACD (`macd.py`) | 12/26/9 crossover | EMAs recomputed over a 36-bar sliding window re-seeded every day (`:31-33`, `:93-104`) — values are not a standard MACD and change with the window; confidence in price units (`abs(histogram) * 2`); exit on any histogram weakening fires almost every bar. | **Fix**: EMAs over a fixed 250-bar warm-up ending at asof; strength normalised by price; exit only on a histogram sign change toward zero. |
| Ensemble (`ensemble.py`) | Confidence-weighted vote across strategies | `KeyError` on `buy`/`sell` (`:130`); adaptive weights never called (`:32-107`); `backtest` concatenates sub-strategy trades (`:237`). | **Fix**: votes on canonical directions only; static, versioned weights (tuning is a later phase). |

Not ported: `strategies/backtest.py` and `strategies/recommendations.py` (non-runnable stubs), the plugin system
(no real plugins), and `scheduler/daily_scheduler.py` toy strategies.

Every ported strategy is a pure `decide(view, params) -> Decision` registered with a version, and is only callable
through `run_decision` (live, replay, backtest and evaluation all use it). Whether any of them makes money is **not**
established by this audit — that is the phase 3 validation gate.
