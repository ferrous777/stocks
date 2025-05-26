"""
Unit tests for the Daily Scheduler's MarketDataCollector class
"""
import unittest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta
import json
import os
import sys

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from scheduler.daily_scheduler import MarketDataCollector


class TestMarketDataCollector(unittest.TestCase):
    """Unit tests for MarketDataCollector"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.collector = MarketDataCollector()
        self.collector.db = Mock()
        self.collector.market_data = Mock()
        
        # Create test cache directory
        os.makedirs('test_cache', exist_ok=True)
        self.collector.cache_dir = 'test_cache'
    
    def tearDown(self):
        """Clean up test fixtures"""
        # Clean up test cache
        import shutil
        if os.path.exists('test_cache'):
            shutil.rmtree('test_cache')
    
    def test_is_new_symbol_no_cache_file(self):
        """Test is_new_symbol when no cache file exists"""
        result = self.collector.is_new_symbol('NEWSTOCK')
        self.assertTrue(result)
    
    def test_is_new_symbol_empty_cache(self):
        """Test is_new_symbol with empty cache file"""
        cache_file = os.path.join(self.collector.cache_dir, 'EMPTY_historical.json')
        with open(cache_file, 'w') as f:
            json.dump({'data_points': []}, f)
        
        result = self.collector.is_new_symbol('EMPTY')
        self.assertTrue(result)
    
    def test_is_new_symbol_sufficient_data(self):
        """Test is_new_symbol with sufficient historical data"""
        cache_file = os.path.join(self.collector.cache_dir, 'AAPL_historical.json')
        
        # Create mock data with sufficient coverage and recent data
        data_points = []
        base_date = datetime.now() - timedelta(days=365 * 3)  # 3 years ago
        for i in range(600):  # 600 data points over 3 years
            date_str = (base_date + timedelta(days=i * 2)).strftime('%Y-%m-%d')
            data_points.append({'date': date_str, 'close': 100 + i})
        
        # Add recent data points (within last week)
        for i in range(5):
            recent_date = datetime.now() - timedelta(days=i)
            date_str = recent_date.strftime('%Y-%m-%d')
            data_points.append({'date': date_str, 'close': 150 + i})
        
        with open(cache_file, 'w') as f:
            json.dump({'data_points': data_points}, f)
        
        result = self.collector.is_new_symbol('AAPL')
        self.assertFalse(result)
    
    def test_get_missing_date_range_no_cache(self):
        """Test get_missing_date_range when no cache exists"""
        target_date = datetime.now() - timedelta(days=365)
        start_date, end_date = self.collector.get_missing_date_range('NOCACHE', target_date)
        
        self.assertEqual(start_date, target_date)
        self.assertIsInstance(end_date, datetime)
    
    def test_get_missing_date_range_with_gaps(self):
        """Test get_missing_date_range with data gaps"""
        cache_file = os.path.join(self.collector.cache_dir, 'GAPPY_historical.json')
        
        # Create data with significant gaps
        data_points = [
            {'date': '2023-01-01', 'close': 100},
            {'date': '2023-06-01', 'close': 110},  # 5-month gap
            {'date': '2024-01-01', 'close': 120}   # 7-month gap
        ]
        
        with open(cache_file, 'w') as f:
            json.dump({'data_points': data_points}, f)
        
        target_date = datetime(2023, 1, 1)
        start_date, end_date = self.collector.get_missing_date_range('GAPPY', target_date)
        
        self.assertIsNotNone(start_date)
        self.assertIsNotNone(end_date)
    
    @patch('scheduler.daily_scheduler.MarketData')
    def test_fetch_initial_historical_data_success(self, mock_market_data_class):
        """Test successful historical data fetch"""
        # Mock the market data response
        mock_data_obj = Mock()
        mock_data_obj.data_points = [
            Mock(date=datetime.now(), open=100, high=105, low=95, close=102, volume=1000)
        ]
        
        mock_response = {'AAPL': mock_data_obj}
        self.collector.market_data.get_batch_data.return_value = mock_response
        
        # Mock get_missing_date_range to return a range
        self.collector.get_missing_date_range = Mock(return_value=(
            datetime.now() - timedelta(days=365),
            datetime.now()
        ))
        
        result = self.collector.fetch_initial_historical_data('AAPL')
        self.assertTrue(result)
        self.collector.market_data.get_batch_data.assert_called_once()
    
    def test_fetch_initial_historical_data_no_missing_range(self):
        """Test fetch_initial_historical_data when no data is missing"""
        # Mock get_missing_date_range to return None, None
        self.collector.get_missing_date_range = Mock(return_value=(None, None))
        
        result = self.collector.fetch_initial_historical_data('AAPL')
        self.assertTrue(result)
        self.collector.market_data.get_batch_data.assert_not_called()
    
    @patch('scheduler.daily_scheduler.DailySnapshot')
    def test_fetch_latest_data_existing_symbol(self, mock_snapshot):
        """Test fetch_latest_data for existing symbol"""
        # Mock is_new_symbol to return False
        self.collector.is_new_symbol = Mock(return_value=False)
        
        # Mock database response
        self.collector.db.get_daily_snapshot.return_value = None
        
        # Mock market data response
        mock_data_obj = Mock()
        mock_data_obj.data_points = [
            Mock(date=datetime.now(), open=100, high=105, low=95, close=102, volume=1000)
        ]
        
        mock_response = {'AAPL': mock_data_obj}
        self.collector.market_data.get_batch_data_with_incremental_update.return_value = mock_response
        
        result = self.collector.fetch_latest_data('AAPL')
        self.assertIsNotNone(result)
    
    def test_fetch_latest_data_new_symbol(self):
        """Test fetch_latest_data for new symbol"""
        # Mock is_new_symbol to return True
        self.collector.is_new_symbol = Mock(return_value=True)
        
        # Mock fetch_initial_historical_data to return True
        self.collector.fetch_initial_historical_data = Mock(return_value=True)
        
        # Mock the rest of the flow
        self.collector.db.get_daily_snapshot.return_value = None
        
        mock_data_obj = Mock()
        mock_data_obj.data_points = [
            Mock(date=datetime.now(), open=100, high=105, low=95, close=102, volume=1000)
        ]
        
        mock_response = {'AAPL': mock_data_obj}
        self.collector.market_data.get_batch_data_with_incremental_update.return_value = mock_response
        
        result = self.collector.fetch_latest_data('AAPL')
        self.collector.fetch_initial_historical_data.assert_called_once_with('AAPL')
        self.assertIsNotNone(result)
    
    def test_fetch_latest_data_cache_hit(self):
        """Test fetch_latest_data when data already exists in cache"""
        # Mock is_new_symbol to return False (existing symbol)
        with patch.object(self.collector, 'is_new_symbol', return_value=False):
            # Mock database to return existing data
            mock_existing_data = Mock()
            self.collector.db.get_daily_snapshot.return_value = mock_existing_data
            
            result = self.collector.fetch_latest_data('AAPL', datetime.now())
            self.assertEqual(result, mock_existing_data)
    
    def test_fetch_all_symbols(self):
        """Test fetch_all_symbols method"""
        # Mock fetch_latest_data
        self.collector.fetch_latest_data = Mock(side_effect=[
            Mock(),  # AAPL result
            Mock(),  # MSFT result
            None     # GOOGL result (failed)
        ])
        
        symbols = ['AAPL', 'MSFT', 'GOOGL']
        results = self.collector.fetch_all_symbols(symbols)
        
        self.assertEqual(len(results), 3)
        self.assertIsNotNone(results['AAPL'])
        self.assertIsNotNone(results['MSFT'])
        self.assertIsNone(results['GOOGL'])
    
    def test_analyze_data_coverage_empty_data(self):
        """Test _analyze_data_coverage with empty data"""
        result = self.collector._analyze_data_coverage(
            'TEST', [], datetime.now() - timedelta(days=365), datetime.now()
        )
        
        self.assertTrue(result['needs_historical_pull'])
        self.assertIn('no data points', result['reason'])
    
    def test_analyze_data_coverage_stale_data(self):
        """Test _analyze_data_coverage with stale data"""
        # Create data that's 30 days old
        old_date = datetime.now() - timedelta(days=30)
        data_points = [
            {'date': old_date.strftime('%Y-%m-%d'), 'close': 100}
        ]
        
        result = self.collector._analyze_data_coverage(
            'TEST', data_points, datetime.now() - timedelta(days=365), datetime.now()
        )
        
        self.assertTrue(result['needs_historical_pull'])
        self.assertIn('latest data is', result['reason'])
    
    def test_analyze_data_coverage_sufficient_data(self):
        """Test _analyze_data_coverage with sufficient data"""
        # Create recent, dense data spanning at least 2.5 years
        data_points = []
        base_date = datetime.now() - timedelta(days=365 * 3)  # 3 years ago
        
        # Create daily data for 3 years with minimal gaps
        for i in range(365 * 3):  # Daily data for 3 years
            if i % 7 not in [5, 6]:  # Skip weekends to be more realistic
                date_str = (base_date + timedelta(days=i)).strftime('%Y-%m-%d')
                data_points.append({'date': date_str, 'close': 100 + i * 0.1})
        
        # Add recent data to ensure it's not stale
        for i in range(5):
            recent_date = datetime.now() - timedelta(days=i)
            date_str = recent_date.strftime('%Y-%m-%d')
            data_points.append({'date': date_str, 'close': 150})
        
        result = self.collector._analyze_data_coverage(
            'TEST', data_points, datetime.now() - timedelta(days=365 * 5), datetime.now()
        )
        
        self.assertFalse(result['needs_historical_pull'])
        # The exact reason may vary based on internal logic, so just check it's not needed
        self.assertIn('reason', result)
    
    def test_identify_missing_date_ranges_empty_data(self):
        """Test _identify_missing_date_ranges with empty data"""
        start_date = datetime.now() - timedelta(days=365)
        end_date = datetime.now()
        
        ranges = self.collector._identify_missing_date_ranges('TEST', [], start_date, end_date)
        
        self.assertEqual(len(ranges), 1)
        self.assertEqual(ranges[0], (start_date, end_date))
    
    def test_identify_missing_date_ranges_with_gaps(self):
        """Test _identify_missing_date_ranges with data gaps"""
        data_points = [
            {'date': '2024-01-01', 'close': 100},
            {'date': '2024-01-02', 'close': 101},
            {'date': '2024-01-15', 'close': 102},  # 13-day gap
            {'date': '2024-01-16', 'close': 103}
        ]
        
        start_date = datetime(2024, 1, 1)
        end_date = datetime(2024, 1, 20)
        
        ranges = self.collector._identify_missing_date_ranges('TEST', data_points, start_date, end_date)
        
        # Should identify the gap and missing end range
        self.assertGreater(len(ranges), 0)


if __name__ == '__main__':
    unittest.main()
