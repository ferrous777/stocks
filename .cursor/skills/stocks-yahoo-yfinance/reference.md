# Reference — Yahoo / yfinance and this repo

## Stocks repo touchpoints

| Area | File | Notes |
|------|------|--------|
| Batch + incremental chart HTTP, `requests` session | `market_data/market_data.py` | `get_batch_data`, `_fetch_from_api`, `get_batch_data_with_incremental_update` |
| `yf.download`, `Ticker.info`, JSON cache | `market_data/market_data.py` | `_get_historical_data`, `_get_fundamental_data` |
| Loader wrapper | `market_data/data_loader.py` | `get_market_data` uses `yf.Ticker` + file cache |
| Scheduler | `scheduler/daily_scheduler.py` | `MarketDataCollector` uses `MarketData()` |

## yfinance upstream (local clone or PyPI)

| Concern | Where to look in yfinance |
|---------|-------------------------|
| Session, cookie, crumb, retries, 429 | `yfinance/data.py` — class `YfData`, `_make_request`, `_get_cookie_and_crumb` |
| Chart URL and query params | `yfinance/scrapers/history.py` — `PriceHistory.history`, `url = f"{_BASE_URL_}/v8/finance/chart/..."` |
| Host constants | `yfinance/const.py` — `_QUERY1_URL_`, `_BASE_URL_` (query2), `_ROOT_URL_` |
| Retries / proxy config | `yfinance/config.py` — `YfConfig.network` |

## Chart GET parameters (yfinance `PriceHistory`)

Typical keys: `period1`, `period2` (Unix seconds) **or** `range` for period-based fetches; `interval`; `includePrePost`; **`events=div,splits,capitalGains`**.

## Legal

Yahoo marks and terms apply to data use; yfinance README points to Yahoo terms — keep personal/research use in mind for product decisions.
