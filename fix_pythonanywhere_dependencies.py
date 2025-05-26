#!/usr/bin/env python3
"""
PythonAnywhere Dependency Fixer

This script fixes the dependency issues on PythonAnywhere by:
1. Upgrading numexpr to resolve pandas warnings
2. Upgrading yfinance to fix the YFRateLimitError import issue
3. Installing any other missing dependencies
"""

import subprocess
import sys
import os

def run_command(command, description):
    """Run a command and handle errors"""
    print(f"🔧 {description}...")
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"✅ {description} completed successfully")
            if result.stdout.strip():
                print(f"   Output: {result.stdout.strip()[-200:]}")  # Last 200 chars
        else:
            print(f"❌ {description} failed")
            print(f"   Error: {result.stderr.strip()}")
            return False
    except Exception as e:
        print(f"❌ {description} failed with exception: {e}")
        return False
    return True

def fix_dependencies():
    """Fix all dependency issues"""
    
    print("PythonAnywhere Dependency Fixer")
    print("=" * 40)
    print()
    
    # Upgrade pip first
    run_command("pip3.10 install --user --upgrade pip", "Upgrading pip")
    
    # Fix numexpr version (for pandas warning)
    run_command("pip3.10 install --user --upgrade 'numexpr>=2.8.4'", "Upgrading numexpr")
    
    # Fix yfinance version (for YFRateLimitError import)
    run_command("pip3.10 install --user --upgrade 'yfinance>=0.2.18'", "Upgrading yfinance")
    
    # Ensure other critical dependencies are current
    dependencies = [
        "pandas>=2.0.0",
        "numpy>=1.24.0", 
        "requests>=2.28.0",
        "python-dateutil>=2.8.0"
    ]
    
    for dep in dependencies:
        run_command(f"pip3.10 install --user --upgrade '{dep}'", f"Upgrading {dep.split('>=')[0]}")
    
    print()
    print("✅ Dependency fixes completed!")
    print()
    print("Next steps:")
    print("1. Run the test script: python3 quick_test_hook.py")
    print("2. If successful, run: python3 pythonanywhere_daily_hook.py --force")

if __name__ == "__main__":
    fix_dependencies()
