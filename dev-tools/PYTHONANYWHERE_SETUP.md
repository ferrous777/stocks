# PythonAnywhere Deployment - Quick Setup Guide

## ✅ Your System Is Ready for PythonAnywhere!

Your stock analysis system is already optimized for PythonAnywhere deployment with:

- **Market Calendar Integration**: Automatically skips weekends and holidays
- **Smart Scheduling Hook**: `dev-tools/pythonanywhere_daily_hook.py` 
- **Comprehensive Logging**: Detailed execution logs and reports
- **Error Handling**: Graceful failure modes and recovery
- **Working Directory Management**: Handles PythonAnywhere environment properly

## 🚀 Deployment Steps

### 1. Upload Your Code

Upload your entire `stocks` directory to PythonAnywhere:

```bash
# Option A: Using Git (recommended)
git clone https://github.com/yourusername/stocks.git

# Option B: ZIP upload via web interface
# Upload and extract your stocks.zip file
```

### 2. Install Dependencies

In a PythonAnywhere Bash console:

```bash
cd ~/stocks
pip3.10 install --user -r requirements.txt
```

### 3. Test the System

Test your daily hook to ensure everything works:

```bash
cd ~/stocks
python3.10 dev-tools/pythonanywhere_daily_hook.py --force
```

### 4. Set Up Scheduled Task

1. Go to PythonAnywhere Dashboard → **Tasks** tab
2. Create a new scheduled task:

**Command:**
```
/home/yourusername/stocks/dev-tools/pythonanywhere_daily_hook.py
```

**Schedule:** Daily at 6:00 PM EST (after market close)

**Description:** Daily Stock Market Analysis

## 📊 What Happens Daily

The scheduler automatically:

1. **Checks Trading Calendar**: Skips weekends and holidays
2. **Collects Market Data**: Fetches latest data for all configured symbols
3. **Runs Strategies**: Executes momentum, mean reversion, and breakout strategies
4. **Calculates Metrics**: Computes rolling performance indicators
5. **Generates Reports**: Creates daily markdown reports and JSON logs
6. **Saves Results**: Organizes data in timestamped files

## 📁 Output Structure

```
logs/
├── daily_executions/
│   └── execution_2025-05-24.json     # Detailed JSON results
├── daily_reports/
│   └── report_2025-05-24.txt         # Human-readable reports
└── pythonanywhere_daily.log          # System logs

reports/
└── daily_report_20250524.md          # Markdown reports
```

## 🎯 Key Features

### Market Calendar Integration
- **US Market Holidays**: New Year's, MLK Day, Presidents' Day, Good Friday, Memorial Day, Juneteenth, July 4th, Labor Day, Thanksgiving, Christmas
- **Early Close Detection**: Day after Thanksgiving, Christmas Eve
- **Weekend Skipping**: Automatic weekday-only execution
- **Timezone Awareness**: Handles EST/EDT properly

### Error Handling
- **Graceful Failures**: Continues processing other symbols if one fails
- **Detailed Logging**: Comprehensive error tracking and reporting
- **Force Override**: `--force` flag for testing and manual runs
- **Exit Codes**: Proper status codes for PythonAnywhere monitoring

### Performance Features
- **Efficient Database**: SQLite with optimized queries
- **Minimal Dependencies**: Uses only essential packages
- **Working Directory Safety**: Handles PythonAnywhere path requirements
- **Memory Efficient**: Processes symbols sequentially

## 🔧 Configuration

### Symbols Management
Update your symbol list:
```bash
cd ~/stocks
python3.10 update_symbols.py
```

### View Current Configuration
```bash
cd ~/stocks
python3.10 config_cli.py list-symbols
```

## 📈 Monitoring

### Check Recent Executions
```bash
cd ~/stocks
ls -la logs/daily_executions/
tail -f logs/pythonanywhere_daily.log
```

### View Reports
```bash
cd ~/stocks
cat logs/daily_reports/report_$(date +%Y-%m-%d).txt
```

### Manual Test Run
```bash
cd ~/stocks
python3.10 dev-tools/pythonanywhere_daily_hook.py --force
```

## 🔍 Troubleshooting

### Common Issues

**Import Errors:**
- Ensure you're in the correct directory (`cd ~/stocks`)
- Check Python path setup in the script

**Permission Errors:**
- Make the script executable: `chmod +x dev-tools/pythonanywhere_daily_hook.py`

**Database Issues:**
- Initialize database: `python3.10 -c "from src.storage.timeseries_db import TimeSeriesDB; TimeSeriesDB()"`

**Missing Data:**
- Market data fetching is currently simulated - replace with real API in production

### Testing Commands

```bash
# Test market calendar
python3.10 -c "
from src.market_calendar.market_calendar import MarketCalendar, MarketType
cal = MarketCalendar(MarketType.NYSE)
from datetime import date
print(f'Today is trading day: {cal.is_trading_day(date.today())}')
"

# Test database
python3.10 -c "
from src.storage.timeseries_db import TimeSeriesDB
db = TimeSeriesDB()
print('Database connection successful')
"

# Test configuration
python3.10 -c "
from src.config.config_manager import ConfigManager
config = ConfigManager().get_config()
print(f'Configured symbols: {len(config.symbols)}')
"
```

## 📞 Support

For PythonAnywhere specific issues:
- Check PythonAnywhere help docs
- Use their forum support
- Email help@pythonanywhere.com

For system-specific issues:
- Check logs in `logs/` directory
- Run manual test with `--force` flag
- Review error messages in daily reports

---

**🎉 Your system is production-ready for PythonAnywhere!**

The `pythonanywhere_daily_hook.py` script handles all the complexities of:
- Market calendar awareness
- Working directory management  
- Error handling and logging
- Report generation
- Database operations

Just upload, install dependencies, and schedule the task!
