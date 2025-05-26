"""
Unit tests for Storage Layer (TimeSeriesDB)

Tests database operations including:
- Saving and retrieving daily snapshots
- Date range queries
- Data integrity
"""
import unittest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta
import sys
import os
import tempfile
import sqlite3

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from storage.timeseries_db import TimeSeriesDB
from storage.models import DailySnapshot


class TestTimeSeriesDB(unittest.TestCase):
    """Tests for TimeSeriesDB operations"""
    
    def setUp(self):
        """Create temporary database for testing"""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, 'test.db')
        self.db = TimeSeriesDB(db_path=self.db_path)
    
    def tearDown(self):
        """Clean up temporary files"""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def create_snapshot(self, symbol='AAPL', date='2024-01-15', close=150.0):
        """Helper to create a DailySnapshot"""
        return DailySnapshot(
            symbol=symbol,
            date=date,
            open=close - 1,
            high=close + 2,
            low=close - 2,
            close=close,
            volume=1000000,
            adjusted_close=close,
            strategy_signals={}
        )
    
    def test_save_and_retrieve_snapshot(self):
        """Should save and retrieve a daily snapshot correctly"""
        snapshot = self.create_snapshot('AAPL', '2024-01-15', 150.0)
        
        self.db.save_daily_snapshot(snapshot)
        result = self.db.get_daily_snapshot('AAPL', '2024-01-15')
        
        self.assertIsNotNone(result)
        self.assertEqual(result.symbol, 'AAPL')
        self.assertEqual(result.date, '2024-01-15')
        self.assertAlmostEqual(result.close, 150.0, delta=0.01)
    
    def test_update_existing_snapshot(self):
        """Should update existing snapshot with same symbol/date"""
        snapshot1 = self.create_snapshot('AAPL', '2024-01-15', 150.0)
        snapshot2 = self.create_snapshot('AAPL', '2024-01-15', 155.0)
        
        self.db.save_daily_snapshot(snapshot1)
        self.db.save_daily_snapshot(snapshot2)
        result = self.db.get_daily_snapshot('AAPL', '2024-01-15')
        
        # Should have the updated value
        self.assertAlmostEqual(result.close, 155.0, delta=0.01)
    
    def test_retrieve_nonexistent_returns_none(self):
        """Should return None for non-existent snapshot"""
        result = self.db.get_daily_snapshot('FAKE', '2024-01-15')
        
        self.assertIsNone(result)
    
    def test_get_symbol_data_returns_all_dates(self):
        """Should return all snapshots for a symbol"""
        # Save multiple days of data
        for day in range(5):
            date = f'2024-01-{15 + day:02d}'
            snapshot = self.create_snapshot('AAPL', date, 150.0 + day)
            self.db.save_daily_snapshot(snapshot)
        
        result = self.db.get_symbol_data('AAPL')
        
        self.assertEqual(len(result), 5)
    
    def test_get_symbol_data_date_range(self):
        """Should filter by date range"""
        # Save 10 days of data
        for day in range(10):
            date = f'2024-01-{10 + day:02d}'
            snapshot = self.create_snapshot('AAPL', date, 150.0 + day)
            self.db.save_daily_snapshot(snapshot)
        
        # Get only days 15-17
        result = self.db.get_symbol_data('AAPL', '2024-01-15', '2024-01-17')
        
        self.assertEqual(len(result), 3)
        dates = [r.date for r in result]
        self.assertIn('2024-01-15', dates)
        self.assertIn('2024-01-16', dates)
        self.assertIn('2024-01-17', dates)
    
    def test_get_latest_date(self):
        """Should return the most recent date for a symbol"""
        for day in range(5):
            date = f'2024-01-{15 + day:02d}'
            snapshot = self.create_snapshot('AAPL', date, 150.0)
            self.db.save_daily_snapshot(snapshot)
        
        result = self.db.get_latest_date('AAPL')
        
        self.assertEqual(result, '2024-01-19')
    
    def test_get_latest_date_empty_symbol(self):
        """Should return None for symbol with no data"""
        result = self.db.get_latest_date('EMPTY')
        
        self.assertIsNone(result)
    
    def test_multiple_symbols_isolated(self):
        """Data for different symbols should be isolated"""
        self.db.save_daily_snapshot(self.create_snapshot('AAPL', '2024-01-15', 150.0))
        self.db.save_daily_snapshot(self.create_snapshot('MSFT', '2024-01-15', 400.0))
        
        aapl = self.db.get_daily_snapshot('AAPL', '2024-01-15')
        msft = self.db.get_daily_snapshot('MSFT', '2024-01-15')
        
        self.assertAlmostEqual(aapl.close, 150.0, delta=0.01)
        self.assertAlmostEqual(msft.close, 400.0, delta=0.01)
    
    def test_strategy_signals_stored(self):
        """Strategy signals should be stored and retrieved"""
        snapshot = self.create_snapshot('AAPL', '2024-01-15', 150.0)
        snapshot.strategy_signals = {
            'momentum': {'signal': 'BUY', 'confidence': 0.8},
            'mean_reversion': {'signal': 'HOLD', 'confidence': 0.5}
        }
        
        self.db.save_daily_snapshot(snapshot)
        result = self.db.get_daily_snapshot('AAPL', '2024-01-15')
        
        self.assertIsNotNone(result.strategy_signals)
        self.assertEqual(result.strategy_signals['momentum']['signal'], 'BUY')


class TestDataIntegrity(unittest.TestCase):
    """Tests for data integrity and edge cases"""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, 'test.db')
        self.db = TimeSeriesDB(db_path=self.db_path)
    
    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_large_volume_numbers(self):
        """Should handle large volume numbers correctly"""
        snapshot = DailySnapshot(
            symbol='AAPL',
            date='2024-01-15',
            open=150.0,
            high=155.0,
            low=148.0,
            close=152.0,
            volume=5000000000,  # 5 billion
            adjusted_close=152.0,
            strategy_signals={}
        )
        
        self.db.save_daily_snapshot(snapshot)
        result = self.db.get_daily_snapshot('AAPL', '2024-01-15')
        
        self.assertEqual(result.volume, 5000000000)
    
    def test_decimal_precision(self):
        """Should maintain decimal precision for prices"""
        snapshot = DailySnapshot(
            symbol='AAPL',
            date='2024-01-15',
            open=150.12345,
            high=155.67890,
            low=148.11111,
            close=152.98765,
            volume=1000000,
            adjusted_close=152.98765,
            strategy_signals={}
        )
        
        self.db.save_daily_snapshot(snapshot)
        result = self.db.get_daily_snapshot('AAPL', '2024-01-15')
        
        self.assertAlmostEqual(result.close, 152.98765, places=4)
    
    def test_special_characters_in_signals(self):
        """Should handle special characters in strategy signals"""
        snapshot = DailySnapshot(
            symbol='AAPL',
            date='2024-01-15',
            open=150.0,
            high=155.0,
            low=148.0,
            close=152.0,
            volume=1000000,
            adjusted_close=152.0,
            strategy_signals={
                'test': {'reason': 'Price > $150 & RSI < 70'}
            }
        )
        
        self.db.save_daily_snapshot(snapshot)
        result = self.db.get_daily_snapshot('AAPL', '2024-01-15')
        
        self.assertEqual(result.strategy_signals['test']['reason'], 'Price > $150 & RSI < 70')


if __name__ == '__main__':
    unittest.main()
