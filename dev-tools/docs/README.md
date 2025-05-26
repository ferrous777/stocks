# Market Analysis Tool Documentation

## Components
- [Backtesting System](backtest.md)
- [Market Data](market_data.md)
- [Trading Strategies](strategies.md)

## Symbol Configuration & Prioritization

The system uses a configuration-based approach to manage trading symbols with priority-based categorization. This allows for efficient resource allocation and focused analysis on the most important symbols.

### Symbol Priority Levels

#### Priority 1 (High Priority)
Focus symbols for active trading and detailed analysis:
- **AAPL** - Apple Inc. (Technology)
- **MSFT** - Microsoft Corporation (Technology)
- **GOOGL** - Alphabet Inc. (Technology)
- **AMZN** - Amazon.com Inc. (Technology)
- **NVDA** - NVIDIA Corporation (Technology)
- **COST** - Costco Wholesale Corporation (Consumer Staples)

#### Priority 2 (Medium Priority)
ETFs for diversified exposure and market tracking:
- **QQQ** - Invesco QQQ Trust (NASDAQ-100 ETF)
- **VUG** - Vanguard Growth ETF
- **IWF** - iShares Russell 1000 Growth ETF
- **SPYG** - SPDR Portfolio S&P 500 Growth ETF
- **VGT** - Vanguard Information Technology ETF
- **FDN** - First Trust Dow Jones Internet Index Fund
- **VEA** - Vanguard Developed Markets Index Fund
- **VWO** - Vanguard Emerging Markets Stock Index Fund
- **FEZ** - SPDR EURO STOXX 50 ETF
- **EWJ** - iShares MSCI Japan ETF
- **MCHI** - iShares MSCI China ETF
- **INDA** - iShares MSCI India Small-Cap ETF
- **EWZ** - iShares MSCI Brazil ETF

#### Priority 3 (Low Priority)
Mutual funds for long-term analysis:
- **KMKNX** - Kinetics Market Opportunities Fund
- **FDEGX** - Fidelity Emerging Markets Fund

### Configuration Management

The symbol configuration is managed through:
- **System Config**: `/config/system_config.yaml` - Main configuration file
- **Source Data**: `/src/data/default_symbols.json` - Symbol definitions
- **CLI Tool**: `config_cli.py` - Command-line interface for configuration management

#### Using the Configuration CLI

```bash
# List all configured symbols
python config_cli.py list

# Add a new symbol with priority
python config_cli.py add TSLA --category individual_stocks --priority 1

# Remove a symbol
python config_cli.py remove TSLA

# Enable/disable a symbol
python config_cli.py enable AAPL
python config_cli.py disable AAPL

# Update symbols from default_symbols.json
python update_symbols.py
```

### Data Storage

The system uses a time-series SQLite database (`/data/timeseries.db`) for efficient historical data storage and retrieval, replacing the previous JSON-based cache system.

### Data Aggregation & Analysis

The system includes comprehensive data aggregation capabilities for trend analysis and performance comparison:

#### Analysis CLI Tool

```bash
# Generate weekly aggregation report
python analysis_cli.py weekly AAPL --start-date 2024-01-01 --end-date 2024-12-31

# Generate monthly aggregation report  
python analysis_cli.py monthly AAPL --start-date 2024-01-01

# Calculate rolling metrics (30, 60, 90 day windows)
python analysis_cli.py rolling AAPL --date 2024-12-15

# Compare multiple symbols
python analysis_cli.py compare AAPL MSFT GOOGL --window 30

# Show market baselines (S&P 500, NASDAQ)
python analysis_cli.py baselines --date 2024-12-15
```

#### Sample Output

**Monthly Aggregation Example:**
```
📊 MONTHLY METRICS
Month    Open     Close    High     Low      Change   Volume      
2024-10  $229.52  $225.91  $237.49  $221.33  -1.57% 930,736,000
2024-11  $220.97  $237.33  $237.81  $219.71   7.40% 891,640,600
2024-12  $237.27  $250.42  $260.10  $237.16   5.54% 977,916,100
```

**Symbol Comparison Example:**
```
Symbol   Return   Ann. Return  Volatility   Sharpe   Trend     
AAPL     10.28%    228.88%      9.76%  13.38 up        
MSFT      7.78%    148.70%     14.30%   7.03 up        
GOOGL    10.05%    220.53%     38.28%   3.51 up
```

#### Available Metrics

- **Weekly/Monthly Aggregation**: OHLC prices, volume, volatility, price changes, technical indicators (RSI, MACD, SMA)
- **Rolling Performance**: Total returns, annualized returns, Sharpe ratios, maximum drawdown, trend analysis, momentum scoring
- **Comparison Analysis**: Multi-symbol performance comparison with customizable time windows
- **Market Baselines**: S&P 500 and NASDAQ benchmark comparisons for relative performance analysis

#### Data Models

The aggregation system provides structured data through these models:

- **`AggregatedMetrics`**: Weekly/monthly OHLC data with calculated performance metrics
- **`RollingMetrics`**: Rolling window performance analysis with risk metrics
- **Market Baselines**: Benchmark data for comparative analysis

#### Programmatic Access

```python
from analysis.aggregation import DataAggregator

aggregator = DataAggregator()

# Get monthly data
monthly_data = aggregator.aggregate_daily_to_monthly('AAPL', start_date, end_date)

# Calculate rolling metrics
rolling_metrics = aggregator.calculate_rolling_metrics('AAPL', date, window_days=30)

# Get market baselines
baselines = aggregator.get_comparison_baselines(date)
```

## Quick Start
```bash
# Install dependencies
pip install -r requirements.txt

# Run basic backtest
python main.py --symbol AAPL --backtest

# View detailed help
python main.py --help
```

## 🌐 Web Interface & Results Access

The system includes a comprehensive Flask web application for accessing analysis results, perfect for server deployments where you need remote access to your data.

### Starting the Web Server

#### Quick Start (Auto-installs dependencies)
```bash
python start_server.py
```

#### Custom Configuration
```bash
# Custom host and port
python start_server.py --host 0.0.0.0 --port 8080 --no-browser

# Direct Flask launch
python app.py

# Production deployment with Gunicorn
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

### Web Interface Features

#### 📊 **Dashboard** (`/`)
- Overview of all analyzed symbols with filtering capabilities
- Real-time symbol grid with performance metrics
- Date range selection and symbol filtering
- Quick access to detailed analysis

#### 📈 **Symbol Details** (`/symbol/<SYMBOL>`)
- Comprehensive analysis with interactive charts
- Performance visualization using Chart.js
- Historical data trends and trading activity
- Win rates and strategy performance metrics

#### 🔄 **Comparison View** (`/compare`)
- Multi-symbol performance comparison
- Side-by-side analysis with multiple visualization types
- Relative performance tracking
- Strategy effectiveness comparison

#### ⚡ **REST API Endpoints**
- `/api/symbols` - Available symbols list
- `/api/backtest/<symbol>/<date>` - Backtest results
- `/api/recommendations/<symbol>/<date>` - Trading recommendations
- `/api/historical/<symbol>` - Historical price data
- `/api/performance/<symbol>` - Performance metrics
- `/api/compare` - Multi-symbol comparison data
- `/health` - System health check

### Server Access Options

#### Local Development
```bash
# Access via localhost
http://localhost:5000
```

#### Remote Server Deployment
```bash
# Access via server IP/domain
http://your-server-ip:5000
http://your-domain.com:5000
```

#### Production Setup
For production deployments, consider:
- **Reverse Proxy**: nginx/Apache for SSL and domain routing
- **Process Management**: systemd, supervisor, or PM2 for auto-restart
- **Cloud Platforms**: AWS, GCP, Azure with auto-scaling

### Web Server Architecture

The Flask application provides:
- **Responsive Design**: Bootstrap-based UI that works on desktop and mobile
- **Real-time Data**: Dynamic loading of backtest results and recommendations
- **Interactive Charts**: Chart.js integration for performance visualization
- **Error Handling**: Graceful error pages and API error responses
- **CORS Support**: Cross-origin requests for API integration

### Integration with Analysis System

The web server automatically detects and serves:
- Backtest results from the `results/` directory
- Historical data from the `cache/` directory
- Real-time performance calculations
- Symbol configuration and metadata

**Perfect for server deployments** - Start the Flask server on your remote server to access all your stock analysis results through a modern web interface!

## 🚀 PythonAnywhere Deployment

This system is optimized for automated deployment on PythonAnywhere with daily scheduled execution.

### Features
- **Market Calendar Integration**: Automatically skips weekends and holidays
- **Smart Scheduling**: Only runs on trading days with early close detection
- **Comprehensive Logging**: Detailed execution logs and human-readable reports
- **Error Handling**: Graceful failure modes and recovery mechanisms
- **Working Directory Management**: Handles PythonAnywhere environment requirements

### Quick Deployment

1. **Upload Code to PythonAnywhere:**
   ```bash
   # Via Git (recommended)
   git clone https://github.com/yourusername/stocks.git
   cd stocks
   ```

2. **Install Dependencies:**
   ```bash
   pip3.10 install --user -r requirements.txt
   ```

3. **Test the System:**
   ```bash
   python3.10 pythonanywhere_daily_hook.py --force
   ```

4. **Schedule Daily Task:**
   - Go to PythonAnywhere Dashboard → **Tasks** tab
   - Command: `/home/yourusername/stocks/pythonanywhere_daily_hook.py`
   - Schedule: Daily at 6:00 PM EST (after market close)

### What Happens Daily

The automated scheduler:
1. ✅ **Market Calendar Check**: Verifies it's a trading day
2. 📊 **Data Collection**: Fetches latest data for all configured symbols
3. 🎯 **Strategy Execution**: Runs momentum, mean reversion, and breakout strategies
4. 📈 **Performance Analysis**: Calculates rolling metrics (7, 30, 90 days)
5. 📄 **Report Generation**: Creates comprehensive daily reports
6. 💾 **Data Storage**: Saves timestamped results and logs

### Output Structure
```
logs/
├── daily_executions/execution_2025-05-24.json    # Detailed JSON results
├── daily_reports/report_2025-05-24.txt           # Human-readable reports
└── pythonanywhere_daily.log                      # System logs

reports/
└── daily_report_20250524.md                      # Markdown reports
```

### Market Calendar Features
- **US Market Holidays**: New Year's, MLK Day, Presidents' Day, Good Friday, Memorial Day, Juneteenth, July 4th, Labor Day, Thanksgiving, Christmas
- **Early Close Detection**: Day after Thanksgiving, Christmas Eve
- **Weekend Skipping**: Automatic weekday-only execution
- **Timezone Awareness**: Handles EST/EDT properly

### Monitoring & Testing
```bash
# Test manual run
python3.10 pythonanywhere_daily_hook.py --force

# Check recent logs
tail -f logs/pythonanywhere_daily.log

# View latest report
cat logs/daily_reports/report_$(date +%Y-%m-%d).txt

# Update symbol configuration
python3.10 update_symbols.py
```

### Key Files
- `pythonanywhere_daily_hook.py` - Main scheduler hook (executable)
- `PYTHONANYWHERE_SETUP.md` - Comprehensive deployment guide
- `docs/pythonanywhere_deployment.md` - Detailed technical documentation

**📚 For complete deployment instructions, see:**
- [`PYTHONANYWHERE_SETUP.md`](../PYTHONANYWHERE_SETUP.md) - Quick setup guide
- [`docs/pythonanywhere_deployment.md`](pythonanywhere_deployment.md) - Detailed documentation

---

See individual component documentation for detailed usage. 