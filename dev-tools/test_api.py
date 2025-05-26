#!/usr/bin/env python3
"""
Test script to verify API endpoints and data availability for mutual funds
"""

import requests
import json

# Test configuration
BASE_URL = "http://127.0.0.1:8090"
FUND_SYMBOLS = ['KMKNX', 'FDEGX', 'QQQ', 'VUG', 'IWF', 'SPYG', 'VGT', 'FDN', 'VEA', 'VWO', 'FEZ', 'EWJ', 'MCHI', 'INDA', 'EWZ']
TEST_DATE = "20250524"

def test_home_page():
    """Test that home page loads and returns symbol data"""
    print("Testing home page...")
    try:
        response = requests.get(f"{BASE_URL}/")
        if response.status_code == 200:
            print(f"✓ Home page loads successfully")
            # Check if fund symbols are in the page content
            for symbol in FUND_SYMBOLS[:5]:  # Test first 5
                if symbol in response.text:
                    print(f"✓ {symbol} found in page content")
                else:
                    print(f"✗ {symbol} NOT found in page content")
        else:
            print(f"✗ Home page failed with status {response.status_code}")
    except Exception as e:
        print(f"✗ Home page error: {e}")

def test_api_endpoints():
    """Test API endpoints for mutual funds"""
    print(f"\nTesting API endpoints for date {TEST_DATE}...")
    
    working_symbols = []
    for symbol in FUND_SYMBOLS:
        try:
            response = requests.get(f"{BASE_URL}/api/recommendations/{symbol}/{TEST_DATE}")
            if response.status_code == 200:
                data = response.json()
                print(f"✓ {symbol}: {data.get('recommendations', {}).get('action', 'NO ACTION')} at ${data.get('recommendations', {}).get('entry_price', 'N/A')}")
                working_symbols.append(symbol)
            else:
                print(f"✗ {symbol}: HTTP {response.status_code}")
        except Exception as e:
            print(f"✗ {symbol}: Error - {e}")
    
    print(f"\nWorking symbols: {working_symbols}")
    return working_symbols

def test_fallback_dates():
    """Test fallback dates for symbols that don't have current date data"""
    print(f"\nTesting fallback dates...")
    fallback_dates = ["20250416", "20250412"]
    
    for symbol in FUND_SYMBOLS[:3]:  # Test first 3
        print(f"\nTesting {symbol}:")
        found_data = False
        
        # Try primary date
        try:
            response = requests.get(f"{BASE_URL}/api/recommendations/{symbol}/{TEST_DATE}")
            if response.status_code == 200:
                print(f"  ✓ Primary date {TEST_DATE} works")
                found_data = True
            else:
                print(f"  ✗ Primary date {TEST_DATE} failed")
        except:
            print(f"  ✗ Primary date {TEST_DATE} error")
        
        # Try fallback dates if primary failed
        if not found_data:
            for fallback_date in fallback_dates:
                try:
                    response = requests.get(f"{BASE_URL}/api/recommendations/{symbol}/{fallback_date}")
                    if response.status_code == 200:
                        data = response.json()
                        print(f"  ✓ Fallback date {fallback_date} works: {data.get('recommendations', {}).get('action', 'NO ACTION')}")
                        found_data = True
                        break
                    else:
                        print(f"  ✗ Fallback date {fallback_date} failed")
                except:
                    print(f"  ✗ Fallback date {fallback_date} error")

if __name__ == "__main__":
    print("=== Mutual Funds API Test ===")
    test_home_page()
    working_symbols = test_api_endpoints()
    test_fallback_dates()
    
    print(f"\n=== Summary ===")
    print(f"Total fund symbols tested: {len(FUND_SYMBOLS)}")
    print(f"Working symbols: {len(working_symbols) if 'working_symbols' in locals() else 0}")
    if 'working_symbols' in locals() and working_symbols:
        print(f"Working symbols: {', '.join(working_symbols)}")
