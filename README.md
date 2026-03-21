# Stock Analysis Dashboard

A comprehensive stock and mutual fund analysis system with automated daily data collection, multi-strategy backtesting, and a modern web interface.

## Features

- **Automated Daily Data Collection** - Incremental data fetching that only pulls missing data
- **Multi-Strategy Analysis** - Momentum, mean reversion, and breakout strategies
- **Mutual Fund Prospectus** - Detailed 1, 3, 5, and 10 year performance analysis
- **Web Dashboard** - Modern Flask-based interface for viewing analysis results
- **Market Calendar Integration** - Automatically handles holidays and weekends
- **PythonAnywhere Ready** - Optimized for cloud deployment with scheduled tasks
- **Plaid Portfolio Sync** - Connects to your real brokerage account to track live holdings and transactions
- **Multi-Channel Alerts** - Email, SMS (Twilio), and Telegram notifications for predictions, stop-loss breaches, and trade parameter changes

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
├── alerts/                   # Alert delivery system
│   ├── alert_engine.py       # Rule evaluation + dispatch orchestrator
│   ├── alert_models.py       # Alert data models (AlertType, Alert)
│   ├── position_monitor.py   # Stop-loss / take-profit / drift detection
│   ├── email_sender.py       # SMTP email delivery
│   ├── sms_sender.py         # Twilio SMS delivery (URGENT alerts only)
│   └── telegram_sender.py    # Telegram bot delivery
├── config/                   # Configuration management
├── data/                     # Database and data files
├── docs/                     # Documentation
├── market_data/              # Market data fetching
├── plaid_integration/        # Plaid brokerage sync
│   ├── plaid_client.py       # API client + Fernet token encryption
│   ├── accounts.py           # Holdings sync → portfolio_positions table
│   └── transactions.py       # Investment transaction sync
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
| `GET /plaid/link-token` | Create a Plaid Link Token (step 1 of broker connection) |
| `POST /plaid/exchange-token` | Exchange public token for access token (step 2) |
| `POST /plaid/sync` | Manually trigger Plaid accounts + holdings + transactions sync |
| `GET /api/portfolio` | Current holdings with live P&L and model recommendation overlay |
| `GET /api/portfolio/transactions` | Investment transaction history (filterable by symbol/date) |
| `GET /api/portfolio/accounts` | All synced Plaid accounts |

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

---

## Plaid Integration (Portfolio Sync)

Connect your real brokerage account so the app tracks what you actually hold, auto-adds newly-detected tickers to the watchlist, and uses your live positions as the anchor for alert rules.

### 1. Create a Plaid account

Sign up at [dashboard.plaid.com](https://dashboard.plaid.com) (free). Start with the **Sandbox** environment — use test credentials `user_good / pass_good` to simulate a brokerage account.

### 2. Generate an encryption key

The access token returned by Plaid is encrypted with Fernet before being stored in the database. Generate a key once and store it as an environment variable — **never commit it to the repo**.

```bash
python - <<'EOF'
from plaid_integration.plaid_client import generate_fernet_key
print(generate_fernet_key())
EOF
```

### 3. Set environment variables

```bash
# Required
export PLAID_CLIENT_ID="your_client_id"
export PLAID_SECRET="your_sandbox_secret"
export PLAID_FERNET_KEY="the_key_you_generated_above"

# Optional — defaults to "sandbox"
export PLAID_ENVIRONMENT="sandbox"   # sandbox | development | production

# Optional — stable user identifier for Plaid Link
export PLAID_USER_ID="my-app-user-1"
```

On **PythonAnywhere**, set these in *Web → Environment variables* or in your `.env` file loaded at startup.

### 4. Connect a brokerage account (Plaid Link flow)

Add the [Plaid Link JS widget](https://plaid.com/docs/link/) to any page, or run this quick flow from the browser console / curl:

```bash
# Step 1 — Get a Link Token
curl http://localhost:8090/plaid/link-token

# → { "link_token": "link-sandbox-..." }
# Pass that token to the Plaid Link widget in the browser.
# After the user selects their institution and logs in, Plaid returns a public_token.

# Step 2 — Exchange for an access token (stored encrypted in the DB)
curl -X POST http://localhost:8090/plaid/exchange-token \
  -H "Content-Type: application/json" \
  -d '{"public_token": "public-sandbox-...", "institution_name": "Chase"}'

# → { "item_id": "...", "institution_name": "Chase", "status": "connected" }
```

### 5. Trigger a manual sync

```bash
curl -X POST http://localhost:8090/plaid/sync
# → { "accounts": 2, "positions": 8, "new_symbols": ["TSLA"], "new_transactions": 14 }
```

Sync also runs automatically as **Step 5** of the daily scheduler after market close.

### What gets synced

| Data | Plaid endpoint | DB table |
|---|---|---|
| Brokerage accounts (balance) | `/investments/holdings/get` | `plaid_accounts` |
| Current equity holdings | `/investments/holdings/get` | `portfolio_positions` |
| Investment transactions | `/investments/transactions/get` | `investment_transactions` |

New equity tickers detected in your holdings are automatically added to `config/system_config.yaml` with `priority: 2` so they flow into the next daily analysis run.

### Moving to Production

Change one line in `config/system_config.yaml`:

```yaml
plaid:
  environment: production   # was: sandbox
```

Or set `PLAID_ENVIRONMENT=production`. No code changes needed.

---

## Alert System

Five event types are monitored and dispatched to Email, SMS, and/or Telegram.

### Alert types

| Type | Severity | Channels | When it fires |
|---|---|---|---|
| `HIGH_CONFIDENCE_PREDICTION` | INFO | Email digest + Telegram | New ≥80% confidence BUY/SELL signal on a symbol you don't already hold |
| `STOP_LOSS_BREACH` | **URGENT** | Email immediately + SMS + Telegram | `current_price < stop_loss` from your entry snapshot |
| `TAKE_PROFIT_REACHED` | **URGENT** | Email immediately + SMS + Telegram | `current_price >= take_profit` from your entry snapshot |
| `POSITION_PARAMS_CHANGED` | INFO | Email digest + Telegram | Stop/target moved >5%, confidence dropped >15 pp, or action flipped to EXIT |
| `DAILY_SUMMARY` | INFO | Email digest + Telegram | All open positions with current P&L and model alignment — sent each trading day |

URGENT alerts are always sent immediately to every enabled channel. INFO alerts are batched into a single daily email digest; Telegram receives them individually.

### Enable alerts in config

Open `config/system_config.yaml` and set `alerts.enabled: true`, then enable each channel:

```yaml
alerts:
  enabled: true
  prediction_confidence_threshold: 0.80   # Minimum confidence for new-prediction alerts
  parameter_change_pct: 0.05              # 5% move in stop/target triggers drift alert
  confidence_drop_threshold: 0.15         # 15 pp confidence drop triggers drift alert

  email:
    enabled: true
    smtp_host: smtp.gmail.com
    smtp_port: 587
    from_address: you@gmail.com
    recipients:
      - you@gmail.com
    # Use app-specific password for Gmail, or set ALERT_SMTP_USER / ALERT_SMTP_PASSWORD env vars

  sms:
    enabled: true
    # Credentials via env vars: TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER
    recipients:
      - "+15551234567"

  telegram:
    enabled: true
    # Token via env var: TELEGRAM_BOT_TOKEN
    # Find your chat_id by messaging @userinfobot in Telegram
    chat_ids:
      - 123456789
```

### Set alert credentials via environment variables

```bash
# Email (SMTP)
export ALERT_SMTP_USER="you@gmail.com"
export ALERT_SMTP_PASSWORD="your_app_password"

# Twilio SMS
export TWILIO_ACCOUNT_SID="ACxxxxx"
export TWILIO_AUTH_TOKEN="your_auth_token"
export TWILIO_FROM_NUMBER="+15557654321"

# Telegram
export TELEGRAM_BOT_TOKEN="123456789:ABCdef..."
```

### Test alerts manually

```python
# Run from the project root
from storage.timeseries_db import TimeSeriesDB
from config.config_manager import ConfigManager
from alerts.alert_engine import AlertEngine

config = ConfigManager().get_config()
config.alerts.enabled = True      # override for testing
db = TimeSeriesDB()

engine = AlertEngine(db, config)
# Fire a test daily summary (uses whatever positions are in the DB)
engine.run(include_daily_summary=True)
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
