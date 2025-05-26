#!/usr/bin/env python3
"""
Cache verification script for PythonAnywhere deployment
This script checks if cache files have the expected data coverage
"""

import json
import os
from datetime import datetime, timedelta

def verify_cache_file(symbol):
    """Verify a cache file has proper data coverage"""
    cache_file = f"cache/{symbol}_historical.json"
    
    print(f"\n🔍 Verifying cache for {symbol}:")
    print(f"   📁 File: {cache_file}")
    
    if not os.path.exists(cache_file):
        print("   ❌ Cache file does not exist")
        return False
    
    # Check file size
    file_size = os.path.getsize(cache_file)
    print(f"   📊 File size: {file_size:,} bytes")
    
    try:
        with open(cache_file, 'r') as f:
            data = json.load(f)
        
        data_points = data.get('data_points', [])
        total_points = len(data_points)
        print(f"   📈 Data points: {total_points:,}")
        
        if total_points == 0:
            print("   ❌ No data points found")
            return False
        
        # Analyze date coverage
        dates = [dp['date'] for dp in data_points]
        min_date = min(dates)
        max_date = max(dates)
        print(f"   📅 Date range: {min_date} to {max_date}")
        
        # Check if we have reasonable 5-year coverage
        start_date = datetime.strptime(min_date, '%Y-%m-%d')
        end_date = datetime.strptime(max_date, '%Y-%m-%d')
        days_covered = (end_date - start_date).days
        print(f"   ⏱️  Days covered: {days_covered}")
        
        # Check recent data completeness (last 30 days)
        today = datetime.now().date()
        recent_start = today - timedelta(days=30)
        recent_dates = [d for d in dates if datetime.strptime(d, '%Y-%m-%d').date() >= recent_start]
        print(f"   🕒 Recent data (30 days): {len(recent_dates)} points")
        
        # Determine if cache is complete
        is_complete = total_points > 1000 and days_covered > 1000  # Rough estimate for 5 years
        status = "✅ COMPLETE" if is_complete else "⚠️  PARTIAL"
        print(f"   🎯 Status: {status}")
        
        return is_complete
        
    except json.JSONDecodeError as e:
        print(f"   ❌ JSON parsing error: {e}")
        return False
    except Exception as e:
        print(f"   ❌ Error reading file: {e}")
        return False

def main():
    """Main verification function"""
    print("🔍 Cache Verification Report")
    print("=" * 50)
    
    # Test symbols to verify
    test_symbols = ['AAPL', 'MSFT', 'GOOGL', 'NVDA']
    
    results = {}
    for symbol in test_symbols:
        results[symbol] = verify_cache_file(symbol)
    
    print("\n📋 Summary:")
    print("-" * 30)
    complete_count = sum(results.values())
    total_count = len(results)
    
    for symbol, is_complete in results.items():
        status = "✅" if is_complete else "⚠️"
        print(f"   {status} {symbol}")
    
    print(f"\n🎯 Overall: {complete_count}/{total_count} caches complete")
    
    if complete_count == total_count:
        print("🎉 All caches are properly populated!")
    else:
        print("⚠️  Some caches need more data - this is normal after initial deployment")

if __name__ == "__main__":
    main()
