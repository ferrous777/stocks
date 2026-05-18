---
name: stocks-yahoo-yfinance
description: Fetches and integrates Yahoo Finance market data in the stocks repo using yfinance and safe HTTP patterns. Use when adding or changing price history, fundamentals, batch downloads, retries, Yahoo API errors, query1/query2, cookies, rate limits, or when the user mentions Yahoo Finance, yfinance, MarketData, or chart endpoints.
---

# Stocks app — Yahoo Finance and yfinance

## Scope

This repository pulls OHLCV and fundamentals from **Yahoo Finance**. Prefer patterns that match **current yfinance** behavior rather than minimal `requests` + chart URLs alone.

Relevant code: `market_data/market_data.py`, `market_data/data_loader.py`, scheduler paths that use `MarketData`.

## Default rule: one data path

- **Prefer `yfinance`** for historical prices: `yf.Ticker(symbol).history(start=..., end=..., interval="1d", ...)` or `yf.download(...)` for batches.
- **Prefer `Ticker.info`** (or yfinance quote-summary flows) for fundamentals unless you need fields yfinance does not expose.
- **Avoid maintaining a second path** that calls `https://query1.finance.yahoo.com/v8/finance/chart/...` with plain `requests` unless there is a documented reason; if both exist, keep behavior aligned (adjusted vs raw OHLC, timezone, error handling).

## Why plain `requests` + User-Agent is fragile

Upstream yfinance uses **`curl_cffi`** with **`Session(impersonate="chrome")`**, obtains **cookies** (e.g. via `fc.yahoo.com`), fetches a **crumb** from Yahoo’s getcrumb endpoint, appends **`crumb`** to query params, retries **transient** errors with backoff, switches **cookie strategy** on some failures, handles **429** and **consent** redirects, and parses **`chart.error`** and empty `indicators`. A stock `requests` session with only `User-Agent` skips most of that and tends to break when Yahoo tightens bot detection.

## If you must call the chart JSON yourself

Match yfinance’s **history** scraper shape as closely as possible:

- **URL base:** `https://query2.finance.yahoo.com/v8/finance/chart/{ticker}` (yfinance uses `query2` for this path; the app historically used `query1`—prefer aligning with yfinance unless you verify both).
- **Params:** `period1`, `period2`, `interval`, `includePrePost`, and **`events=div,splits,capitalGains`** (as in yfinance `PriceHistory`).
- **Transport:** Prefer the same stack as yfinance (**curl_cffi** + impersonate) and the **cookie + crumb** flow, or delegate to yfinance’s session layer instead of reimplementing.
- **Resilience:** Retry transient failures with exponential backoff; treat **HTTP 429** as rate limit; read **`data["chart"]["error"]`** when present; detect maintenance-style HTML (e.g. “Will be right back”) if you parse text responses.

## Timezones and timestamps

Yahoo expects **Unix `period1`/`period2`** consistent with the **instrument’s exchange timezone** for correct calendar-day boundaries. Avoid using naive `datetime.timestamp()` in the **server’s local TZ** for non-US symbols or DST edges. **`Ticker.history`** with date strings or timezone-aware datetimes delegates this to yfinance.

## Adjusted vs raw prices

`Ticker.history` defaults to **`auto_adjust=True`** (split/dividend-adjusted OHLC semantics). Raw chart `quote` arrays are **unadjusted**. Pick one semantics for strategies and **document it**; do not mix adjusted and raw across code paths without explicit conversion.

## Configuration and versions

- Expose **`yf.set_config`** / **`YfConfig`** for **`network.retries`** and **`network.proxy`** when users need resilience or corporate proxies.
- Pin **`yfinance`** in `requirements.txt` deliberately; very old pins miss Yahoo-side fixes. After upgrading, run tests and smoke-fetch a few symbols.

## Implementation checklist

When changing market data fetching:

1. [ ] Single primary API: yfinance `history` / `download` / `info` unless raw JSON is unavoidable.
2. [ ] Retries and clear errors on all network paths (not only `yf.download`).
3. [ ] Consistent **adjusted vs raw** OHLC across batch, incremental, and backtest flows.
4. [ ] Timezone-safe range boundaries for `period1`/`period2` if building URLs manually.
5. [ ] Handle **`chart.error`** and empty `result` / `timestamp` / `quote` like yfinance.
6. [ ] No duplicate session stacks (`requests` chart + `yf` elsewhere) without a migration plan.

## Deeper reference

For file paths in this repo, upstream yfinance module names, and param details, see [reference.md](reference.md).
