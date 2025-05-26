# Operational Tools Documentation

This document describes the operational tools available for managing daily market data collection and analysis.

## 🚀 Quick Start

### Run Daily Operations for Any Date
```bash
# Run for today (default)
python run_daily.py

# Run for specific date
python run_daily.py --date 2025-05-23

# Backfill date range
python run_daily.py --start 2025-05-20 --end 2025-05-23

# Preview operations (dry-run)
python run_daily.py --dry-run --date 2025-05-23

# Force refresh existing data
python run_daily.py --date 2025-05-23 --force
```

### Detect and Fix Data Gaps
```bash
# Analyze all symbols for gaps
python detect_gaps.py

# Analyze specific symbols
python detect_gaps.py --symbols AAPL MSFT GOOGL

# Analyze specific date range
python detect_gaps.py --start 2025-05-01 --end 2025-05-23

# Generate fix commands
python detect_gaps.py --fix

# Run generated fixes
bash fix_data_gaps_YYYYMMDD_HHMM.sh
```

## 📋 Available Tools

### 1. `run_daily.py` - Daily Operations Wrapper

**Purpose**: Execute daily market data collection and analysis for any date or date range.

**Key Features**:
- ✅ Date-specific execution (`--date YYYY-MM-DD`)
- ✅ Date range processing (`--start` and `--end`)
- ✅ Dry-run mode for previewing operations
- ✅ Force refresh for overriding existing data
- ✅ Trading day validation (skips weekends/holidays)
- ✅ Comprehensive logging to `logs/run_daily.log`
- ✅ Data existence validation before processing
- ✅ Summary reporting with success/failure counts

**Usage Examples**:
```bash
# Basic operations
python run_daily.py                              # Today
python run_daily.py --date 2025-05-23           # Specific date
python run_daily.py --start 2025-05-20 --end 2025-05-23  # Date range

# Options
python run_daily.py --dry-run --date 2025-05-23          # Preview only
python run_daily.py --force --date 2025-05-23            # Force refresh
python run_daily.py --symbols AAPL MSFT --date 2025-05-23 # Specific symbols
python run_daily.py --validate-only --date 2025-05-23    # Check data only
python run_daily.py --verbose --date 2025-05-23          # Detailed logging
```

### 2. `detect_gaps.py` - Data Gap Analysis

**Purpose**: Identify missing dates in historical market data and generate fix commands.

**Key Features**:
- ✅ Trading day-aware gap detection
- ✅ Multi-symbol analysis with configurable date ranges
- ✅ Data coverage statistics and reporting
- ✅ Automatic fix command generation
- ✅ Executable shell script creation
- ✅ Customizable minimum gap size filtering
- ✅ Comprehensive summary reports

**Usage Examples**:
```bash
# Basic analysis
python detect_gaps.py                           # All symbols, past year
python detect_gaps.py --symbols AAPL MSFT      # Specific symbols
python detect_gaps.py --start 2025-05-01       # From specific date

# Generate fixes
python detect_gaps.py --fix                     # Create fix commands
python detect_gaps.py --symbols AAPL --fix     # Fix specific symbol
python detect_gaps.py --start 2025-05-01 --end 2025-05-23 --fix

# Options
python detect_gaps.py --verbose                 # Detailed output
python detect_gaps.py --min-gap-size 5         # Only gaps ≥5 days
```

## 🔧 Common Operational Scenarios

### Scenario 1: Daily System Failed
```bash
# Check what happened
python detect_gaps.py --start 2025-05-23 --end 2025-05-23

# Fix the missing day
python run_daily.py --date 2025-05-23 --force
```

### Scenario 2: Multiple Days Missing
```bash
# Find gaps in past week
python detect_gaps.py --start 2025-05-17 --end 2025-05-23 --fix

# Run generated fix script
bash fix_data_gaps_20250524_1854.sh
```

### Scenario 3: New Symbol Added
```bash
# Backfill new symbol for past year
python run_daily.py --symbols NVDA --start 2024-05-24 --end 2025-05-24 --force

# Verify coverage
python detect_gaps.py --symbols NVDA --start 2024-05-24
```

### Scenario 4: API Issues Recovery
```bash
# Check what data is missing
python detect_gaps.py --start 2025-05-01 --fix

# Preview recovery operations
python run_daily.py --dry-run --start 2025-05-01 --end 2025-05-23

# Execute recovery
bash fix_data_gaps_YYYYMMDD_HHMM.sh
```

## 📊 Output and Logging

### Log Files
- `logs/run_daily.log` - Daily operations log
- `logs/detect_gaps.log` - Gap analysis log
- Generated fix scripts: `fix_data_gaps_YYYYMMDD_HHMM.sh`

### Status Codes
- **Exit 0**: Success, all operations completed
- **Exit 1**: Failures detected, check logs for details

### Data Status Indicators
- ✅ **COMPLETE**: All expected data present
- ⚠️ **GAPS_FOUND**: Missing data periods identified
- ❌ **NO_DATA**: No data available for symbol/period
- 🔄 **PROCESSING**: Operation in progress

## 🛡️ Safety Features

### Date Validation
- Prevents processing future dates beyond market availability
- Validates date format (YYYY-MM-DD)
- Trading day awareness (skips weekends/holidays by default)

### Data Protection
- Existing data preserved unless `--force` specified
- Dry-run mode for safe operation preview
- Comprehensive validation before processing

### Error Handling
- Graceful failure handling with detailed error messages
- Resume capability for interrupted operations
- Data integrity validation and reporting

## 🔄 Integration with Existing System

These tools integrate seamlessly with the existing market data infrastructure:

- **Configuration**: Uses `ConfigManager` for symbol lists and settings
- **Data Storage**: Works with existing cache file structure
- **Market Calendar**: Respects trading days and holidays
- **Logging**: Consistent with system logging standards
- **Error Handling**: Compatible with existing error handling patterns

## 📈 Performance Considerations

- **Batch Processing**: Efficient handling of date ranges
- **Parallel Operations**: Symbol processing can be parallelized
- **Memory Usage**: Streaming approach for large datasets
- **API Rate Limits**: Respects external API constraints
- **Cache Efficiency**: Leverages existing cache infrastructure

## 🚨 Emergency Procedures

### Complete System Recovery
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

### Critical Symbol Priority Recovery
```bash
# Focus on high-priority symbols first
python run_daily.py --symbols AAPL MSFT GOOGL AMZN NVDA --start 2025-05-01 --force
python detect_gaps.py --symbols AAPL MSFT GOOGL AMZN NVDA
```

---

*For additional support or questions, refer to the main project documentation or system logs.*
