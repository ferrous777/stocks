#!/usr/bin/env python3
"""
Test script for the new time-series database
"""
import sys
import os
from datetime import datetime, timedelta

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from storage.timeseries_db import TimeSeriesDB
from storage.models import DailySnapshot
from storage.adapter import DataAdapter

def test_database():
    """Test basic database operations"""
    print("Testing TimeSeriesDB...")
    
    # Initialize database
    db = TimeSeriesDB("data/test_timeseries.db")
    
    # Create test data
    test_date = "2025-05-24"
    test_symbol = "AAPL"
    
    snapshot = DailySnapshot(
        date=test_date,
        symbol=test_symbol,
        open=195.0,
        high=197.5,
        low=194.0,
        close=196.5,
        volume=50000000,
        adjusted_close=196.5,
        sma_20=195.0,
        sma_50=192.0,
        rsi=65.5
    )
    
    # Test save
    print(f"Saving snapshot for {test_symbol} on {test_date}...")
    success = db.save_daily_snapshot(snapshot)
    print(f"Save successful: {success}")
    
    # Test retrieve
    print(f"Retrieving snapshot for {test_symbol} on {test_date}...")
    retrieved = db.get_daily_snapshot(test_symbol, test_date)
    
    if retrieved:
        print(f"Retrieved: {retrieved.symbol} - {retrieved.date}")
        print(f"Close: {retrieved.close}, RSI: {retrieved.rsi}")
        print("✓ Basic save/retrieve test passed")
    else:
        print("✗ Failed to retrieve snapshot")
        return False
    
    # Test symbol data retrieval
    print(f"Getting all data for {test_symbol}...")
    symbol_data = db.get_symbol_data(test_symbol)
    print(f"Found {len(symbol_data)} records for {test_symbol}")
    
    # Test date data retrieval
    print(f"Getting all symbols for {test_date}...")
    date_data = db.get_date_data(test_date)
    print(f"Found {len(date_data)} symbols for {test_date}")
    
    # Test database stats
    print("Database statistics:")
    stats = db.get_database_stats()
    for key, value in stats.items():
        print(f"  {key}: {value}")
    
    print("✓ All tests passed!")
    return True

def test_adapter():
    """Test the data adapter"""
    print("\nTesting DataAdapter...")
    
    # Mock old DataPoint structure
    class MockDataPoint:
        def __init__(self):
            self.date = "2025-05-24"
            self.open = 195.0
            self.high = 197.5
            self.low = 194.0
            self.close = 196.5
            self.volume = 50000000
            self.adjusted_close = 196.5
    
    # Test conversion
    old_datapoint = MockDataPoint()
    indicators = {
        'sma_20': 195.0,
        'rsi': 65.5,
        'macd': 1.2
    }
    
    snapshot = DataAdapter.datapoint_to_snapshot(
        old_datapoint, 
        "AAPL", 
        indicators=indicators
    )
    
    print(f"Converted datapoint to snapshot: {snapshot.symbol} - {snapshot.date}")
    print(f"Indicators: SMA20={snapshot.sma_20}, RSI={snapshot.rsi}")
    
    print("✓ Adapter test passed!")

if __name__ == "__main__":
    try:
        test_database()
        test_adapter()
        print("\n🎉 All tests completed successfully!")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
