# Data Schemas and Query Patterns

## Overview

This document describes the data structures, schemas, and query patterns used in the Stock Analysis System. The system uses a combination of JSON files and SQLite database for data storage.

## Table of Contents

1. [Storage Architecture](#storage-architecture)
2. [File-Based Data Schemas](#file-based-data-schemas)
3. [Database Schemas](#database-schemas)
4. [Query Patterns](#query-patterns)
5. [Data Models](#data-models)
6. [API Response Formats](#api-response-formats)
7. [Data Validation](#data-validation)

---

## Storage Architecture

### Overview

The system uses a hybrid storage approach:
- **JSON Files**: Historical price data and analysis results
- **SQLite Database**: Time-series data and aggregated metrics
- **File System**: Organized directory structure for easy access

### Directory Structure

```
stocks/
├── cache/                          # Historical price data
│   ├── AAPL_historical.json      # Raw price data per symbol
│   ├── MSFT_historical.json
│   └── ...
├── results/                        # Analysis outputs
│   ├── AAPL_recommendations_20250524.json
│   ├── AAPL_backtest_20250524.json
│   ├── MSFT_recommendations_20250524.json
│   └── ...
├── data/                           # Database files
│   ├── timeseries.db              # SQLite database
│   └── migrations/                # Database migrations
└── logs/                           # System logs
    ├── daily_executions/          # JSON execution logs
    ├── daily_reports/             # Human-readable reports
    └── system logs
```

### Naming Conventions

#### File Naming Patterns
- **Historical Data**: `{SYMBOL}_historical.json`
- **Recommendations**: `{SYMBOL}_recommendations_{YYYYMMDD}.json`
- **Backtest Results**: `{SYMBOL}_backtest_{YYYYMMDD}.json`
- **Execution Logs**: `execution_{YYYY-MM-DD}.json`
- **Daily Reports**: `report_{YYYY-MM-DD}.txt`

#### Key Patterns
- **Symbol Keys**: Uppercase ticker symbols (e.g., "AAPL", "MSFT")
- **Date Keys**: ISO format YYYY-MM-DD for storage, YYYYMMDD for filenames
- **Strategy Keys**: Descriptive names (e.g., "Moving Average Crossover")

---

## File-Based Data Schemas

### Historical Price Data Schema

**File Pattern**: `cache/{SYMBOL}_historical.json`

```json
{
  "symbol": "NVDA",
  "data_points": [
    {
      "date": "2025-05-20",
      "open": 134.29,
      "high": 134.58,
      "low": 132.62,
      "close": 134.38,
      "volume": 161514200
    }
  ]
}
```

**Field Specifications**:
- `symbol` (string): Stock ticker symbol (uppercase)
- `data_points` (array): Chronological price data
  - `date` (string): ISO date format YYYY-MM-DD
  - `open` (float): Opening price
  - `high` (float): Highest price of the day
  - `low` (float): Lowest price of the day
  - `close` (float): Closing price
  - `volume` (integer): Trading volume

### Trading Recommendations Schema

**File Pattern**: `results/{SYMBOL}_recommendations_{YYYYMMDD}.json`

```json
{
  "symbol": "NVDA",
  "analysis_date": "2025-05-24",
  "recommendations": {
    "action": "BUY",
    "confidence": 0.67,
    "entry_price": 306.31,
    "stop_loss": 281.81,
    "take_profit": 343.07,
    "reasoning": "Technical analysis for NVDA shows buy signal with strong momentum indicators."
  }
}
```

**Field Specifications**:
- `symbol` (string): Stock ticker symbol
- `analysis_date` (string): Date of analysis (YYYY-MM-DD)
- `recommendations` (object): Trading recommendation details
  - `action` (enum): "BUY", "SELL", "HOLD"
  - `confidence` (float): Confidence score (0.0 to 1.0)
  - `entry_price` (float): Recommended entry price
  - `stop_loss` (float): Stop loss price level
  - `take_profit` (float): Take profit target price
  - `reasoning` (string): Human-readable explanation

### Backtest Results Schema

**File Pattern**: `results/{SYMBOL}_backtest_{YYYYMMDD}.json`

```json
{
  "symbol": "NVDA",
  "date_run": "2025-05-24 22:51:28",
  "period": {
    "start": "2022-05-25",
    "end": "2025-05-24"
  },
  "strategies": {
    "Moving Average Crossover": {
      "total_returns": 0.15,
      "total_trades": 45,
      "winning_trades": 28,
      "losing_trades": 17,
      "win_rate": 0.62,
      "final_balance": 11500.0,
      "max_drawdown": 0.08,
      "sharpe_ratio": 1.25,
      "first_price": 399.47,
      "last_price": 390.6,
      "trades": [
        {
          "entry_date": "2022-06-01",
          "exit_date": "2022-06-15",
          "entry_price": 180.50,
          "exit_price": 195.20,
          "shares": 100,
          "profit_loss": 1470.0,
          "return_pct": 0.081
        }
      ]
    },
    "Volume-Price Analysis": {
      // Similar structure for other strategies
    }
  }
}
```

**Field Specifications**:
- `symbol` (string): Stock ticker symbol
- `date_run` (string): Execution timestamp
- `period` (object): Analysis time period
  - `start` (string): Start date (YYYY-MM-DD)
  - `end` (string): End date (YYYY-MM-DD)
- `strategies` (object): Results for each trading strategy
  - `{strategy_name}` (object): Strategy-specific results
    - `total_returns` (float): Total return percentage
    - `total_trades` (integer): Number of trades executed
    - `winning_trades` (integer): Number of profitable trades
    - `losing_trades` (integer): Number of losing trades
    - `win_rate` (float): Win rate (0.0 to 1.0)
    - `final_balance` (float): Final portfolio balance
    - `max_drawdown` (float): Maximum drawdown percentage
    - `sharpe_ratio` (float): Sharpe ratio
    - `first_price` (float): First price in period
    - `last_price` (float): Last price in period
    - `trades` (array): Individual trade records

### Trade Record Schema

```json
{
  "entry_date": "2022-06-01",
  "exit_date": "2022-06-15",
  "entry_price": 180.50,
  "exit_price": 195.20,
  "shares": 100,
  "profit_loss": 1470.0,
  "return_pct": 0.081,
  "strategy": "Moving Average Crossover",
  "signal_strength": 0.75
}
```

---

## Database Schemas

### SQLite Table Structures

#### daily_snapshots Table

```sql
CREATE TABLE daily_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    date TEXT NOT NULL,
    open_price REAL,
    high_price REAL,
    low_price REAL,
    close_price REAL,
    volume INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(symbol, date)
);
```

#### strategy_performance Table

```sql
CREATE TABLE strategy_performance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    date TEXT NOT NULL,
    strategy_name TEXT NOT NULL,
    total_returns REAL,
    win_rate REAL,
    sharpe_ratio REAL,
    max_drawdown REAL,
    total_trades INTEGER,
    confidence_score REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(symbol, date, strategy_name)
);
```

#### recommendations Table

```sql
CREATE TABLE recommendations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    date TEXT NOT NULL,
    action TEXT NOT NULL,
    confidence REAL,
    entry_price REAL,
    stop_loss REAL,
    take_profit REAL,
    reasoning TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(symbol, date)
);
```

#### trade_history Table

```sql
CREATE TABLE trade_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    strategy_name TEXT NOT NULL,
    entry_date TEXT NOT NULL,
    exit_date TEXT,
    entry_price REAL,
    exit_price REAL,
    shares INTEGER,
    profit_loss REAL,
    return_pct REAL,
    signal_strength REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## Query Patterns

### Common Query Patterns

#### 1. Get Latest Data for Symbol

```python
# File-based approach
def get_latest_recommendations(symbol):
    pattern = f"results/{symbol}_recommendations_*.json"
    files = sorted(glob.glob(pattern), reverse=True)
    if files:
        with open(files[0]) as f:
            return json.load(f)
    return None

# Database approach
def get_latest_recommendations_db(symbol):
    query = """
    SELECT * FROM recommendations 
    WHERE symbol = ? 
    ORDER BY date DESC 
    LIMIT 1
    """
    return db.execute(query, (symbol,)).fetchone()
```

#### 2. Get Historical Performance

```python
def get_performance_history(symbol, strategy, days=30):
    query = """
    SELECT date, total_returns, win_rate, sharpe_ratio
    FROM strategy_performance
    WHERE symbol = ? AND strategy_name = ?
    AND date >= date('now', '-{} days')
    ORDER BY date DESC
    """.format(days)
    return db.execute(query, (symbol, strategy)).fetchall()
```

#### 3. Compare Symbols Performance

```python
def compare_symbols_performance(symbols, date):
    query = """
    SELECT symbol, strategy_name, total_returns, win_rate
    FROM strategy_performance
    WHERE symbol IN ({}) AND date = ?
    ORDER BY total_returns DESC
    """.format(','.join('?' * len(symbols)))
    return db.execute(query, symbols + [date]).fetchall()
```

#### 4. Find Data Gaps

```python
def find_data_gaps(symbol, start_date, end_date):
    query = """
    WITH RECURSIVE date_range(date) AS (
        SELECT ?
        UNION ALL
        SELECT date(date, '+1 day')
        FROM date_range
        WHERE date < ?
    )
    SELECT dr.date
    FROM date_range dr
    LEFT JOIN daily_snapshots ds ON dr.date = ds.date AND ds.symbol = ?
    WHERE ds.date IS NULL
    """
    return db.execute(query, (start_date, end_date, symbol)).fetchall()
```

### Aggregation Queries

#### Rolling Performance Metrics

```python
def get_rolling_metrics(symbol, strategy, window_days=30):
    query = """
    SELECT 
        date,
        AVG(total_returns) OVER (
            ORDER BY date 
            ROWS BETWEEN ? PRECEDING AND CURRENT ROW
        ) as avg_returns,
        AVG(win_rate) OVER (
            ORDER BY date 
            ROWS BETWEEN ? PRECEDING AND CURRENT ROW
        ) as avg_win_rate
    FROM strategy_performance
    WHERE symbol = ? AND strategy_name = ?
    ORDER BY date
    """
    return db.execute(query, (window_days-1, window_days-1, symbol, strategy)).fetchall()
```

#### Performance Rankings

```python
def get_strategy_rankings(date):
    query = """
    SELECT 
        strategy_name,
        COUNT(*) as symbol_count,
        AVG(total_returns) as avg_returns,
        AVG(win_rate) as avg_win_rate,
        RANK() OVER (ORDER BY AVG(total_returns) DESC) as rank
    FROM strategy_performance
    WHERE date = ?
    GROUP BY strategy_name
    ORDER BY avg_returns DESC
    """
    return db.execute(query, (date,)).fetchall()
```

---

## Data Models

### Python Data Models

#### DailySnapshot Model

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass
class DailySnapshot:
    symbol: str
    date: str
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: int
    created_at: Optional[datetime] = None
    
    def to_dict(self):
        return {
            'symbol': self.symbol,
            'date': self.date,
            'open': self.open_price,
            'high': self.high_price,
            'low': self.low_price,
            'close': self.close_price,
            'volume': self.volume
        }
```

#### StrategyPerformance Model

```python
@dataclass
class StrategyPerformance:
    symbol: str
    date: str
    strategy_name: str
    total_returns: float
    win_rate: float
    sharpe_ratio: float
    max_drawdown: float
    total_trades: int
    confidence_score: Optional[float] = None
    
    def performance_grade(self) -> str:
        if self.total_returns > 0.15 and self.win_rate > 0.6:
            return 'A'
        elif self.total_returns > 0.1 and self.win_rate > 0.5:
            return 'B'
        elif self.total_returns > 0.05:
            return 'C'
        else:
            return 'D'
```

#### TradingRecommendation Model

```python
from enum import Enum

class Action(Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"

@dataclass
class TradingRecommendation:
    symbol: str
    date: str
    action: Action
    confidence: float
    entry_price: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    reasoning: Optional[str] = None
    
    def risk_reward_ratio(self) -> Optional[float]:
        if self.stop_loss and self.take_profit:
            risk = abs(self.entry_price - self.stop_loss)
            reward = abs(self.take_profit - self.entry_price)
            return reward / risk if risk > 0 else None
        return None
```

---

## API Response Formats

### Standard Response Wrapper

```json
{
  "data": {}, // Main response data
  "metadata": {
    "timestamp": "2025-05-24T22:51:28.123456",
    "version": "1.0",
    "source": "stock_analysis_system"
  },
  "pagination": { // For paginated responses
    "page": 1,
    "per_page": 50,
    "total": 150,
    "has_next": true
  }
}
```

### Error Response Format

```json
{
  "error": {
    "code": "SYMBOL_NOT_FOUND",
    "message": "Symbol 'INVALID' not found in system",
    "details": {
      "available_symbols": ["AAPL", "MSFT", "GOOGL"],
      "suggestion": "Use /api/symbols to get valid symbols"
    }
  },
  "metadata": {
    "timestamp": "2025-05-24T22:51:28.123456",
    "request_id": "req_123456"
  }
}
```

---

## Data Validation

### Validation Rules

#### Symbol Validation
```python
import re

def validate_symbol(symbol: str) -> bool:
    """Validate stock symbol format"""
    if not symbol or not isinstance(symbol, str):
        return False
    
    # Allow 1-5 uppercase letters
    pattern = r'^[A-Z]{1,5}$'
    return bool(re.match(pattern, symbol.upper()))
```

#### Date Validation
```python
from datetime import datetime

def validate_date(date_str: str) -> bool:
    """Validate date format YYYY-MM-DD"""
    try:
        datetime.strptime(date_str, '%Y-%m-%d')
        return True
    except ValueError:
        return False

def validate_trading_date(date_str: str) -> bool:
    """Validate that date is a trading day"""
    from src.utils.market_calendar import MarketCalendar
    calendar = MarketCalendar()
    return calendar.is_trading_day(date_str)
```

#### Price Validation
```python
def validate_price_data(data: dict) -> bool:
    """Validate price data structure"""
    required_fields = ['open', 'high', 'low', 'close', 'volume']
    
    # Check required fields exist
    if not all(field in data for field in required_fields):
        return False
    
    # Validate price logic: high >= low, close between high/low
    try:
        high, low, close = data['high'], data['low'], data['close']
        return high >= low and low <= close <= high
    except (TypeError, KeyError):
        return False
```

### Data Integrity Checks

#### File Integrity
```python
import json
import hashlib

def verify_json_integrity(filepath: str) -> bool:
    """Verify JSON file is valid and uncorrupted"""
    try:
        with open(filepath, 'r') as f:
            json.load(f)
        return True
    except (json.JSONDecodeError, IOError):
        return False

def calculate_file_checksum(filepath: str) -> str:
    """Calculate file checksum for integrity verification"""
    with open(filepath, 'rb') as f:
        return hashlib.md5(f.read()).hexdigest()
```

#### Database Integrity
```python
def check_database_integrity():
    """Check SQLite database integrity"""
    query = "PRAGMA integrity_check"
    result = db.execute(query).fetchone()
    return result[0] == 'ok'

def validate_foreign_keys():
    """Validate foreign key constraints"""
    db.execute("PRAGMA foreign_key_check")
    violations = db.fetchall()
    return len(violations) == 0
```

---

## Performance Considerations

### Indexing Strategy

```sql
-- Primary indexes for common queries
CREATE INDEX idx_daily_snapshots_symbol_date ON daily_snapshots(symbol, date);
CREATE INDEX idx_strategy_performance_symbol_date ON strategy_performance(symbol, date);
CREATE INDEX idx_recommendations_symbol_date ON recommendations(symbol, date);

-- Composite indexes for complex queries
CREATE INDEX idx_performance_strategy_returns ON strategy_performance(strategy_name, total_returns DESC);
CREATE INDEX idx_trades_symbol_strategy_date ON trade_history(symbol, strategy_name, entry_date);
```

### Query Optimization

#### Efficient Date Range Queries
```python
# Use BETWEEN for date ranges
query = """
SELECT * FROM daily_snapshots 
WHERE symbol = ? AND date BETWEEN ? AND ?
ORDER BY date
"""

# Use LIMIT for pagination
query = """
SELECT * FROM strategy_performance 
WHERE symbol = ? 
ORDER BY date DESC 
LIMIT ? OFFSET ?
"""
```

#### Batch Operations
```python
# Batch inserts for better performance
def batch_insert_snapshots(snapshots):
    query = """
    INSERT OR REPLACE INTO daily_snapshots 
    (symbol, date, open_price, high_price, low_price, close_price, volume)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """
    data = [(s.symbol, s.date, s.open_price, s.high_price, 
             s.low_price, s.close_price, s.volume) for s in snapshots]
    db.executemany(query, data)
    db.commit()
```

---

## Migration and Versioning

### Schema Migrations

#### Migration Script Template
```python
def migrate_v1_to_v2():
    """Migration from schema version 1 to 2"""
    # Add new columns
    db.execute("ALTER TABLE daily_snapshots ADD COLUMN adjusted_close REAL")
    
    # Create new tables
    db.execute("""
    CREATE TABLE IF NOT EXISTS market_events (
        id INTEGER PRIMARY KEY,
        date TEXT NOT NULL,
        event_type TEXT NOT NULL,
        description TEXT
    )
    """)
    
    # Update schema version
    db.execute("UPDATE schema_info SET version = 2")
    db.commit()
```

### Data Format Versioning

#### Version Headers
```json
{
  "schema_version": "2.1",
  "format_version": "1.0",
  "data": {
    // Actual data content
  }
}
```

---

## Related Documentation

- [API Documentation](api_documentation.md) - REST API endpoints and usage
- [Operational Runbooks](operational_runbooks.md) - System operations and maintenance
- [Troubleshooting Guide](troubleshooting_guide.md) - Common issues and solutions
