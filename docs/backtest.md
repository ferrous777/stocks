# Backtesting Documentation

## Overview
The backtesting system allows you to test trading strategies against historical market data and compare their performance against a buy-and-hold strategy.

## Literature Review (Issue #4)

This section summarizes research findings for backtesting bias controls, evaluation horizons, and interpretation metrics.

### Backtesting biases and mitigations

- Survivorship bias: using only currently listed assets can overstate historical performance; include delisted assets and point-in-time universes where possible.
- Look-ahead bias: features or labels must only use information available at each historical timestamp.
- Data-snooping/overfitting: repeated strategy tuning on the same sample inflates in-sample performance and weakens out-of-sample reliability.

Recommended controls:

1. Split data into development/validation/test windows and reserve a true holdout period.
2. Use walk-forward or rolling-window validation rather than one static split.
3. Track all parameter searches and avoid selecting models solely on in-sample Sharpe.
4. Use realistic trading assumptions (costs, slippage, liquidity constraints).

### Evaluation horizons

- For daily strategies, multi-year windows are generally required to cover different market regimes.
- Weekly/monthly strategies should be evaluated across longer cycles (including at least one stress regime) before promoting to production.
- Cross-regime robustness checks are required: re-run results across alternate start dates and subperiods, not just one backtest window.

### Performance metric interpretation

Core metrics for this repository are:

- Return metrics: total and annualized returns.
- Risk-adjusted metrics: Sharpe, Sortino, Calmar.
- Drawdown metrics: max drawdown and drawdown duration.
- Trade quality metrics: win rate and profit factor.

Interpretation guidance:

- Sharpe and Sortino should be interpreted with sample-length awareness; both are unstable on short windows.
- Calmar should be paired with drawdown duration so short-lived and prolonged drawdowns are distinguished.
- Metrics should be analyzed net of transaction costs/slippage to reduce optimistic bias.

### References

1. Bailey, D. H., Borwein, J. M., Lopez de Prado, M., & Zhu, Q. J. (2014). The Probability of Backtest Overfitting. Journal of Computational Finance.
2. Brown, S. J., Goetzmann, W. N., Ibbotson, R. G., & Ross, S. A. (1992). Survivorship Bias in Performance Studies. Review of Financial Studies.
3. Lo, A. W., & MacKinlay, A. C. (1990). Data-Snooping Biases in Tests of Financial Asset Pricing Models. Review of Financial Studies.
4. Lo, A. W. (2002). The Statistics of Sharpe Ratios. Financial Analysts Journal.
5. Arnott, R. D., Harvey, C. R., & Markowitz, H. (2019). A Backtesting Protocol in the Era of Machine Learning. Journal of Portfolio Management.

## Strategy Taxonomy (Issue #5)

This taxonomy focuses on medium- and long-horizon approaches requested for task 3.

### 1) Factor-based strategies

- Examples: value, quality, low-volatility, size, multi-factor ranking.
- Pros: interpretable economic intuition, diversified signal sources, strong academic coverage.
- Cons: factor crowding and long drawdown cycles, turnover sensitivity, regime dependence.
- Data requirements: clean point-in-time fundamentals, corporate actions, universe membership history, benchmark series.

### 2) Momentum and trend-following

- Examples: cross-sectional momentum, time-series momentum, moving-average trend rules.
- Pros: robust in persistent trends, simple implementation, broadly applicable across assets.
- Cons: whipsaw risk in range-bound markets, crash sensitivity during sharp reversals.
- Data requirements: adjusted OHLCV history, liquidity filters, transaction-cost model, regime segmentation windows.

### 3) Volatility and risk-premium strategies

- Examples: low-volatility tilt, volatility timing, risk-parity style allocations.
- Pros: explicit risk targeting, often smoother drawdown profile, portfolio-construction friendly.
- Cons: leverage and financing assumptions can dominate outcomes, tail shocks can break stability.
- Data requirements: realized/implied volatility inputs, covariance estimates, rebalance frequency controls, financing assumptions.

### 4) Machine-learning approaches

- Examples: gradient-boosted trees, temporal models, ensemble forecasters.
- Pros: can model nonlinear relationships and interactions beyond linear factor models.
- Cons: high overfitting risk, weak interpretability, feature leakage risk if time alignment is poor.
- Data requirements: strict point-in-time feature pipelines, leakage-safe train/validation/test splits, feature-store lineage, robust out-of-sample evaluation.

### Selection guidance for medium/long horizons

1. Prefer strategies with stable out-of-sample behavior across multiple market regimes.
2. Require explicit transaction-cost and slippage assumptions before ranking strategies.
3. Treat ML strategies as complements to factor/trend baselines, not replacements, unless robustness is demonstrated on holdout windows.

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

### Extended Performance Metrics (Issue #3 foundation)
- `annualized_return`: Compounded yearly return implied by periodic returns
- `sortino_ratio`: Downside-volatility-adjusted return
- `calmar_ratio`: Annualized return divided by max drawdown
- `profit_factor`: Gross gains divided by gross losses
- `volatility`: Annualized standard deviation of periodic returns
- `drawdown_duration`: Longest consecutive drawdown period length

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

## Strategy Plugin Architecture

The repository now includes a plugin contract for strategies:

- Base contract: `strategies/plugin_contract.py`
- Discovery/loader: `strategies/plugin_manager.py`

Each plugin provides:

1. Data preparation
2. Backtest execution
3. Metrics computation
4. Recommendation generation

Required plugin metadata includes strategy `name`, `version`, supported asset classes, and holding horizon.