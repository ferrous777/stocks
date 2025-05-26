# API Documentation

## Overview

The Stock Analysis System provides a comprehensive REST API for accessing market data, analysis results, and system information. The API is built with Flask and provides both JSON endpoints and a web interface.

## Base Configuration

**Base URL**: `http://localhost:8090` (development) or your deployed domain  
**Content-Type**: `application/json`  
**CORS**: Enabled for cross-origin requests

## Authentication

Currently, the API does not require authentication. All endpoints are publicly accessible.

## API Endpoints

### Data Access Endpoints

#### GET `/api/symbols`
Returns a list of all available symbols in the system.

**Response**:
```json
[
  "AAPL", "MSFT", "GOOGL", "NVDA", "AMZN", "TSLA", ...
]
```

#### GET `/api/dates`
Returns a list of all available analysis dates.

**Response**:
```json
[
  "20250524", "20250523", "20250522", ...
]
```

#### GET `/api/backtest/<symbol>/<date>`
Get backtest results for a specific symbol and date.

**Parameters**:
- `symbol` (string): Stock symbol (e.g., "AAPL")
- `date` (string): Date in YYYYMMDD format (e.g., "20250524")

**Response**:
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
      "total_returns": 0.0,
      "total_trades": 0,
      "winning_trades": 0,
      "losing_trades": 0,
      "win_rate": 0,
      "final_balance": 10000.0,
      "max_drawdown": 0,
      "sharpe_ratio": 0,
      "first_price": 399.47,
      "last_price": 390.6,
      "trades": []
    },
    "Volume-Price Analysis": {
      // ... similar structure for other strategies
    }
  }
}
```

**Error Response** (404):
```json
{
  "error": "Results not found"
}
```

#### GET `/api/recommendations/<symbol>/<date>`
Get trading recommendations for a specific symbol and date.

**Parameters**:
- `symbol` (string): Stock symbol (e.g., "AAPL")
- `date` (string): Date in YYYYMMDD format (e.g., "20250524")

**Response**:
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

**Error Response** (404):
```json
{
  "error": "Recommendations not found"
}
```

#### GET `/api/historical/<symbol>`
Get historical price data for a symbol.

**Parameters**:
- `symbol` (string): Stock symbol (e.g., "AAPL")

**Response**:
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
    },
    {
      "date": "2025-05-21",
      "open": 133.06,
      "high": 137.40,
      "low": 130.59,
      "close": 131.80,
      "volume": 270608700
    }
  ]
}
```

**Error Response** (404):
```json
{
  "error": "Historical data not found"
}
```

### Symbol Management Endpoints

#### POST `/api/add_ticker`
Add a new ticker symbol to the system.

**Request Body**:
```json
{
  "symbol": "AAPL"
}
```

**Response** (Success):
```json
{
  "success": true,
  "message": "Ticker AAPL added successfully",
  "files_created": [
    "AAPL_recommendations_20250524.json",
    "AAPL_backtest_20250524.json"
  ]
}
```

**Response** (Error):
```json
{
  "success": false,
  "error": "Error message details"
}
```

#### POST `/api/remove_ticker`
Remove a ticker symbol from the system.

**Request Body**:
```json
{
  "symbol": "AAPL"
}
```

**Response** (Success):
```json
{
  "success": true,
  "message": "Ticker AAPL removed successfully"
}
```

**Response** (Error):
```json
{
  "success": false,
  "error": "Error message details"
}
```

### System Information Endpoints

#### GET `/api/store/info`
Get information about the data storage structure and access patterns.

**Response**:
```json
{
  "description": "File-based key/value store for stock analysis data",
  "structure": {
    "historical_data": {
      "location": "cache/",
      "key_pattern": "{symbol}_historical.json",
      "description": "Historical price data for each symbol",
      "example_key": "AAPL_historical.json"
    },
    "recommendations": {
      "location": "results/",
      "key_pattern": "{symbol}_recommendations_{date}.json",
      "description": "Trading recommendations for symbol on specific date",
      "example_key": "AAPL_recommendations_20250524.json"
    },
    "backtest_results": {
      "location": "results/",
      "key_pattern": "{symbol}_backtest_{date}.json",
      "description": "Backtest results for all strategies on symbol for specific date",
      "example_key": "AAPL_backtest_20250524.json"
    }
  },
  "access_patterns": {
    "get_latest": "Iterate through available dates (newest first) to find latest data",
    "get_all_history": "Use glob patterns to find all files for a symbol",
    "get_specific": "Direct file access using symbol and date"
  },
  "current_statistics": {
    "total_symbols": 35,
    "total_dates": 125,
    "cache_files": 35,
    "result_files": 250
  }
}
```

#### GET `/api/store/keys`
List all available keys in the data store.

**Response**:
```json
{
  "historical_keys": [
    "AAPL_historical.json",
    "MSFT_historical.json",
    "GOOGL_historical.json"
  ],
  "recommendation_keys": [
    "AAPL_recommendations_20250524.json",
    "AAPL_recommendations_20250523.json",
    "MSFT_recommendations_20250524.json"
  ],
  "backtest_keys": [
    "AAPL_backtest_20250524.json",
    "AAPL_backtest_20250523.json",
    "MSFT_backtest_20250524.json"
  ]
}
```

#### GET `/health`
Health check endpoint for monitoring system status.

**Response**:
```json
{
  "status": "healthy",
  "timestamp": "2025-05-24T22:51:28.123456",
  "available_symbols": 35,
  "available_dates": 125
}
```

### Comparison and Analysis Endpoints

#### GET `/api/compare/<date>`
Get comparison data for all symbols on a specific date.

**Parameters**:
- `date` (string): Date in YYYYMMDD format (e.g., "20250524")

**Response**:
```json
{
  "date": "20250524",
  "symbols": {
    "AAPL": {
      "backtest": {
        "strategies": {
          "Moving Average Crossover": {
            "total_returns": 0.15,
            "win_rate": 0.65,
            "sharpe_ratio": 1.2
          }
        }
      },
      "recommendations": {
        "action": "BUY",
        "confidence": 0.75,
        "entry_price": 180.50
      }
    },
    "MSFT": {
      // ... similar structure
    }
  }
}
```

## Web Interface Endpoints

### Pages

#### GET `/`
Main dashboard page displaying symbol overview and recent analysis.

#### GET `/symbol/<symbol>/<date>`
Detailed analysis page for a specific symbol and date.

**Parameters**:
- `symbol` (string): Stock symbol
- `date` (string): Date in YYYYMMDD format

#### GET `/ticker/<symbol>`
Comprehensive ticker detail page with historical analysis.

**Parameters**:
- `symbol` (string): Stock symbol

#### GET `/compare`
Multi-symbol comparison interface.

## Error Handling

### HTTP Status Codes

- `200 OK` - Request successful
- `404 Not Found` - Resource not found
- `500 Internal Server Error` - Server error

### Error Response Format

All error responses follow this format:
```json
{
  "error": "Descriptive error message",
  "code": "ERROR_CODE", // Optional
  "details": {} // Optional additional details
}
```

### Common Error Scenarios

1. **Symbol not found**: Invalid or unsupported symbol
2. **Date not available**: No data for the requested date
3. **File not found**: Missing data files
4. **Invalid format**: Malformed request parameters
5. **Server error**: Internal processing errors

## Rate Limiting

Currently, no rate limiting is implemented. For production deployments, consider implementing rate limiting based on your usage requirements.

## Data Freshness

- **Historical data**: Updated daily during market hours
- **Recommendations**: Generated daily after market close
- **Backtest results**: Updated when new strategies are implemented

## Client Libraries and SDKs

### Python Example

```python
import requests

# Get symbols
response = requests.get('http://localhost:8090/api/symbols')
symbols = response.json()

# Get recommendations
response = requests.get('http://localhost:8090/api/recommendations/AAPL/20250524')
recommendations = response.json()

# Add new ticker
response = requests.post('http://localhost:8090/api/add_ticker', 
                        json={'symbol': 'TSLA'})
result = response.json()
```

### JavaScript Example

```javascript
// Get symbols
fetch('/api/symbols')
  .then(response => response.json())
  .then(symbols => console.log(symbols));

// Get recommendations
fetch('/api/recommendations/AAPL/20250524')
  .then(response => response.json())
  .then(data => console.log(data));

// Add new ticker
fetch('/api/add_ticker', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({symbol: 'TSLA'})
})
.then(response => response.json())
.then(result => console.log(result));
```

### cURL Examples

```bash
# Get symbols
curl http://localhost:8090/api/symbols

# Get recommendations
curl http://localhost:8090/api/recommendations/AAPL/20250524

# Add ticker
curl -X POST http://localhost:8090/api/add_ticker \
  -H "Content-Type: application/json" \
  -d '{"symbol": "TSLA"}'

# Health check
curl http://localhost:8090/health
```

## Versioning

The API is currently unversioned. Future versions will include version numbers in the URL path (e.g., `/api/v1/symbols`).

## Support and Contact

For API support, refer to the project documentation or create an issue in the project repository.
