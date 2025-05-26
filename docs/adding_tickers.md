# How to Add New Tickers to the Stock Analysis System

## Overview
The system automatically discovers available tickers by scanning files in two directories:
- `cache/` - Contains historical price data
- `results/` - Contains analysis results (recommendations and backtests)

## Required Files for Each Ticker

### 1. Historical Data File (Required)
**Location:** `cache/{SYMBOL}_historical.json`

**Format:**
```json
{
  "symbol": "SYMBOL", 
  "data_points": [
    {
      "date": "2025-05-23",
      "open": 150.00,
      "high": 152.50,
      "low": 149.00, 
      "close": 151.25,
      "volume": 1000000
    },
    // ... more data points
  ]
}
```

### 2. Recommendations File (Optional but recommended)
**Location:** `results/{SYMBOL}_recommendations_{YYYYMMDD}.json`

**Format:**
```json
{
  "symbol": "SYMBOL",
  "date_run": "2025-05-24 10:30:00",
  "recommendations": {
    "action": "BUY",           // BUY, SELL, HOLD, STRONG_BUY, STRONG_SELL
    "type": "LONG",            // LONG, SHORT
    "confidence": 0.75,        // 0.0 to 1.0
    "entry_price": 151.25,
    "stop_loss": 145.00,
    "take_profit": 160.00,
    "reasoning": "Strong technical indicators suggest upward momentum",
    "supporting_strategies": ["Moving Average Crossover", "RSI"]
  }
}
```

### 3. Backtest File (Optional)
**Location:** `results/{SYMBOL}_backtest_{YYYYMMDD}.json`

**Format:**
```json
{
  "symbol": "SYMBOL",
  "date_run": "2025-05-24 10:30:00",
  "period": {
    "start": "2022-05-24",
    "end": "2025-05-24"
  },
  "strategies": {
    "Moving Average Crossover": {
      "total_returns": 15.25,
      "total_trades": 42,
      "winning_trades": 28,
      "losing_trades": 14,
      "final_balance": 11525.00,
      // ... more strategy results
    }
  }
}
```

## Step-by-Step Process to Add New Tickers

### Method 1: Manual Addition

1. **Create Historical Data File**
   ```bash
   # Create the cache file with historical data
   cat > cache/TSLA_historical.json << 'EOF'
   {
     "symbol": "TSLA",
     "data_points": [
       {
         "date": "2025-05-23",
         "open": 180.50,
         "high": 185.25,
         "low": 178.00,
         "close": 182.75,
         "volume": 2500000
       }
     ]
   }
   EOF
   ```

2. **Create Recommendations File**
   ```bash
   # Create recommendations for current date
   cat > results/TSLA_recommendations_20250524.json << 'EOF'
   {
     "symbol": "TSLA",
     "date_run": "2025-05-24 10:00:00",
     "recommendations": {
       "action": "BUY",
       "confidence": 0.80,
       "entry_price": 182.75,
       "stop_loss": 175.00,
       "take_profit": 195.00,
       "reasoning": "Electric vehicle sector showing strong growth"
     }
   }
   EOF
   ```

3. **Restart the Flask Server**
   ```bash
   # The system will automatically pick up the new ticker
   python app.py
   ```

### Method 2: Automated Addition (Recommended)

Create a helper script to fetch data and add tickers:

```python
#!/usr/bin/env python3
"""
Add new ticker to the system with real data
"""
import yfinance as yf
import json
import os
from datetime import datetime

def add_ticker(symbol):
    # 1. Fetch historical data
    ticker = yf.Ticker(symbol)
    hist = ticker.history(period="3y")  # 3 years of data
    
    # 2. Convert to our format
    data_points = []
    for date, row in hist.iterrows():
        data_points.append({
            "date": date.strftime("%Y-%m-%d"),
            "open": float(row['Open']),
            "high": float(row['High']),
            "low": float(row['Low']),
            "close": float(row['Close']),
            "volume": int(row['Volume'])
        })
    
    # 3. Save historical data
    cache_data = {
        "symbol": symbol,
        "data_points": data_points
    }
    
    with open(f"cache/{symbol}_historical.json", "w") as f:
        json.dump(cache_data, f)
    
    # 4. Create basic recommendation
    current_price = data_points[-1]["close"]
    rec_data = {
        "symbol": symbol,
        "date_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "recommendations": {
            "action": "HOLD",
            "confidence": 0.5,
            "entry_price": current_price,
            "reasoning": f"Initial tracking setup for {symbol}"
        }
    }
    
    today = datetime.now().strftime("%Y%m%d")
    with open(f"results/{symbol}_recommendations_{today}.json", "w") as f:
        json.dump(rec_data, f, indent=2)
    
    print(f"✓ Added {symbol} to tracking system")

# Usage:
# add_ticker("TSLA")
# add_ticker("NVDA")
```

## Fund/ETF Classification

If adding mutual funds or ETFs, update the `FUND_SYMBOLS` array in the template:

```javascript
// In templates/index.html
const FUND_SYMBOLS = ['QQQ', 'SPYG', 'VEA', 'VGT', 'VUG', 'NEW_FUND_SYMBOL'];
```

## System Discovery

The system automatically discovers tickers by:

1. **`get_available_symbols()`** - Scans `cache/*_historical.json` files
2. **`get_available_dates()`** - Scans `results/*_backtest_*.json` files  
3. **Flask routes** - Serve data based on available files

## Testing New Tickers

After adding files:

1. **Check Symbol Detection**
   ```bash
   curl http://127.0.0.1:8090/ | grep "NEW_SYMBOL"
   ```

2. **Test API Endpoints**
   ```bash
   curl http://127.0.0.1:8090/api/recommendations/NEW_SYMBOL/20250524
   curl http://127.0.0.1:8090/api/backtest/NEW_SYMBOL/20250524
   ```

3. **Verify in Dashboard**
   - Visit http://127.0.0.1:8090
   - Look for the new ticker in the table
   - Check if recommendations appear

## Common Issues

1. **Symbol Not Appearing**: Check that `cache/{SYMBOL}_historical.json` exists
2. **No Recommendations**: Create `results/{SYMBOL}_recommendations_{DATE}.json`
3. **Invalid JSON**: Validate JSON syntax with `python -m json.tool file.json`
4. **Date Format**: Use YYYYMMDD format for dates in filenames

## Bulk Addition

To add multiple tickers at once:

```bash
# List of symbols
SYMBOLS=("TSLA" "NVDA" "META" "GOOGL" "AMZN")

for symbol in "${SYMBOLS[@]}"; do
    echo "Adding $symbol..."
    # Run your addition script here
    python add_ticker_script.py "$symbol"
done
```

The system will automatically pick up new tickers on the next page refresh!
