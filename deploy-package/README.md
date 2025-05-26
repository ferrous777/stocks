# Stock Market Analysis System

An automated daily stock market analysis system with comprehensive strategy execution, performance tracking, and intelligent scheduling.

## 🚀 Quick Start (PythonAnywhere Ready!)

This system is optimized for **PythonAnywhere deployment** with automated daily scheduling:

```bash
# 1. Clone the repository
git clone https://github.com/yourusername/stocks.git
cd stocks

# 2. Install dependencies
pip install -r requirements.txt

# 3. Test the system
python pythonanywhere_daily_hook.py --force

# 4. Set up PythonAnywhere scheduled task (see deployment section below)
```

## 📊 Features

### Market Analysis
- **21 Configured Symbols**: Tech stocks, ETFs, mutual funds with priority-based processing
- **3 Trading Strategies**: Momentum, mean reversion, and breakout detection
- **Performance Metrics**: Rolling analysis (7, 30, 90-day windows)
- **Market Benchmarking**: S&P 500 and sector comparisons

### Automation & Scheduling
- **Market Calendar Integration**: Automatically skips weekends and holidays
- **Smart Execution**: US market holiday detection with early close handling
- **Daily Reports**: Comprehensive analysis with strategy signals and performance
- **Error Recovery**: Graceful failure handling and detailed logging

### Data Management
- **SQLite Database**: Efficient time-series storage with 9,889+ historical records
- **JSON Export**: Structured data for external analysis
- **Markdown Reports**: Human-readable daily summaries
- **Performance Tracking**: Historical strategy effectiveness

## 🔧 System Components

### Core Modules
- **Market Data Collection**: Automated data fetching and validation
- **Strategy Engine**: Momentum, mean reversion, and breakout strategies
- **Performance Calculator**: Rolling metrics and benchmark comparisons
- **Report Generator**: Daily summaries and trend analysis

### Configuration
- **Symbol Management**: Priority-based symbol categorization
- **Strategy Parameters**: Configurable trading strategy settings
- **Scheduling Options**: Flexible timing and execution controls

## 🚀 PythonAnywhere Deployment

### ✅ Production Ready Features
- **Market Calendar Integration**: US holidays and trading day detection
- **PythonAnywhere Optimization**: Working directory and path management
- **Comprehensive Logging**: Detailed execution logs and error tracking
- **Smart Scheduling**: Only runs on trading days (unless forced)

### Quick Deploy Steps

1. **Upload to PythonAnywhere:**
   ```bash
   git clone https://github.com/yourusername/stocks.git
   cd stocks
   ```

2. **Install Dependencies:**
   ```bash
   pip3.10 install --user -r requirements.txt
   ```

3. **Test System:**
   ```bash
   python3.10 pythonanywhere_daily_hook.py --force
   ```

4. **Schedule Daily Task:**
   - Dashboard → Tasks → Create new task
   - Command: `/home/yourusername/stocks/pythonanywhere_daily_hook.py`
   - Time: Daily at 6:00 PM EST

### Daily Automation
The system automatically:
- ✅ Checks market calendar (skips weekends/holidays)
- 📊 Collects data for 21 configured symbols
- 🎯 Executes 3 trading strategies
- 📈 Calculates rolling performance metrics
- 📄 Generates comprehensive reports
- 💾 Saves timestamped results

### Output Structure
```
logs/
├── daily_executions/     # JSON execution results
├── daily_reports/        # Human-readable reports
└── pythonanywhere_daily.log  # System logs

reports/
└── daily_report_*.md     # Markdown summaries
```

## 📈 Configured Symbols

### Priority 1 (High Priority - 6 symbols)
**Technology Stocks:**
- AAPL, MSFT, GOOGL, AMZN, NVDA

**Consumer:**
- COST

### Priority 2 (Medium Priority - 13 symbols)
**ETFs for diversified exposure:**
- QQQ, VUG, IWF, SPYG, VGT, FDN
- VEA, VWO, FEZ, EWJ, MCHI, INDA, EWZ

### Priority 3 (Low Priority - 2 symbols)
**Mutual Funds:**
- KMKNX, FDEGX

## 🛠️ Development & Testing

### Local Development
```bash
# Run daily workflow manually
python dev-tools/scheduler_cli.py run

# Backfill historical data
python dev-tools/scheduler_cli.py backfill 2024-01-01 2024-12-31

# Check system status
python dev-tools/scheduler_cli.py status

# Update symbol configuration
python dev-tools/update_symbols.py
```

### Configuration Management
```bash
# View current symbols
python dev-tools/config_cli.py list-symbols

# Add new symbol
python dev-tools/config_cli.py add-symbol TSLA --priority 1 --sector Technology

# View aggregated data
python dev-tools/analysis_cli.py monthly AAPL --start-date 2024-01-01
```

## 📚 Documentation

- **[Complete Documentation](docs/README.md)** - Detailed component guides
- **[PythonAnywhere Setup](PYTHONANYWHERE_SETUP.md)** - Quick deployment guide
- **[Deployment Guide](docs/pythonanywhere_deployment.md)** - Technical details
- **[Backtest Guide](docs/backtest.md)** - Strategy testing
- **[Trade Guide](docs/trade_guide.md)** - Trading implementation

## 🔍 Market Calendar Features

### US Market Holidays (Automatically Detected)
- New Year's Day, MLK Day, Presidents' Day
- Good Friday, Memorial Day, Juneteenth
- Independence Day, Labor Day
- Thanksgiving, Christmas Day

### Special Handling
- **Early Closes**: Day after Thanksgiving, Christmas Eve
- **Weekend Skipping**: Automatic weekday-only execution
- **Timezone Awareness**: EST/EDT handling for market hours

## 📊 Monitoring & Logs

### Check System Health
```bash
# View recent execution logs
tail -f logs/pythonanywhere_daily.log

# Check latest report
cat logs/daily_reports/report_$(date +%Y-%m-%d).txt

# View execution results
cat logs/daily_executions/execution_$(date +%Y-%m-%d).json
```

### Performance Tracking
- **Strategy Effectiveness**: Historical signal accuracy
- **Data Quality**: Success rates and error tracking
- **Execution Metrics**: Processing time and resource usage

---

## 🎯 Ready for Production

This system is **production-ready** for PythonAnywhere with:
- ✅ Market calendar awareness
- ✅ Comprehensive error handling
- ✅ Detailed logging and reporting
- ✅ Automated scheduling optimization
- ✅ 9,889+ historical data points migrated

**Deploy today**: Upload, install dependencies, and schedule the daily task!

For detailed deployment instructions, see [`PYTHONANYWHERE_SETUP.md`](PYTHONANYWHERE_SETUP.md).
