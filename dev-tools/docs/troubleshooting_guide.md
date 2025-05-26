# Troubleshooting Guide

## Overview

This guide provides comprehensive troubleshooting procedures for the Stock Analysis System. It covers common issues, diagnostic procedures, and step-by-step solutions for system administrators and developers.

## Table of Contents

1. [Quick Diagnostic Commands](#quick-diagnostic-commands)
2. [System Issues](#system-issues)
3. [Data Issues](#data-issues)
4. [API Issues](#api-issues)
5. [Performance Issues](#performance-issues)
6. [Deployment Issues](#deployment-issues)
7. [Error Codes Reference](#error-codes-reference)
8. [Log Analysis](#log-analysis)

---

## Quick Diagnostic Commands

### System Health Check
```bash
# Quick system status
curl http://localhost:8090/health

# Check process status
ps aux | grep python | grep -E "(app.py|flask)"

# Check disk space
df -h

# Check recent errors
tail -20 logs/pythonanywhere_daily.log | grep -i error
```

### Data Validation
```bash
# Check for recent data files
ls -la results/ | head -10

# Validate JSON files
python -m json.tool results/AAPL_recommendations_20250524.json > /dev/null

# Check data gaps
python detect_gaps.py --symbols AAPL MSFT --start 2025-05-20
```

### Service Status
```bash
# Test API endpoints
curl http://localhost:8090/api/symbols
curl http://localhost:8090/api/dates

# Check database connectivity
python -c "from src.storage.timeseries_db import TimeSeriesDB; db = TimeSeriesDB(); print('DB OK' if db.connection else 'DB FAILED')"
```

---

## System Issues

### Issue: Flask Application Won't Start

#### Symptoms
- HTTP connection errors
- "Address already in use" errors
- Import errors on startup

#### Diagnosis
```bash
# Check if port is in use
netstat -tulpn | grep :8090

# Check Python path and imports
python -c "import flask; print('Flask OK')"
python -c "from app import app; print('App import OK')"

# Check configuration
python -c "from config import Config; print('Config OK')"
```

#### Solutions

1. **Port Already in Use**
```bash
# Find and kill process using port
lsof -ti:8090 | xargs kill -9

# Or use different port
python app.py --port 8091
```

2. **Import Errors**
```bash
# Check dependencies
pip install -r requirements.txt

# Check Python path
export PYTHONPATH=/path/to/stocks:$PYTHONPATH
```

3. **Configuration Issues**
```bash
# Verify configuration file
python -c "
import config
print('Flask ENV:', config.Config.FLASK_ENV)
print('Debug:', config.Config.DEBUG)
"
```

### Issue: Scheduled Tasks Not Running

#### Symptoms
- No new data files created
- Missing daily execution logs
- Outdated analysis results

#### Diagnosis
```bash
# Check cron jobs (Linux/Mac)
crontab -l

# Check PythonAnywhere tasks
# (Via web interface)

# Test manual execution
python dev-tools/pythonanywhere_daily_hook.py --force
```

#### Solutions

1. **Cron Job Issues**
```bash
# Edit crontab
crontab -e

# Add correct job
0 9 * * 1-5 cd /path/to/stocks && python dev-tools/pythonanywhere_daily_hook.py

# Check cron logs
grep CRON /var/log/syslog | tail -10
```

2. **PythonAnywhere Task Issues**
- Verify task is enabled in Tasks tab
- Check task logs for errors
- Ensure correct Python version (3.10)
- Verify working directory path

3. **Permission Issues**
```bash
# Fix file permissions
chmod +x dev-tools/pythonanywhere_daily_hook.py
chmod -R 755 /path/to/stocks
```

### Issue: Database Connection Errors

#### Symptoms
- SQLite errors in logs
- "Database is locked" errors
- Data not saving to database

#### Diagnosis
```bash
# Check database file
ls -la data/timeseries.db

# Test database integrity
sqlite3 data/timeseries.db "PRAGMA integrity_check;"

# Check for locks
lsof data/timeseries.db
```

#### Solutions

1. **Database Locked**
```bash
# Kill processes using database
lsof data/timeseries.db | awk 'NR>1 {print $2}' | xargs kill

# Restart application
```

2. **Corrupted Database**
```bash
# Backup current database
cp data/timeseries.db data/timeseries.db.backup

# Restore from backup
cp data/timeseries.db.backup.YYYYMMDD data/timeseries.db

# Or recreate database
rm data/timeseries.db
python src/storage/timeseries_db.py --init
```

3. **Permission Issues**
```bash
# Fix database permissions
chmod 664 data/timeseries.db
chown $USER:$GROUP data/timeseries.db
```

---

## Data Issues

### Issue: Missing Market Data

#### Symptoms
- Empty or outdated cache files
- API errors in logs
- Gaps in historical data

#### Diagnosis
```bash
# Check for data gaps
python detect_gaps.py --start 2025-05-01

# Test API connectivity
curl -I "https://query1.finance.yahoo.com/v8/finance/chart/AAPL"

# Check recent cache files
ls -la cache/ | grep $(date +%Y-%m)
```

#### Solutions

1. **API Connectivity Issues**
```bash
# Check internet connection
ping 8.8.8.8

# Test Yahoo Finance API
curl "https://query1.finance.yahoo.com/v8/finance/chart/AAPL?range=1d&interval=1d"

# Use alternative data source
# (Update configuration if needed)
```

2. **Fill Missing Data**
```bash
# Generate fix commands
python detect_gaps.py --fix

# Execute fixes
bash fix_data_gaps_YYYYMMDD_HHMM.sh

# Manual backfill
python run_daily.py --start 2025-05-01 --end 2025-05-24 --force
```

3. **Cache Corruption**
```bash
# Validate JSON files
find cache/ -name "*.json" -exec python -m json.tool {} \; > /dev/null

# Remove corrupted files
find cache/ -name "*.json" -exec sh -c 'python -m json.tool "$1" > /dev/null || rm "$1"' _ {} \;

# Regenerate data
python run_daily.py --start 2025-05-01 --force
```

### Issue: Inconsistent Analysis Results

#### Symptoms
- Different results for same symbol/date
- NaN or infinite values in calculations
- Strategy results don't match expectations

#### Diagnosis
```bash
# Check data consistency
python -c "
import json
with open('results/AAPL_backtest_20250524.json') as f:
    data = json.load(f)
    for strategy, results in data['strategies'].items():
        print(f'{strategy}: returns={results.get(\"total_returns\", \"N/A\")}, trades={results.get(\"total_trades\", \"N/A\")}')
"

# Validate calculation inputs
python -c "
import json
with open('cache/AAPL_historical.json') as f:
    data = json.load(f)
    print(f'Data points: {len(data[\"data_points\"])}')
    print(f'Date range: {data[\"data_points\"][0][\"date\"]} to {data[\"data_points\"][-1][\"date\"]}')
"
```

#### Solutions

1. **Recalculate Analysis**
```bash
# Force recalculation
python run_daily.py --date 2025-05-24 --force

# Clear cache and recalculate
rm results/AAPL_*_20250524.json
python run_daily.py --date 2025-05-24
```

2. **Validate Input Data**
```bash
# Check for data quality issues
python -c "
import json
import numpy as np
with open('cache/AAPL_historical.json') as f:
    data = json.load(f)
    for point in data['data_points']:
        if any(np.isnan(v) for v in [point['open'], point['high'], point['low'], point['close']]):
            print(f'NaN values found in {point[\"date\"]}')
        if point['high'] < point['low']:
            print(f'Invalid high/low in {point[\"date\"]}')
"
```

3. **Strategy Configuration Issues**
```bash
# Check strategy parameters
python -c "
from src.strategies.strategy_manager import StrategyManager
sm = StrategyManager()
print('Available strategies:', sm.get_strategy_names())
for name in sm.get_strategy_names():
    print(f'{name} config:', sm.get_strategy_config(name))
"
```

---

## API Issues

### Issue: API Endpoints Return 404 Errors

#### Symptoms
- HTTP 404 responses
- "Not Found" errors
- Missing API routes

#### Diagnosis
```bash
# Test specific endpoints
curl -v http://localhost:8090/api/symbols
curl -v http://localhost:8090/api/dates
curl -v http://localhost:8090/api/backtest/AAPL/20250524

# Check Flask routes
python -c "
from app import app
for rule in app.url_map.iter_rules():
    print(f'{rule.rule} -> {rule.endpoint}')
"
```

#### Solutions

1. **Verify File Existence**
```bash
# Check if data files exist
ls results/AAPL_backtest_20250524.json
ls results/AAPL_recommendations_20250524.json

# Generate missing files
python run_daily.py --date 2025-05-24 --symbols AAPL
```

2. **Check URL Patterns**
```bash
# Verify correct URL format
# Correct: /api/backtest/AAPL/20250524
# Incorrect: /api/backtest/aapl/2025-05-24

# Test with curl
curl "http://localhost:8090/api/backtest/AAPL/20250524"
```

3. **Flask Route Issues**
```bash
# Restart Flask application
python app.py

# Check for route conflicts
grep -n "@app.route" app.py
```

### Issue: API Returns 500 Internal Server Errors

#### Symptoms
- HTTP 500 responses
- Server error messages
- Application crashes

#### Diagnosis
```bash
# Check Flask logs
tail -50 logs/pythonanywhere_daily.log | grep -A 5 -B 5 "500"

# Test with debug mode
FLASK_DEBUG=True python app.py

# Check for Python exceptions
python -c "
from app import app
with app.app_context():
    from app import get_available_symbols
    print(get_available_symbols())
"
```

#### Solutions

1. **Fix Python Exceptions**
```bash
# Check for missing imports
python -c "
import json
import glob
import os
from datetime import datetime
from flask import Flask, render_template, jsonify
print('All imports OK')
"

# Verify file paths
python -c "
import os
print('Results dir exists:', os.path.exists('results'))
print('Cache dir exists:', os.path.exists('cache'))
"
```

2. **Handle Missing Data Gracefully**
```python
# Example fix for missing data
def load_backtest_results(symbol, date):
    try:
        filepath = f"results/{symbol}_backtest_{date}.json"
        if os.path.exists(filepath):
            with open(filepath, 'r') as f:
                return json.load(f)
        return None  # Return None instead of raising exception
    except Exception as e:
        app.logger.error(f"Error loading backtest for {symbol}/{date}: {e}")
        return None
```

### Issue: Slow API Response Times

#### Symptoms
- Long response times (>5 seconds)
- Timeouts
- Poor user experience

#### Diagnosis
```bash
# Test response times
time curl http://localhost:8090/api/symbols
time curl http://localhost:8090/api/backtest/AAPL/20250524

# Check file sizes
du -sh results/ cache/

# Monitor system resources
top -p $(pgrep -f flask)
```

#### Solutions

1. **Optimize Data Loading**
```python
# Add caching for frequently accessed data
from functools import lru_cache

@lru_cache(maxsize=100)
def get_cached_symbols():
    return get_available_symbols()

# Use more efficient file operations
def load_json_fast(filepath):
    with open(filepath, 'r') as f:
        return json.load(f)
```

2. **Implement Response Caching**
```python
from flask_caching import Cache

cache = Cache(app, config={'CACHE_TYPE': 'simple'})

@app.route('/api/symbols')
@cache.cached(timeout=300)  # 5 minutes
def api_symbols():
    return jsonify(get_available_symbols())
```

3. **Database Optimization**
```sql
-- Add indexes for common queries
CREATE INDEX IF NOT EXISTS idx_symbol_date ON daily_snapshots(symbol, date);
CREATE INDEX IF NOT EXISTS idx_performance_date ON strategy_performance(date);
```

---

## Performance Issues

### Issue: High Memory Usage

#### Symptoms
- System running out of memory
- Slow performance
- Process killed by OS

#### Diagnosis
```bash
# Check memory usage
ps aux | grep python | grep -E "(app|flask)"
free -h

# Monitor memory over time
watch -n 5 'ps aux | grep python | grep flask'

# Check for memory leaks
python -c "
import psutil
import os
process = psutil.Process(os.getpid())
print(f'Memory usage: {process.memory_info().rss / 1024 / 1024:.2f} MB')
"
```

#### Solutions

1. **Optimize Data Loading**
```python
# Stream large files instead of loading all at once
def stream_large_file(filepath):
    with open(filepath, 'r') as f:
        for line in f:
            yield json.loads(line)

# Limit data in memory
def get_recent_data(symbol, days=30):
    # Only load recent data instead of all history
    pass
```

2. **Implement Pagination**
```python
@app.route('/api/backtest/<symbol>/<date>')
def api_backtest(symbol, date):
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    
    # Return paginated results
    results = load_backtest_results(symbol, date)
    if results and 'trades' in results:
        trades = results['trades']
        start = (page - 1) * per_page
        end = start + per_page
        results['trades'] = trades[start:end]
        results['pagination'] = {
            'page': page,
            'per_page': per_page,
            'total': len(trades)
        }
    return jsonify(results)
```

3. **Clear Unused Data**
```bash
# Clean up old log files
find logs/ -name "*.log" -mtime +30 -delete

# Remove temporary files
find /tmp -name "*stocks*" -mtime +1 -delete

# Compress old data
find results/ -name "*.json" -mtime +90 -exec gzip {} \;
```

### Issue: High CPU Usage

#### Symptoms
- System becomes unresponsive
- High load average
- Slow calculations

#### Diagnosis
```bash
# Check CPU usage
top -p $(pgrep -f python)
htop | grep python

# Profile Python code
python -m cProfile -o profile.stats app.py
```

#### Solutions

1. **Optimize Calculations**
```python
# Use vectorized operations with NumPy
import numpy as np

def calculate_moving_average_fast(prices, window):
    return np.convolve(prices, np.ones(window)/window, mode='valid')

# Cache expensive calculations
@lru_cache(maxsize=1000)
def expensive_calculation(symbol, date):
    # Cache results of expensive operations
    pass
```

2. **Implement Background Processing**
```python
import threading
from queue import Queue

def background_processor():
    while True:
        task = task_queue.get()
        if task:
            process_task(task)
        task_queue.task_done()

# Start background thread
task_queue = Queue()
worker_thread = threading.Thread(target=background_processor, daemon=True)
worker_thread.start()
```

---

## Deployment Issues

### Issue: PythonAnywhere Deployment Fails

#### Symptoms
- WSGI errors
- Import errors
- File not found errors

#### Diagnosis
```bash
# Check WSGI configuration
cat /var/www/yourusername_pythonanywhere_com_wsgi.py

# Verify file structure
ls -la /home/yourusername/stocks/

# Check Python path
python3.10 -c "import sys; print('\n'.join(sys.path))"
```

#### Solutions

1. **Fix WSGI Configuration**
```python
# Correct WSGI file content
import sys
import os

# Add project directory to Python path
project_home = '/home/yourusername/stocks'
if project_home not in sys.path:
    sys.path.insert(0, project_home)

# Set environment
os.environ['FLASK_ENV'] = 'production'

# Import application
from app import app as application
```

2. **Fix File Permissions**
```bash
# Make files readable
chmod -R 755 /home/yourusername/stocks/

# Make Python files executable
chmod +x /home/yourusername/stocks/app.py
```

3. **Install Dependencies**
```bash
# Install in user directory or virtual environment
pip3.10 install --user -r requirements.txt

# Or create virtual environment
python3.10 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Issue: Environment Configuration Problems

#### Symptoms
- Wrong configuration values
- Missing environment variables
- Different behavior between environments

#### Diagnosis
```bash
# Check environment variables
env | grep FLASK
env | grep PYTHON

# Verify configuration loading
python -c "
import os
print('FLASK_ENV:', os.environ.get('FLASK_ENV', 'not set'))
print('DEBUG:', os.environ.get('FLASK_DEBUG', 'not set'))
"
```

#### Solutions

1. **Set Environment Variables**
```bash
# For development
export FLASK_ENV=development
export FLASK_DEBUG=True

# For production
export FLASK_ENV=production
export FLASK_DEBUG=False

# Make permanent in shell profile
echo "export FLASK_ENV=production" >> ~/.bashrc
```

2. **Create Environment Files**
```bash
# .env file for development
cat > .env << EOF
FLASK_ENV=development
FLASK_DEBUG=True
DATABASE_URL=sqlite:///data/timeseries.db
EOF

# Load in application
from dotenv import load_dotenv
load_dotenv()
```

---

## Error Codes Reference

### HTTP Error Codes

| Code | Meaning | Common Causes | Solutions |
|------|---------|---------------|-----------|
| 404 | Not Found | Missing data files, invalid symbol/date | Verify file exists, check symbol format |
| 500 | Internal Server Error | Python exceptions, database errors | Check logs, fix code issues |
| 502 | Bad Gateway | WSGI configuration issues | Fix WSGI file, restart service |
| 503 | Service Unavailable | Service down, overloaded | Restart service, check resources |

### Application Error Codes

| Code | Description | Cause | Solution |
|------|-------------|-------|---------|
| DATA_NOT_FOUND | Requested data not available | Missing files, no data for date | Run data collection, check date format |
| INVALID_SYMBOL | Invalid stock symbol | Wrong format, unsupported symbol | Use valid symbols from /api/symbols |
| DATABASE_ERROR | Database operation failed | Connection issues, corruption | Check database, restart service |
| API_RATE_LIMIT | External API rate limited | Too many requests | Wait and retry, implement backoff |
| CALCULATION_ERROR | Analysis calculation failed | Invalid data, division by zero | Check input data, fix calculations |

### System Error Patterns

#### Common Log Patterns
```bash
# Database connection errors
grep "database.*lock" logs/*.log

# API timeout errors
grep "timeout" logs/*.log

# File permission errors
grep "permission.*denied" logs/*.log

# Memory errors
grep -i "memory\|oom" logs/*.log
```

---

## Log Analysis

### Log File Locations

| Log File | Purpose | Format |
|----------|---------|--------|
| `logs/pythonanywhere_daily.log` | Main application log | Text |
| `logs/daily_executions/execution_YYYY-MM-DD.json` | Daily execution details | JSON |
| `logs/daily_reports/report_YYYY-MM-DD.txt` | Human-readable reports | Text |
| `logs/run_daily.log` | Manual operations | Text |

### Log Analysis Commands

#### Find Recent Errors
```bash
# Last 24 hours of errors
find logs/ -name "*.log" -mtime -1 -exec grep -l -i error {} \;

# Count error types
grep -i error logs/pythonanywhere_daily.log | cut -d' ' -f3- | sort | uniq -c | sort -nr
```

#### Analyze Performance
```bash
# Find slow operations
grep "took\|duration\|elapsed" logs/*.log | sort -k3 -nr

# Check memory usage over time
grep "memory\|mem" logs/*.log | tail -20
```

#### Monitor Data Quality
```bash
# Check data validation failures
grep "validation\|invalid\|corrupt" logs/*.log

# Find missing data incidents
grep "not found\|missing\|gap" logs/*.log
```

### Log Rotation and Cleanup

#### Automatic Log Rotation
```bash
# Configure logrotate
cat > /etc/logrotate.d/stocks << EOF
/path/to/stocks/logs/*.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
}
EOF
```

#### Manual Cleanup
```bash
# Clean logs older than 30 days
find logs/ -name "*.log" -mtime +30 -delete

# Compress old logs
find logs/ -name "*.log" -mtime +7 -exec gzip {} \;

# Archive old execution logs
tar -czf logs/archive/executions_$(date +%Y%m).tar.gz logs/daily_executions/
```

---

## Preventive Measures

### Monitoring Setup

#### Health Check Script
```bash
#!/bin/bash
# health_check.sh

# Check API endpoints
curl -f http://localhost:8090/health || echo "API DOWN"

# Check disk space
DISK_USAGE=$(df / | tail -1 | awk '{print $5}' | sed 's/%//')
if [ $DISK_USAGE -gt 90 ]; then
    echo "DISK USAGE HIGH: ${DISK_USAGE}%"
fi

# Check for recent data
RECENT_FILES=$(find results/ -name "*.json" -mtime -1 | wc -l)
if [ $RECENT_FILES -eq 0 ]; then
    echo "NO RECENT DATA FILES"
fi
```

#### Automated Alerts
```python
# alert_system.py
import smtplib
from email.mime.text import MIMEText

def send_alert(subject, message):
    msg = MIMEText(message)
    msg['Subject'] = f"Stock Analysis Alert: {subject}"
    msg['From'] = "alerts@example.com"
    msg['To'] = "admin@example.com"
    
    server = smtplib.SMTP('localhost')
    server.send_message(msg)
    server.quit()

# Usage in application
try:
    # Risk operation
    run_daily_analysis()
except Exception as e:
    send_alert("Daily Analysis Failed", str(e))
```

### Best Practices

1. **Regular Backups**: Automate daily backups of data and configuration
2. **Monitoring**: Implement comprehensive health checks and alerting
3. **Testing**: Test deployment and recovery procedures regularly
4. **Documentation**: Keep troubleshooting procedures up to date
5. **Logging**: Ensure adequate logging for diagnosis
6. **Validation**: Implement data validation at all entry points

---

## Support Escalation

### Level 1 Support (Basic Issues)
- API endpoint problems
- Basic configuration issues
- Simple data gaps

### Level 2 Support (Intermediate Issues)
- Database problems
- Performance optimization
- Deployment issues

### Level 3 Support (Advanced Issues)
- Complex data corruption
- Algorithm issues
- Infrastructure problems

### Contact Information
- **Documentation**: [Project README](../README.md)
- **Issue Tracking**: GitHub Issues
- **Emergency Contact**: System Administrator

---

*Last Updated: 2025-05-24*  
*Version: 1.0*
