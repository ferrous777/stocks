# Backtesting Documentation

## Overview
The backtesting system allows you to test trading strategies against historical market data and compare their performance against a buy-and-hold strategy.

## Usage

### Command Line
```bash
# Basic backtest with default settings
python main.py --symbol AAPL --backtest

# Backtest with specific strategy
python main.py --symbol AAPL --backtest --strategy macd

# Backtest with custom initial capital
python main.py --symbol AAPL --backtest --initial-capital 100000

# Backtest multiple symbols
python main.py --symbol "AAPL MSFT GOOGL" --backtest

# Backtest with custom date range
python main.py --symbol AAPL --backtest --start 2020-01-01 --end 2023-12-31
```

### Available Strategies
- `sma`: Simple Moving Average (default)
- `macd`: Moving Average Convergence Divergence
- `rsi`: Relative Strength Index
- `bb`: Bollinger Bands

## Output
Results are saved to JSON files in the cache directory with the format:
`{symbol}_backtest_{strategy}_{date}.json`

### Sample Output Structure
```json
{
  "symbol": "AAPL",
  "strategy": "sma",
  "initial_capital": 10000,
  "date_run": "2024-01-01T14:30:45.123456",
  "results": {
    "total_returns": 23.45,
    "total_trades": 24,
    "winning_trades": 16,
    "losing_trades": 8,
    "win_rate": 0.667,
    "final_balance": 12345.67,
    "max_drawdown": -15.3,
    "sharpe_ratio": 1.23,
    "trades": [
      {
        "date": "2023-01-15",
        "type": "BUY",
        "price": 150.25,
        "shares": 10,
        "profit_loss": null
      }
    ]
  },
  "buy_and_hold": {
    "initial_price": 150.25,
    "final_price": 185.75,
    "shares_held": 66.55,
    "final_value": 12362.91,
    "total_return_pct": 23.63,
    "total_return_dollars": 2362.91
  },
  "comparison": {
    "strategy_outperformance": -0.18,
    "strategy_vs_buyhold": "UNDERPERFORM"
  }
}
```

## Metrics Explained

### Strategy Performance
- `total_returns`: Percentage return on initial capital
- `total_trades`: Number of trades executed
- `winning_trades`: Number of profitable trades
- `losing_trades`: Number of unprofitable trades
- `win_rate`: Percentage of winning trades
- `final_balance`: Final portfolio value
- `max_drawdown`: Largest peak-to-trough decline
- `sharpe_ratio`: Risk-adjusted return metric

### Buy and Hold Performance
- `initial_price`: Stock price at start of period
- `final_price`: Stock price at end of period
- `shares_held`: Number of shares bought with initial capital
- `final_value`: Final value of buy-and-hold position
- `total_return_pct`: Percentage return of buy-and-hold
- `total_return_dollars`: Dollar return of buy-and-hold

### Comparison
- `strategy_outperformance`: How much the strategy outperformed buy-and-hold (in percentage points)
- `strategy_vs_buyhold`: Simple OUTPERFORM/UNDERPERFORM indicator

## Cache Management
- Results are automatically cached for future reference
- Use `--force` flag to ignore cached data and run fresh backtest
- Cache files include date in filename for tracking multiple runs 