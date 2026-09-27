# PythonAnywhere Deployment Guide

This guide explains how to deploy the stock analysis system to PythonAnywhere and set up automated daily execution.

## Prerequisites

- PythonAnywhere account (free or paid)
- SSH access for the direct deployment script, plus local `ssh` and `rsync`
- A configured web app and scheduled task using the required Python dependencies

## Deployment Steps

### 1. Upload Files to PythonAnywhere

From your local checkout, upload code to `/home/ferrous77`:

```bash
bash deploy_clean.sh
```

This replaces application code and `config/system_config.yaml`, backs up the existing
WSGI file before configuring it for the home directory, and reloads the web app.
Server-side `data/`, `cache/`, `results/`, `logs/`, and `reports/` are preserved.
Only Python source is copied from `performance/`; its databases and reports are preserved.
Back up any server-specific YAML settings before deploying.

For offline upload, run `bash scripts/deploy_to_pythonanywhere.sh` locally. Upload
`stocks-app.tar.gz`, extract it into a separate staging directory (not the home
directory), and run `bash deploy_server.sh` there. Configure WSGI to import
`app` from `/home/ferrous77`, then install dependencies and reload via the Web tab.

### 2. Install Dependencies

In a PythonAnywhere Bash console:

```bash
cd ~/
pip3.10 install --user -r requirements.txt
```

Note: Replace `3.10` with your preferred Python version.

### 3. Set Up the Database

Initialize the database and migrate existing data:

```bash
cd ~/
python3.10 -c "
from storage.timeseries_db import TimeSeriesDB
db = TimeSeriesDB()
print('Database initialized successfully')
"
```

### 4. Configure System Settings

Update the configuration file if needed:

```bash
cd ~/
python3.10 -c "from config.config_manager import ConfigManager; print(ConfigManager().get_enabled_symbols())"
```

### 5. Test the Daily Hook

Test the PythonAnywhere hook script to ensure it works:

```bash
cd ~/
python3.10 /home/ferrous77/pythonanywhere_daily_hook.py --force
```

This will run the daily workflow regardless of whether it's a trading day.

## Setting Up Scheduled Tasks

### For Paid Accounts

1. Go to your PythonAnywhere Dashboard
2. Click on the "Tasks" tab
3. Create a new scheduled task with these settings:

**Command:**
```bash
python3.10 /home/ferrous77/pythonanywhere_daily_hook.py
```

**Time:** 
- Daily at 6:00 PM EST (after market close)
- Or choose your preferred time

**Description:** Daily stock market analysis

### For Free Accounts

Free accounts can set up one daily task. Use the same command as above.

### Using Custom Python Version

If you need a specific Python version:

```bash
python3.10 /home/ferrous77/pythonanywhere_daily_hook.py
```

### Using Virtual Environment

If you're using a virtual environment:

```bash
source virtualenvwrapper.sh && workon myenv && python /home/ferrous77/pythonanywhere_daily_hook.py
```

Or using the direct path to the venv python:

```bash
/home/ferrous77/.virtualenvs/myenv/bin/python /home/ferrous77/pythonanywhere_daily_hook.py
```

## Features of the PythonAnywhere Hook

The `/home/ferrous77/pythonanywhere_daily_hook.py` script includes:

### Market Calendar Integration
- Automatically skips weekends and holidays
- Handles early close days (day after Thanksgiving, Christmas Eve)
- Provides detailed trading day information

### Smart Execution
- Only runs on trading days (unless forced)
- Proper working directory handling
- Comprehensive error handling and logging

### Logging and Reporting
- Creates detailed execution logs in `logs/daily_executions/`
- Generates human-readable reports in `logs/daily_reports/`
- Prints summary to console (visible in task logs)

### Example Output
```
=== Daily Market Analysis Report ===
Date: 2025-05-24
Time: 2025-05-24 18:00:05.123456
Status: COMPLETED
Environment: PythonAnywhere

✅ Execution completed successfully

📊 Data Collection:
- Symbols processed: 21
- Successful fetches: 19
- Success rate: 90.5%

📈 Strategy Signals:
- BUY signals: 3
- SELL signals: 2
- HOLD signals: 16

📊 Performance Metrics:
- Symbols analyzed: 19

Trading day info: 2025-05-24 is a trading day
```

## Monitoring and Troubleshooting

### Check Task Logs
PythonAnywhere provides logs for each task execution. Check these if there are issues.

### Manual Testing
You can always run the script manually to test:

```bash
cd ~/
python3.10 /home/ferrous77/pythonanywhere_daily_hook.py --force
```

### Log Files
Check the following log files for detailed information:
- `logs/pythonanywhere_daily.log` - Main application log
- `logs/daily_executions/execution_YYYY-MM-DD.json` - JSON results
- `logs/daily_reports/report_YYYY-MM-DD.txt` - Human-readable reports

### Common Issues

**ImportError: Failed to import required modules**
- Check that all dependencies are installed
- Verify the working directory is correct
- Ensure the src path is properly added

**Database errors**
- Verify the database file exists and is writable
- Check file permissions

**Market data errors**
- These are often temporary API issues
- Check the error logs for specific details

## Configuration Options

### Force Execution
To run on non-trading days:
```bash
python3.10 /home/ferrous77/pythonanywhere_daily_hook.py --force
```

### Different Time Zones
The market calendar handles US Eastern Time automatically. If you need different timezone handling, modify the `MarketCalendar` configuration.

## Performance Considerations

### Free Account Limitations
- One scheduled task only
- Task can run for up to 2 hours
- Limited CPU seconds per day

### Paid Account Benefits
- Up to 20 scheduled tasks
- Tasks can run for up to 12 hours
- More CPU seconds available

### Optimization Tips
- The hook includes market calendar checks to skip unnecessary runs
- Data is cached to reduce API calls
- Database operations are optimized for speed

## Backup and Maintenance

### Database Backup
Regularly backup your database file:
```bash
cp data/timeseries.db data/timeseries.db.backup.$(date +%Y%m%d)
```

### Log Cleanup
Periodically clean old log files to save space:
```bash
find logs/daily_executions -name "*.json" -mtime +30 -delete
find logs/daily_reports -name "*.txt" -mtime +30 -delete
```

## Support

If you encounter issues:
1. Check the PythonAnywhere forums
2. Review the log files for error details
3. Test the script manually first
4. Ensure all dependencies are properly installed

For PythonAnywhere-specific issues, consult their help documentation or contact their support team.
