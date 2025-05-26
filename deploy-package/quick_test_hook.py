#!/usr/bin/env python3
"""
Simple Daily Hook Test - Can be run from web interface

This is a minimal test to verify the daily hook works on PythonAnywhere
without requiring console access.
"""

import sys
import os
from pathlib import Path
from datetime import datetime

# Ensure we're in the correct directory
script_dir = Path(__file__).parent.absolute()
os.chdir(script_dir)
src_path = script_dir / 'src'
sys.path.insert(0, str(src_path))

def quick_test():
    """Quick test that can be called from web interface"""
    
    result = {
        'test_time': str(datetime.now()),
        'status': 'unknown',
        'tests': {}
    }
    
    try:
        # Test 1: Basic imports
        try:
            from pythonanywhere_daily_hook import PythonAnywhereSchedulerHook
            result['tests']['imports'] = 'SUCCESS'
        except Exception as e:
            result['tests']['imports'] = f'FAILED: {str(e)}'
            result['status'] = 'error'
            return result
        
        # Test 2: Hook initialization
        try:
            hook = PythonAnywhereSchedulerHook()
            result['tests']['initialization'] = 'SUCCESS'
        except Exception as e:
            result['tests']['initialization'] = f'FAILED: {str(e)}'
            result['status'] = 'error'
            return result
        
        # Test 3: Market calendar
        try:
            from datetime import date
            should_run, reason = hook.should_run_today(date.today())
            result['tests']['market_calendar'] = f'SUCCESS: {reason}'
        except Exception as e:
            result['tests']['market_calendar'] = f'FAILED: {str(e)}'
        
        # Test 4: Quick workflow test
        try:
            # Just test the workflow without forcing execution
            workflow_results = hook.run_daily_workflow(force_run=False)
            if workflow_results.get('status') in ['completed', 'skipped']:
                result['tests']['workflow'] = f"SUCCESS: {workflow_results.get('status')}"
                result['status'] = 'success'
            else:
                result['tests']['workflow'] = f"WARNING: {workflow_results.get('status')}"
                result['status'] = 'partial'
        except Exception as e:
            result['tests']['workflow'] = f'FAILED: {str(e)}'
            result['status'] = 'error'
        
        if result['status'] == 'unknown':
            result['status'] = 'success'
            
    except Exception as e:
        result['status'] = 'error'
        result['error'] = str(e)
    
    return result

if __name__ == "__main__":
    result = quick_test()
    
    print("PythonAnywhere Daily Hook Quick Test")
    print("=" * 40)
    print(f"Test Time: {result['test_time']}")
    print(f"Overall Status: {result['status'].upper()}")
    print()
    
    for test_name, test_result in result.get('tests', {}).items():
        status_icon = "✅" if "SUCCESS" in test_result else "❌" if "FAILED" in test_result else "⚠️"
        print(f"{status_icon} {test_name}: {test_result}")
    
    if 'error' in result:
        print(f"\nError: {result['error']}")
    
    print()
    if result['status'] == 'success':
        print("✅ Daily hook is ready for deployment!")
    elif result['status'] == 'partial':
        print("⚠️  Daily hook has minor issues but should work")
    else:
        print("❌ Daily hook has issues that need to be resolved")
