#!/usr/bin/env python3
"""
PythonAnywhere Deployment Test Script

This script tests if the daily hook can run successfully on PythonAnywhere.
Run this manually on your PythonAnywhere console to verify the deployment.

Instructions:
1. Upload this file to your PythonAnywhere account
2. Open a Bash console on PythonAnywhere
3. Run: python3 test_pythonanywhere_deployment.py
"""

import os
import sys
import traceback
from pathlib import Path
from datetime import datetime

def test_deployment():
    """Test the daily hook deployment on PythonAnywhere"""
    
    print("="*60)
    print("PythonAnywhere Daily Hook Deployment Test")
    print("="*60)
    print(f"Test started at: {datetime.now()}")
    print()
    
    # Test 1: Check working directory and file structure
    print("TEST 1: File Structure Check")
    print("-" * 30)
    
    current_dir = Path.cwd()
    print(f"Current directory: {current_dir}")
    
    required_files = [
        'pythonanywhere_daily_hook.py',
        'src/',
        'requirements.txt'
    ]
    
    missing_files = []
    for file_path in required_files:
        full_path = current_dir / file_path
        if full_path.exists():
            print(f"✅ Found: {file_path}")
        else:
            print(f"❌ Missing: {file_path}")
            missing_files.append(file_path)
    
    if missing_files:
        print(f"\n❌ DEPLOYMENT ISSUE: Missing files: {missing_files}")
        print("Please upload these files to your PythonAnywhere account.")
        return False
    
    print("✅ All required files present")
    print()
    
    # Test 2: Python path and imports
    print("TEST 2: Import Check")
    print("-" * 30)
    
    try:
        # Add src to path
        src_path = current_dir / 'src'
        sys.path.insert(0, str(src_path))
        
        # Test critical imports
        from market_calendar.market_calendar import MarketCalendar, MarketType
        from scheduler.daily_scheduler import DailyScheduler
        from config.config_manager import ConfigManager
        
        print("✅ All critical imports successful")
        
    except ImportError as e:
        print(f"❌ IMPORT ERROR: {e}")
        print("This suggests missing dependencies or incorrect file structure.")
        return False
    except Exception as e:
        print(f"❌ UNEXPECTED ERROR: {e}")
        traceback.print_exc()
        return False
    
    print()
    
    # Test 3: Daily hook initialization
    print("TEST 3: Daily Hook Initialization")
    print("-" * 30)
    
    try:
        # Import the hook class
        sys.path.insert(0, str(current_dir))
        from pythonanywhere_daily_hook import PythonAnywhereSchedulerHook
        
        # Initialize
        hook = PythonAnywhereSchedulerHook()
        print("✅ Daily hook initialized successfully")
        
        # Test market calendar
        from datetime import date
        should_run, reason = hook.should_run_today(date.today())
        print(f"✅ Market calendar check: {reason}")
        
    except Exception as e:
        print(f"❌ INITIALIZATION ERROR: {e}")
        traceback.print_exc()
        return False
    
    print()
    
    # Test 4: Database and storage
    print("TEST 4: Database Connection")
    print("-" * 30)
    
    try:
        from storage.timeseries_db import TimeSeriesDB
        db = TimeSeriesDB()
        print("✅ Database connection successful")
        
    except Exception as e:
        print(f"❌ DATABASE ERROR: {e}")
        print("This might indicate missing dependencies or database issues.")
        return False
    
    print()
    
    # Test 5: Market data API
    print("TEST 5: Market Data API")
    print("-" * 30)
    
    try:
        from market_data.market_data import MarketData
        api = MarketData()
        print("✅ Market data API initialized")
        
        # Test a simple fetch (this will use cache if available)
        print("Testing data fetch for AAPL...")
        from datetime import datetime, timedelta
        end_date = datetime.now()
        start_date = end_date - timedelta(days=5)
        
        data = api.get_historical_data('AAPL', start_date, end_date)
        if data and len(data.data_points) > 0:
            latest = data.data_points[-1]
            print(f"✅ Successfully fetched AAPL data: ${latest.close:.2f} on {latest.date}")
        else:
            print("⚠️  No data returned (might be cached or API limit)")
        
    except Exception as e:
        print(f"❌ MARKET DATA ERROR: {e}")
        print("This might indicate API issues or network problems.")
        # Don't return False here as this could be a temporary issue
    
    print()
    
    # Test 6: Try a dry run of the daily hook
    print("TEST 6: Daily Hook Dry Run")
    print("-" * 30)
    
    try:
        print("Attempting dry run (force mode)...")
        results = hook.run_daily_workflow(force_run=True)
        
        if results.get('status') == 'completed':
            print("✅ Daily hook executed successfully!")
            
            # Print summary
            data_results = results.get('data', {})
            successful_fetches = sum(1 for result in data_results.values() if result is not None)
            total_symbols = len(data_results)
            
            print(f"   📊 Data fetched: {successful_fetches}/{total_symbols} symbols")
            
            strategies = results.get('strategies', {})
            if strategies:
                signal_counts = {'BUY': 0, 'SELL': 0, 'HOLD': 0}
                for symbol_strategies in strategies.values():
                    for strategy_result in symbol_strategies.values():
                        signal = strategy_result.get('signal', 'HOLD')
                        if signal in signal_counts:
                            signal_counts[signal] += 1
                
                print(f"   📈 Signals: {signal_counts['BUY']} BUY, {signal_counts['SELL']} SELL, {signal_counts['HOLD']} HOLD")
            
        elif results.get('status') == 'error':
            print(f"❌ Daily hook failed: {results.get('error', 'Unknown error')}")
            return False
        else:
            print(f"⚠️  Daily hook returned status: {results.get('status')}")
            
    except Exception as e:
        print(f"❌ DRY RUN ERROR: {e}")
        traceback.print_exc()
        return False
    
    print()
    print("="*60)
    print("✅ DEPLOYMENT TEST COMPLETED SUCCESSFULLY!")
    print("="*60)
    print()
    print("Next Steps:")
    print("1. Set up the scheduled task in PythonAnywhere dashboard")
    print("2. Configure it to run daily at market close (6:00 PM EST)")
    print("3. Monitor the first few executions")
    print()
    print("Command for scheduled task:")
    print(f"   {current_dir}/pythonanywhere_daily_hook.py")
    
    return True

if __name__ == "__main__":
    try:
        success = test_deployment()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n❌ Test interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}")
        traceback.print_exc()
        sys.exit(1)
