# Stock Analysis Dashboard

A comprehensive stock and mutual fund analysis system with automated daily data collection, multi-strategy backtesting, and a modern web interface.

## Features

- **Automated Daily Data Collection** - Incremental data fetching that only pulls missing data
- **Multi-Strategy Analysis** - Momentum, mean reversion, and breakout strategies
- **Mutual Fund Prospectus** - Detailed 1, 3, 5, and 10 year performance analysis
- **Web Dashboard** - Modern Flask-based interface for viewing analysis results
- **Market Calendar Integration** - Automatically handles holidays and weekends
- **PythonAnywhere Ready** - Optimized for cloud deployment with scheduled tasks

## Quick Start

### Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/stocks.git
cd stocks

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate  # On macOS/Linux
# venv\Scripts\activate   # On Windows

# Install dependencies
pip install -r requirements.txt
```

### Activating the Environment

Each time you open a new terminal for development:

```bash
cd stocks
source venv/bin/activate  # On macOS/Linux
# venv\Scripts\activate   # On Windows
```

### Run the Web Server

```bash
# Start the Flask development server
python app.py

# Access at http://localhost:8090
```

### Run Daily Analysis

```bash
# Run the daily scheduler
python scheduler/daily_scheduler.py

# Or force run on non-trading days
python pythonanywhere_daily_hook.py --force
```

## Project Structure

```
stocks/
├── app.py                    # Flask web application
├── main.py                   # CLI entry point
├── analysis/                 # Data analysis modules
│   ├── aggregation.py        # Data aggregation
│   └── fund_analyzer.py      # Mutual fund prospectus analysis
├── config/                   # Configuration management
├── data/                     # Database and data files
├── docs/                     # Documentation
├── market_data/              # Market data fetching
├── scheduler/                # Daily scheduler
├── storage/                  # Database adapters
├── strategies/               # Trading strategies
├── templates/                # HTML templates
└── tests/                    # Test suite
```

## Web Interface

### Dashboard (`/`)
Overview of all tracked symbols with filtering and analysis summaries.

### Ticker Detail (`/ticker/<symbol>`)
Comprehensive analysis for individual stocks including:
- Current recommendations
- Strategy performance
- Historical data visualization

### Fund Prospectus (`/fund/<symbol>`)
Mutual fund and ETF analysis with:
- 1, 3, 5, 10 year performance metrics
- Risk analysis (beta, alpha, Sharpe ratio)
- Benchmark comparison (vs S&P 500)
- Fund metadata (expense ratio, holdings)

### Compare (`/compare`)
Side-by-side comparison of multiple symbols.

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/symbols` | List available symbols |
| `GET /api/dates` | List available analysis dates |
| `GET /api/backtest/<symbol>/<date>` | Get backtest results |
| `GET /api/recommendations/<symbol>/<date>` | Get recommendations |
| `GET /api/historical/<symbol>` | Get historical data |
| `GET /api/fund/<symbol>/prospectus` | Get fund prospectus data |
| `GET /api/fund/<symbol>/info` | Get fund metadata |
| `GET /health` | Health check |

## Configuration

### Symbol Management

Symbols are configured in `config/system_config.yaml`:

```yaml
symbols:
  - symbol: AAPL
    enabled: true
    priority: 1
    sector: Technology
  - symbol: QQQ
    enabled: true
    priority: 2
    sector: ETF
```

### Adding/Removing Symbols

Use the API endpoints or modify the config directly:

```bash
# Via API
curl -X POST http://localhost:8090/api/add_ticker \
  -H "Content-Type: application/json" \
  -d '{"symbol": "TSLA", "sector": "Technology"}'
```

## Deployment

### PythonAnywhere

See [docs/pythonanywhere_deployment.md](docs/pythonanywhere_deployment.md) for detailed deployment instructions.

Quick setup:
1. Upload code to PythonAnywhere
2. Install dependencies: `pip3.10 install --user -r requirements.txt`
3. Schedule daily task: `python3.10 pythonanywhere_daily_hook.py`

### Production

For production deployments:

```bash
# Using Gunicorn
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

## Documentation

- [API Documentation](docs/api_documentation.md)
- [Deployment Guide](docs/pythonanywhere_deployment.md)
- [Troubleshooting](docs/troubleshooting_guide.md)
- [Data Schemas](docs/data_schemas.md)

## License

MIT License - See LICENSE file for details.
