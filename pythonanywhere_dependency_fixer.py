#!/usr/bin/env python3
"""
PythonAnywhere Dependency Fixer
Fix the dependency issues preventing the daily hook from running
"""

import subprocess
import sys

def run_command(command, description):
    """Run a shell command and handle errors"""
    print(f"🔧 {description}...")
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=300
        )
        
        if result.returncode == 0:
            print(f"✅ {description} completed successfully")
            if result.stdout.strip():
                print(f"   Output: {result.stdout.strip()[-200:]}")  # Last 200 chars
        else:
            print(f"❌ {description} failed")
            print(f"   Error: {result.stderr}")
            return False
            
    except subprocess.TimeoutExpired:
        print(f"❌ {description} timed out")
        return False
    except Exception as e:
        print(f"❌ {description} failed with exception: {e}")
        return False
    
    return True

def main():
    print("PythonAnywhere Dependency Fixer")
    print("=" * 40)
    print()
    
    # List of commands to run
    commands = [
        ("python3.10 -m pip install --user --upgrade pip", "Upgrading pip"),
        ("python3.10 -m pip install --user --upgrade 'numexpr>=2.8.4'", "Upgrading numexpr"),
        ("python3.10 -m pip install --user --upgrade 'yfinance>=0.2.60'", "Upgrading yfinance"),
        ("python3.10 -m pip install --user --upgrade 'pandas>=2.0.0'", "Upgrading pandas"),
        ("python3.10 -m pip install --user --upgrade 'numpy>=1.24.0'", "Upgrading numpy"),
        ("python3.10 -m pip install --user --upgrade 'requests>=2.28.0'", "Upgrading requests"),
        ("python3.10 -m pip install --user --upgrade 'python-dateutil>=2.8.0'", "Upgrading python-dateutil"),
    ]
    
    success_count = 0
    for command, description in commands:
        if run_command(command, description):
            success_count += 1
        print()
    
    print(f"✅ Dependency fixes completed!")
    print(f"   Successful: {success_count}/{len(commands)}")
    print()
    print("Next steps:")
    print("1. Run the test script: python3.10 quick_test_hook.py")
    print("2. If successful, run: python3.10 pythonanywhere_daily_hook.py --force")

if __name__ == "__main__":
    main()
