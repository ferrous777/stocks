# PythonAnywhere Deployment - CORRECTED PATHS

## ✅ IMPORTANT: Correct File Structure

All files should be uploaded directly to `/home/ferrous77/` (NOT `/home/ferrous77/stocks/`)

## Step 1: Upload Files to PythonAnywhere

Upload these files to `/home/ferrous77/`:

```
/home/ferrous77/
├── pythonanywhere_daily_hook.py
├── pythonanywhere_daily_hook_server.py  (server-specific version)
├── quick_test_hook_server.py
├── pythonanywhere_dependency_fixer.py
├── requirements.txt
├── src/
│   ├── scheduler/
│   │   └── daily_scheduler.py  (with real API integration)
│   ├── market_data/
│   ├── strategies/
│   ├── storage/
│   ├── analysis/
│   ├── reports/
│   └── config/
├── cache/
├── logs/ (will be created)
└── reports/ (will be created)
```

## Step 2: Fix Dependencies on PythonAnywhere

Run these commands on PythonAnywhere server:

```bash
cd /home/ferrous77
python3.10 -m pip install --user --upgrade pip
python3.10 -m pip install --user --upgrade 'numexpr>=2.8.4'
python3.10 -m pip install --user --upgrade 'yfinance>=0.2.60'
python3.10 -m pip install --user --upgrade 'pandas>=2.0.0'
```

Or run the fixer script:
```bash
python3.10 pythonanywhere_dependency_fixer.py
```

## Step 3: Test the Deployment

```bash
cd /home/ferrous77
python3.10 quick_test_hook_server.py
```

If successful, test full workflow:
```bash
python3.10 pythonanywhere_daily_hook_server.py --force
```

## Step 4: Set Up Scheduled Task

1. Go to PythonAnywhere Dashboard → Tasks
2. Create new scheduled task:
   - **Command:** `python3.10 /home/ferrous77/pythonanywhere_daily_hook_server.py`
   - **Schedule:** Daily at 6:00 PM EST
   - **Description:** "Daily stock analysis and recommendations"

## Step 5: Verify Success

Check the web dashboard: https://ferrous77.pythonanywhere.com

Expected: 21 tracked symbols and recent analysis dates

## Key Corrections Made:

1. **Directory Structure**: Changed from `/home/ferrous77/stocks/` to `/home/ferrous77/`
2. **Script Paths**: Updated all command references
3. **Log Paths**: Updated log file locations
4. **Documentation**: Fixed all deployment guides

## Files with Corrected Paths:

- ✅ `pythonanywhere_daily_hook.py` - Updated usage instructions
- ✅ `pythonanywhere_daily_hook_server.py` - Server-specific version with hardcoded paths
- ✅ `quick_test_hook_server.py` - Server-specific test script
- ✅ `PYTHONANYWHERE_DEPLOYMENT.md` - Updated all path references
- ✅ `FINAL_DEPLOYMENT_CHECKLIST.md` - Updated all path references
- ✅ `check_deployment_status.py` - Updated instructions
- ✅ All deploy-package versions - Updated path references

The system is now correctly configured for the `/home/ferrous77/` directory structure!
