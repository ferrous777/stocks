# Operational Runbooks

## Overview

This document provides step-by-step procedures for operating, maintaining, and troubleshooting the Stock Analysis System. These runbooks are designed for system administrators, DevOps engineers, and support personnel.

## Table of Contents

1. [Daily Operations](#daily-operations)
2. [Deployment Procedures](#deployment-procedures)
3. [Monitoring and Health Checks](#monitoring-and-health-checks)
4. [Backup and Recovery](#backup-and-recovery)
5. [Troubleshooting](#troubleshooting)
6. [Emergency Procedures](#emergency-procedures)
7. [Maintenance Tasks](#maintenance-tasks)

---

## Daily Operations

### Daily Workflow Overview

The system operates on an automated daily schedule that:
1. Checks if it's a trading day (market calendar validation)
2. Fetches latest market data for all tracked symbols
3. Runs trading strategies and generates signals
4. Calculates performance metrics and comparisons
5. Generates daily reports and summaries
6. Stores timestamped results

### Manual Daily Execution

#### Run Today's Analysis
```bash
cd /path/to/stocks
python run_daily.py
```

#### Run Specific Date
```bash
# Run analysis for a specific date
python run_daily.py --date 2025-05-24

# Run with dry-run mode (preview only)
python run_daily.py --date 2025-05-24 --dry-run

# Force refresh existing data
python run_daily.py --date 2025-05-24 --force
```

#### Backfill Date Range
```bash
# Fill multiple missing days
python run_daily.py --start 2025-05-20 --end 2025-05-24

# Preview backfill operations
python run_daily.py --start 2025-05-20 --end 2025-05-24 --dry-run
```

### Data Gap Detection and Resolution

#### Detect Missing Data
```bash
# Check all symbols for gaps
python detect_gaps.py

# Check specific symbols
python detect_gaps.py --symbols AAPL MSFT GOOGL

# Check specific date range
python detect_gaps.py --start 2025-05-01 --end 2025-05-24
```

#### Generate and Execute Fixes
```bash
# Generate fix commands
python detect_gaps.py --fix

# Execute generated fix script
bash fix_data_gaps_YYYYMMDD_HHMM.sh
```

### Daily Monitoring Checklist

- [ ] Check daily execution logs in `logs/pythonanywhere_daily.log`
- [ ] Verify data files created in `results/` directory
- [ ] Review daily report in `logs/daily_reports/`
- [ ] Monitor system health via `/health` endpoint
- [ ] Check for any error notifications

---

## Deployment Procedures

### Local Development Setup

#### Prerequisites
- Python 3.10 or higher
- pip package manager
- Git

#### Setup Steps
```bash
# 1. Clone repository
git clone <repository-url>
cd stocks

# 2. Install dependencies
pip install -r requirements.txt

# 3. Initialize configuration
python src/config/config_manager.py --init

# 4. Test installation
python test_api.py

# 5. Start development server
python app.py
```

### PythonAnywhere Production Deployment

#### Initial Deployment
```bash
# 1. Upload files to PythonAnywhere
# 2. Create virtual environment
mkvirtualenv stocks --python=python3.10

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure WSGI application
# Edit /var/www/yourusername_pythonanywhere_com_wsgi.py

# 5. Set up scheduled task
# Add to PythonAnywhere Tasks tab:
# cd /home/yourusername/stocks && python3.10 dev-tools/pythonanywhere_daily_hook.py
```

#### Deployment Validation
```bash
# Test manual execution
python3.10 dev-tools/pythonanywhere_daily_hook.py --force

# Verify web interface
curl https://yourusername.pythonanywhere.com/health

# Check log files
tail -f logs/pythonanywhere_daily.log
```

### Configuration Management

#### Environment Variables
```bash
# Development
export FLASK_ENV=development
export FLASK_DEBUG=True

# Production
export FLASK_ENV=production
export FLASK_DEBUG=False
```

#### Configuration Files
- `config.py` - Flask application configuration
- `src/data/default_symbols.json` - Default symbol list
- `wsgi.py` - WSGI configuration for production

---

## Monitoring and Health Checks

### Health Check Endpoints

#### System Health
```bash
# Basic health check
curl http://localhost:8090/health

# Response format:
{
  "status": "healthy",
  "timestamp": "2025-05-24T22:51:28.123456",
  "available_symbols": 35,
  "available_dates": 125
}
```

#### API Endpoints
```bash
# Test core endpoints
curl http://localhost:8090/api/symbols
curl http://localhost:8090/api/dates
curl http://localhost:8090/api/store/info
```

### Log Monitoring

#### Key Log Files
- `logs/pythonanywhere_daily.log` - Main application log
- `logs/daily_executions/execution_YYYY-MM-DD.json` - Daily execution details
- `logs/daily_reports/report_YYYY-MM-DD.txt` - Human-readable daily reports
- `logs/run_daily.log` - Manual operations log

#### Log Analysis Commands
```bash
# Check recent errors
grep -i error logs/pythonanywhere_daily.log | tail -20

# Monitor real-time logs
tail -f logs/pythonanywhere_daily.log

# Check daily execution summary
cat logs/daily_reports/report_$(date +%Y-%m-%d).txt
```

### Performance Monitoring

#### Key Metrics
- Daily execution completion time
- Number of symbols processed
- API response times
- Data file sizes and growth
- Memory and CPU usage

#### Monitoring Commands
```bash
# Check disk usage
du -sh cache/ results/ logs/

# Monitor process performance
ps aux | grep python

# Check file counts
find results/ -name "*.json" | wc -l
find cache/ -name "*.json" | wc -l
```

---

## Backup and Recovery

### Backup Procedures

#### Database Backup
```bash
# Backup SQLite database
cp data/timeseries.db data/timeseries.db.backup.$(date +%Y%m%d)

# Compress backup
gzip data/timeseries.db.backup.$(date +%Y%m%d)
```

#### Data Files Backup
```bash
# Backup results and cache
tar -czf backup_$(date +%Y%m%d).tar.gz results/ cache/ logs/

# Backup to external location
rsync -av results/ cache/ logs/ /backup/location/
```

#### Configuration Backup
```bash
# Backup configuration files
tar -czf config_backup_$(date +%Y%m%d).tar.gz \
  config.py wsgi.py requirements.txt \
  src/data/default_symbols.json
```

### Recovery Procedures

#### Data Recovery
```bash
# Restore from backup
tar -xzf backup_YYYYMMDD.tar.gz

# Validate restored data
python detect_gaps.py --start 2024-01-01
```

#### Database Recovery
```bash
# Restore database
cp data/timeseries.db.backup.YYYYMMDD data/timeseries.db

# Verify database integrity
python -c "
import sqlite3
conn = sqlite3.connect('data/timeseries.db')
cursor = conn.cursor()
cursor.execute('PRAGMA integrity_check')
print(cursor.fetchall())
conn.close()
"
```

#### Complete System Recovery
```bash
# 1. Assess damage
python detect_gaps.py --start 2024-01-01 --fix

# 2. Preview recovery
python run_daily.py --dry-run --start 2024-01-01

# 3. Execute gradual recovery
python run_daily.py --start 2024-01-01 --end 2024-06-30
python run_daily.py --start 2024-07-01 --end 2024-12-31
python run_daily.py --start 2025-01-01

# 4. Verify completion
python detect_gaps.py --start 2024-01-01
```

---

## Troubleshooting

### Common Issues and Solutions

#### Issue: Daily Execution Fails
**Symptoms**: No new files in results/, error logs show failures

**Diagnosis**:
```bash
# Check recent logs
tail -50 logs/pythonanywhere_daily.log

# Test manual execution
python dev-tools/pythonanywhere_daily_hook.py --force
```

**Solutions**:
1. Check internet connectivity and API access
2. Verify file permissions: `chmod -R 755 ~/stocks`
3. Check disk space: `df -h`
4. Restart scheduled task

#### Issue: Web Interface Not Loading
**Symptoms**: HTTP 500 errors, blank pages

**Diagnosis**:
```bash
# Test Flask app directly
python app.py

# Check WSGI configuration
grep -n error /var/www/yourusername_pythonanywhere_com_wsgi.py
```

**Solutions**:
1. Verify WSGI configuration
2. Check Python path in WSGI file
3. Ensure all dependencies installed
4. Review Flask error logs

#### Issue: Missing Market Data
**Symptoms**: Gaps in historical data, outdated information

**Diagnosis**:
```bash
# Detect data gaps
python detect_gaps.py --symbols AAPL MSFT

# Check API connectivity
curl -I https://query1.finance.yahoo.com/v8/finance/chart/AAPL
```

**Solutions**:
1. Run gap detection and fix commands
2. Check API rate limits and keys
3. Verify market calendar (weekends/holidays)
4. Run manual data collection for missing dates

#### Issue: High Memory Usage
**Symptoms**: System slowdown, out of memory errors

**Diagnosis**:
```bash
# Check memory usage
ps aux | grep python | head -5
free -h

# Check file sizes
du -sh cache/* | sort -h
```

**Solutions**:
1. Clear old log files: `find logs/ -name "*.log" -mtime +30 -delete`
2. Compress old data files
3. Optimize data processing batch sizes
4. Consider data retention policies

### Debug Mode Operations

#### Enable Debug Logging
```bash
# Set debug environment
export FLASK_DEBUG=True
export FLASK_ENV=development

# Run with verbose logging
python app.py --debug
```

#### Database Diagnostics
```bash
# Check database connections
python -c "
from src.storage.timeseries_db import TimeSeriesDB
db = TimeSeriesDB()
print('Database connection:', 'OK' if db.connection else 'FAILED')
"

# Verify data integrity
python -c "
from src.storage.timeseries_db import TimeSeriesDB
db = TimeSeriesDB()
print('Total records:', db.get_record_count())
"
```

---

## Emergency Procedures

### System Down - Critical Recovery

#### Immediate Actions (5 minutes)
1. Check system health: `curl http://localhost:8090/health`
2. Review recent error logs: `tail -100 logs/pythonanywhere_daily.log`
3. Attempt service restart: Restart Flask application
4. Notify stakeholders of outage

#### Short-term Recovery (30 minutes)
1. Identify root cause from logs
2. Implement temporary fix or workaround
3. Verify basic functionality restored
4. Monitor system stability

#### Long-term Resolution (2 hours)
1. Implement permanent fix
2. Run comprehensive system validation
3. Update monitoring and alerting
4. Document incident and lessons learned

### Data Corruption - Recovery Protocol

#### Assessment Phase
```bash
# Check data integrity
python detect_gaps.py --start 2024-01-01

# Verify database integrity
sqlite3 data/timeseries.db "PRAGMA integrity_check;"

# Check file system corruption
find results/ cache/ -name "*.json" -exec python -m json.tool {} \; > /dev/null
```

#### Recovery Phase
```bash
# Restore from last known good backup
cp data/timeseries.db.backup.YYYYMMDD data/timeseries.db

# Rebuild corrupted data
python run_daily.py --start <last_good_date> --force

# Validate recovery
python detect_gaps.py --start <last_good_date>
```

### Performance Emergency

#### High Load Response
```bash
# Identify resource usage
top -p $(pgrep -f python)
iostat -x 1 5

# Temporary load reduction
# Kill non-essential processes
# Reduce concurrent operations
```

#### Scale-up Procedures
1. Increase server resources (CPU/Memory)
2. Optimize database queries
3. Implement caching strategies
4. Consider horizontal scaling

---

## Maintenance Tasks

### Daily Maintenance

#### Automated Tasks
- [ ] Data collection and analysis (scheduled)
- [ ] Log rotation and cleanup
- [ ] Health checks and monitoring
- [ ] Backup verification

#### Manual Checks
- [ ] Review error logs for anomalies
- [ ] Verify data completeness
- [ ] Monitor system performance
- [ ] Check disk space usage

### Weekly Maintenance

#### Data Management
```bash
# Clean old temporary files
find /tmp -name "*stocks*" -mtime +7 -delete

# Compress old log files
find logs/ -name "*.log" -mtime +7 -exec gzip {} \;

# Verify backup integrity
tar -tzf backup_$(date -d '7 days ago' +%Y%m%d).tar.gz > /dev/null
```

#### System Updates
```bash
# Update dependencies
pip list --outdated
pip install -U <package_name>

# System security updates
sudo apt update && sudo apt upgrade
```

### Monthly Maintenance

#### Performance Review
- Analyze system performance trends
- Review and optimize slow queries
- Evaluate storage usage patterns
- Plan capacity improvements

#### Security Audit
- Review access logs
- Update API keys and credentials
- Check for security vulnerabilities
- Update security patches

#### Data Archival
```bash
# Archive old data (older than 2 years)
find results/ -name "*.json" -mtime +730 -exec mv {} archive/ \;

# Compress archived data
tar -czf archive_$(date +%Y%m).tar.gz archive/
rm -rf archive/
```

### Quarterly Maintenance

#### System Optimization
- Review and optimize database schemas
- Analyze and improve algorithm performance
- Update documentation and procedures
- Plan infrastructure improvements

#### Disaster Recovery Testing
- Test backup and recovery procedures
- Validate emergency response protocols
- Update incident response documentation
- Train team on new procedures

---

## Appendix

### Contact Information

**Primary Support**: System Administrator  
**Secondary**: DevOps Team  
**Emergency**: On-call Engineer  

### External Dependencies

- **Yahoo Finance API**: Market data source
- **PythonAnywhere**: Hosting platform
- **Flask**: Web framework
- **SQLite**: Database engine

### Change Log

| Date | Version | Changes | Author |
|------|---------|---------|--------|
| 2025-05-24 | 1.0 | Initial runbook creation | System |

### Related Documentation

- [API Documentation](api_documentation.md)
- [Data Schema Documentation](data_schemas.md)
- [Troubleshooting Guide](troubleshooting_guide.md)
- [PythonAnywhere Deployment Guide](pythonanywhere_deployment.md)
