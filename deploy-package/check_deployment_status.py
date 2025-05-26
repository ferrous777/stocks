#!/usr/bin/env python3
"""
Remote Status Checker for PythonAnywhere Daily Hook

This script can be used to remotely verify if the daily hook is working
by checking the web dashboard and analyzing the response.
"""

import requests
import re
from datetime import datetime

def check_pythonanywhere_status(base_url="https://ferrous77.pythonanywhere.com"):
    """Check the status of the PythonAnywhere deployment"""
    
    print("PythonAnywhere Daily Hook Status Checker")
    print("=" * 50)
    print(f"Checking: {base_url}")
    print(f"Time: {datetime.now()}")
    print()
    
    try:
        # Check main dashboard
        response = requests.get(base_url, timeout=30)
        
        if response.status_code != 200:
            print(f"❌ Website not accessible: HTTP {response.status_code}")
            return False
        
        content = response.text
        
        # Extract key metrics
        tracked_symbols = 0
        analysis_dates = 0
        
        # Look for symbol count
        symbol_match = re.search(r'(\d+)\s+Tracked Symbols?', content)
        if symbol_match:
            tracked_symbols = int(symbol_match.group(1))
        
        # Look for analysis dates count  
        date_match = re.search(r'(\d+)\s+Analysis Dates?', content)
        if date_match:
            analysis_dates = int(date_match.group(1))
        
        print(f"📊 Dashboard Status:")
        print(f"   Tracked Symbols: {tracked_symbols}")
        print(f"   Analysis Dates: {analysis_dates}")
        print()
        
        # Determine status
        if tracked_symbols > 0 and analysis_dates > 0:
            print("✅ SUCCESS: Daily hook is working!")
            print("   - Data is being collected")
            print("   - Analysis is running")
            print("   - Dashboard is populated")
            
            # Check for recent activity
            if "No analysis dates available" not in content:
                print("   - Recent activity detected")
            
            return True
            
        elif tracked_symbols > 0:
            print("⚠️  PARTIAL: Symbols tracked but no analysis dates")
            print("   - Data collection may be working")
            print("   - Analysis pipeline may have issues")
            return False
            
        else:
            print("❌ NOT RUNNING: No symbols or analysis data")
            print("   - Daily hook has not executed successfully")
            print("   - Check deployment and scheduled task")
            
            # Check for error indicators
            if "Oops! Something went wrong" in content:
                print("   - Error page detected in some sections")
            
            return False
        
    except requests.RequestException as e:
        print(f"❌ CONNECTION ERROR: {e}")
        return False
    except Exception as e:
        print(f"❌ UNEXPECTED ERROR: {e}")
        return False

def print_deployment_steps():
    """Print next steps for deployment"""
    
    print()
    print("Next Steps:")
    print("-" * 20)
    print("1. Upload all files to /home/ferrous77/")
    print("2. Run test: python3 quick_test_hook.py")
    print("3. Set up scheduled task in PythonAnywhere dashboard")
    print("4. Manual test: python3 pythonanywhere_daily_hook.py --force")
    print("5. Wait for first scheduled execution")
    print()
    print("Expected after first run:")
    print("- 21 Tracked Symbols")
    print("- Recent Analysis Dates") 
    print("- Strategy signals visible")

if __name__ == "__main__":
    success = check_pythonanywhere_status()
    
    if not success:
        print_deployment_steps()
    
    print()
    print("For detailed deployment instructions, see:")
    print("PYTHONANYWHERE_DEPLOYMENT.md")
