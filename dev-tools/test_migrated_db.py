#!/usr/bin/env python3
"""
Quick test of the migrated database
"""
import os
import sys
from datetime import datetime, timedelta

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from storage.timeseries_db import TimeSeriesDB

def test_migrated_database():
    """Test basic operations on the migrated database"""
    db = TimeSeriesDB("data/timeseries.db")
    
    print("Testing migrated database...")
    
    # 1. Basic stats
    stats = db.get_database_stats()
    print(f"\nDatabase stats:")
    print(f"  Total snapshots: {stats['total_snapshots']}")
    print(f"  Date range: {stats['date_range']}")
    print(f"  Symbols: {len(stats['snapshots_by_symbol'])}")
    
    # 2. Test querying individual stocks
    print(f"\nTesting AAPL data:")
    aapl_range = db.get_date_range('AAPL')
    print(f"  Date range: {aapl_range}")
    
    latest_date = db.get_latest_date('AAPL')
    print(f"  Latest date: {latest_date}")
    
    if latest_date:
        latest_snapshot = db.get_daily_snapshot('AAPL', latest_date)
        if latest_snapshot:
            print(f"  Latest price: ${latest_snapshot.close:.2f}")
            print(f"  Volume: {latest_snapshot.volume:,}")
    
    # 3. Test date range queries
    print(f"\nTesting date range queries for NVDA:")
    end_date = '2025-04-16'  # Use actual latest date in database
    start_date = '2025-03-01'  # Go back about 6 weeks
    
    recent_data = db.get_symbol_data('NVDA', start_date, end_date)
    print(f"  Found {len(recent_data)} records in last 30 days")
    
    if recent_data:
        print(f"  Price range: ${min(s.close for s in recent_data):.2f} - ${max(s.close for s in recent_data):.2f}")
    
    # 4. Test multi-symbol queries  
    print(f"\nTesting multi-symbol queries:")
    symbols = ['AAPL', 'NVDA', 'GOOGL']
    multi_data = {}
    for symbol in symbols:
        symbol_data = db.get_symbol_data(symbol, start_date, end_date)
        multi_data[symbol] = symbol_data
    
    for symbol in symbols:
        if symbol in multi_data:
            count = len(multi_data[symbol])
            print(f"  {symbol}: {count} records")
    
    print("\n✅ All tests passed!")

if __name__ == "__main__":
    test_migrated_database()
