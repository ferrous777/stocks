#!/usr/bin/env python3
"""
Ticker Management Test Script
Tests all the ticker management functionality including add, remove, and validation.
"""

import requests
import json
import time

BASE_URL = "http://127.0.0.1:8090"

def test_add_ticker(symbol):
    """Test adding a new ticker."""
    print(f"\n🔹 Testing ADD ticker: {symbol}")
    
    response = requests.post(f"{BASE_URL}/api/add_ticker", 
                           json={"symbol": symbol})
    
    if response.status_code == 200:
        result = response.json()
        if result.get('success'):
            print(f"✅ Successfully added {symbol}")
            print(f"   Files created: {result.get('files_created', [])}")
            return True
        else:
            print(f"❌ Failed to add {symbol}: {result.get('error')}")
            return False
    else:
        print(f"❌ HTTP Error {response.status_code}")
        return False

def test_remove_ticker(symbol):
    """Test removing a ticker."""
    print(f"\n🔹 Testing REMOVE ticker: {symbol}")
    
    response = requests.post(f"{BASE_URL}/api/remove_ticker", 
                           json={"symbol": symbol})
    
    if response.status_code == 200:
        result = response.json()
        if result.get('success'):
            print(f"✅ Successfully removed {symbol}")
            print(f"   Files removed: {result.get('files_removed', [])}")
            return True
        else:
            print(f"❌ Failed to remove {symbol}: {result.get('error')}")
            return False
    else:
        print(f"❌ HTTP Error {response.status_code}")
        return False

def test_duplicate_add(symbol):
    """Test adding a duplicate ticker."""
    print(f"\n🔹 Testing DUPLICATE add: {symbol}")
    
    response = requests.post(f"{BASE_URL}/api/add_ticker", 
                           json={"symbol": symbol})
    
    result = response.json()
    if response.status_code == 400 and not result.get('success'):
        print(f"✅ Correctly rejected duplicate: {symbol}")
        print(f"   Error message: {result.get('error')}")
        return True
    else:
        print(f"❌ Should have rejected duplicate {symbol}")
        return False

def test_invalid_remove(symbol):
    """Test removing a non-existent ticker."""
    print(f"\n🔹 Testing INVALID remove: {symbol}")
    
    response = requests.post(f"{BASE_URL}/api/remove_ticker", 
                           json={"symbol": symbol}")
    
    result = response.json()
    if response.status_code == 404 and not result.get('success'):
        print(f"✅ Correctly rejected invalid removal: {symbol}")
        print(f"   Error message: {result.get('error')}")
        return True
    else:
        print(f"❌ Should have rejected invalid removal {symbol}")
        return False

def test_recommendations_api(symbol):
    """Test that recommendations API works for new ticker."""
    print(f"\n🔹 Testing RECOMMENDATIONS API: {symbol}")
    
    response = requests.get(f"{BASE_URL}/api/recommendations/{symbol}/20250524")
    
    if response.status_code == 200:
        result = response.json()
        print(f"✅ Recommendations API working for {symbol}")
        print(f"   Action: {result.get('recommendations', {}).get('action', 'N/A')}")
        print(f"   Entry Price: ${result.get('recommendations', {}).get('entry_price', 'N/A')}")
        return True
    else:
        print(f"❌ Recommendations API failed for {symbol}")
        return False

def main():
    """Run comprehensive ticker management tests."""
    print("🚀 Starting Ticker Management System Tests")
    print("=" * 50)
    
    # Test data
    test_symbol = "PYPL"  # PayPal for testing
    invalid_symbol = "INVALID_TICKER_XYZ"
    
    tests_passed = 0
    total_tests = 6
    
    try:
        # Test 1: Add new ticker
        if test_add_ticker(test_symbol):
            tests_passed += 1
            
        time.sleep(1)  # Brief pause between tests
        
        # Test 2: Try adding duplicate (should fail)
        if test_duplicate_add(test_symbol):
            tests_passed += 1
            
        time.sleep(1)
        
        # Test 3: Test recommendations API
        if test_recommendations_api(test_symbol):
            tests_passed += 1
            
        time.sleep(1)
        
        # Test 4: Remove the ticker
        if test_remove_ticker(test_symbol):
            tests_passed += 1
            
        time.sleep(1)
        
        # Test 5: Try removing non-existent ticker (should fail)
        if test_invalid_remove(invalid_symbol):
            tests_passed += 1
            
        time.sleep(1)
        
        # Test 6: Try removing already removed ticker (should fail)
        if test_invalid_remove(test_symbol):
            tests_passed += 1
        
    except requests.exceptions.ConnectionError:
        print("❌ Could not connect to Flask server. Make sure it's running on port 8090.")
        return
    
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return
    
    # Summary
    print("\n" + "=" * 50)
    print(f"📊 Test Results: {tests_passed}/{total_tests} tests passed")
    
    if tests_passed == total_tests:
        print("🎉 All tests PASSED! Ticker management system is working perfectly.")
    else:
        print(f"⚠️  {total_tests - tests_passed} test(s) FAILED. Check the output above.")
    
    print("\n📋 Available API Endpoints:")
    print("   - POST /api/add_ticker")
    print("   - POST /api/remove_ticker")
    print("   - GET /api/recommendations/{symbol}/{date}")
    print("   - GET /api/backtest/{symbol}/{date}")
    print("\n🌐 Dashboard: http://127.0.0.1:8090")

if __name__ == "__main__":
    main()
