"""
Integration tests for the Daily Scheduler system
"""
import unittest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta
import json
import os
import sys
import tempfile

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from scheduler.daily_scheduler import MarketDataCollector, StrategyRunner


class TestDailySchedulerIntegration(unittest.TestCase):
    """Integration tests for Daily Scheduler components"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        
        # Initialize components
        self.collector = MarketDataCollector()
        self.strategy_runner = StrategyRunner()
        
        # Mock external dependencies
        self.collector.db = Mock()
        self.collector.market_data = Mock()
        self.collector.cache_dir = self.temp_dir
        
        self.strategy_runner.db = Mock()
    
    def tearDown(self):
        """Clean up test fixtures"""
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
    
    def test_full_workflow_new_symbol(self):
        """Test complete workflow for a new symbol"""
        symbol = 'NEWSTOCK'
        test_date = datetime.now()
        
        # Mock market data response for initial historical fetch
        mock_historical_data = Mock()
        mock_historical_data.data_points = [
            Mock(date=test_date - timedelta(days=i), open=100+i, high=105+i, 
                 low=95+i, close=102+i, volume=1000000)
            for i in range(365)  # 1 year of data
        ]
        
        self.collector.market_data.get_batch_data.return_value = {symbol: mock_historical_data}
        
        # Mock incremental update response
        mock_daily_data = Mock()
        mock_daily_data.data_points = [
            Mock(date=test_date, open=150, high=155, low=145, close=152, volume=1200000)
        ]
        
        self.collector.market_data.get_batch_data_with_incremental_update.return_value = {symbol: mock_daily_data}
        
        # Test the workflow
        # 1. Fetch latest data (should trigger historical fetch for new symbol)
        daily_snapshot = self.collector.fetch_latest_data(symbol, test_date)
        
        # Verify historical data was fetched
        self.collector.market_data.get_batch_data.assert_called()
        
        # Verify daily snapshot was created
        self.assertIsNotNone(daily_snapshot)
        # The daily snapshot is a mock, so just verify it was returned
        self.assertTrue(hasattr(daily_snapshot, 'symbol') or daily_snapshot is not None)
        
        # 2. Run strategies on the fetched data
        # Mock historical data for strategy analysis
        mock_strategy_data = [
            Mock(date=(test_date - timedelta(days=i)).strftime('%Y-%m-%d'), 
                 close=100+i, open=99+i, high=101+i, low=98+i, volume=1000000)
            for i in range(30)
        ]
        
        self.strategy_runner.db.get_symbol_data.return_value = mock_strategy_data
        
        strategy_results = self.strategy_runner.run_all_strategies(symbol, test_date)
        
        # Verify strategies were executed
        self.assertIsInstance(strategy_results, dict)
        self.assertGreater(len(strategy_results), 0)
    
    def test_full_workflow_existing_symbol(self):
        """Test complete workflow for an existing symbol with sufficient data"""
        symbol = 'AAPL'
        test_date = datetime.now()
        
        # Create cache file with sufficient historical data
        cache_file = os.path.join(self.collector.cache_dir, f'{symbol}_historical.json')
        
        # Create 3 years of historical data with recent data points
        data_points = []
        base_date = datetime.now() - timedelta(days=365 * 3)
        
        # Add historical data points (3 years worth)
        for i in range(365 * 3):
            if i % 7 not in [5, 6]:  # Skip weekends
                date_str = (base_date + timedelta(days=i)).strftime('%Y-%m-%d')
                data_points.append({
                    'date': date_str,
                    'close': 100 + i * 0.01,
                    'open': 99 + i * 0.01,
                    'high': 101 + i * 0.01,
                    'low': 98 + i * 0.01,
                    'volume': 1000000
                })
        
        # Add very recent data (within last week) to ensure it's not considered stale
        for i in range(5):
            recent_date = datetime.now() - timedelta(days=i)
            date_str = recent_date.strftime('%Y-%m-%d')
            data_points.append({
                'date': date_str,
                'close': 150,
                'open': 149,
                'high': 151,
                'low': 148,
                'volume': 1200000
            })
        
        with open(cache_file, 'w') as f:
            json.dump({'data_points': data_points}, f)
        
        # Mock daily data fetch
        mock_daily_data = Mock()
        mock_daily_data.data_points = [
            Mock(date=test_date, open=150, high=155, low=145, close=152, volume=1200000)
        ]
        
        self.collector.market_data.get_batch_data_with_incremental_update.return_value = {symbol: mock_daily_data}
        
        # Test the workflow
        # 1. Fetch latest data (should NOT trigger historical fetch)
        daily_snapshot = self.collector.fetch_latest_data(symbol, test_date)
        
        # Verify historical data was NOT fetched (symbol has sufficient data)
        self.collector.market_data.get_batch_data.assert_not_called()
        
        # Verify incremental update was called
        self.collector.market_data.get_batch_data_with_incremental_update.assert_called()
        
        # Verify daily snapshot was created
        self.assertIsNotNone(daily_snapshot)
        # The daily snapshot is a mock, so just verify it was returned
        self.assertTrue(hasattr(daily_snapshot, 'symbol') or daily_snapshot is not None)
    
    def test_batch_processing_multiple_symbols(self):
        """Test batch processing of multiple symbols"""
        symbols = ['AAPL', 'MSFT', 'GOOGL']
        test_date = datetime.now()
        
        # Mock responses for different symbols
        def mock_fetch_latest_data(symbol, date=None):
            return Mock(symbol=symbol, date=date or test_date, close=100)
        
        self.collector.fetch_latest_data = Mock(side_effect=mock_fetch_latest_data)
        
        # Test batch fetch
        results = self.collector.fetch_all_symbols(symbols, test_date)
        
        # Verify all symbols were processed
        self.assertEqual(len(results), len(symbols))
        for symbol in symbols:
            self.assertIn(symbol, results)
            self.assertIsNotNone(results[symbol])
            self.assertEqual(results[symbol].symbol, symbol)
    
    def test_error_recovery_workflow(self):
        """Test error recovery in the workflow"""
        symbol = 'ERRORSTOCK'
        test_date = datetime.now()
        
        # Mock market data to raise an exception
        self.collector.market_data.get_batch_data.side_effect = Exception("API Error")
        
        # Test that the system handles errors gracefully
        result = self.collector.fetch_latest_data(symbol, test_date)
        
        # Should return None but not crash
        self.assertIsNone(result)
    
    def test_data_consistency_across_components(self):
        """Test data consistency between collector and strategy runner"""
        symbol = 'CONSISTENT'
        test_date = datetime.now()
        
        # Create consistent test data
        test_data_points = []
        base_date = test_date - timedelta(days=30)
        
        for i in range(30):
            date_obj = base_date + timedelta(days=i)
            test_data_points.append(Mock(
                date=date_obj.strftime('%Y-%m-%d'),
                close=100 + i,
                open=99 + i,
                high=101 + i,
                low=98 + i,
                volume=1000000
            ))
        
        # Mock strategy runner to return the same data
        self.strategy_runner.db.get_symbol_data.return_value = test_data_points
        
        # Mock collector's daily data
        mock_daily_data = Mock()
        mock_daily_data.data_points = [test_data_points[-1]]  # Latest data point
        
        self.collector.market_data.get_batch_data_with_incremental_update.return_value = {symbol: mock_daily_data}
        
        # Fetch latest data
        daily_snapshot = self.collector.fetch_latest_data(symbol, test_date)
        
        # Run strategies
        strategy_results = self.strategy_runner.run_all_strategies(symbol, test_date)
        
        # Verify data consistency
        if daily_snapshot:
            latest_price = test_data_points[-1].close
            self.assertEqual(daily_snapshot.close, latest_price)
        
        # Verify strategy results are based on consistent data
        self.assertIsInstance(strategy_results, dict)
    
    def test_performance_with_large_dataset(self):
        """Test system performance with large datasets"""
        symbol = 'BIGDATA'
        test_date = datetime.now()
        
        # Create large dataset (5 years of daily data)
        large_dataset = []
        base_date = test_date - timedelta(days=365 * 5)
        
        for i in range(365 * 5):
            large_dataset.append(Mock(
                date=(base_date + timedelta(days=i)).strftime('%Y-%m-%d'),
                close=100 + i * 0.01,
                open=99 + i * 0.01,
                high=101 + i * 0.01,
                low=98 + i * 0.01,
                volume=1000000
            ))
        
        # Mock strategy runner with large dataset
        self.strategy_runner.db.get_symbol_data.return_value = large_dataset
        
        # Measure execution time (should complete reasonably quickly)
        import time
        start_time = time.time()
        
        strategy_results = self.strategy_runner.run_all_strategies(symbol, test_date)
        
        execution_time = time.time() - start_time
        
        # Should complete within reasonable time (< 5 seconds for this test)
        self.assertLess(execution_time, 5.0)
        self.assertIsInstance(strategy_results, dict)
    
    def test_cache_invalidation_workflow(self):
        """Test cache invalidation and refresh workflow"""
        symbol = 'CACHED'
        test_date = datetime.now()
        
        # Create cache file with old data
        cache_file = os.path.join(self.collector.cache_dir, f'{symbol}_historical.json')
        
        # Create old data (2 months old)
        old_date = test_date - timedelta(days=60)
        old_data_points = [{
            'date': old_date.strftime('%Y-%m-%d'),
            'close': 100,
            'open': 99,
            'high': 101,
            'low': 98,
            'volume': 1000000
        }]
        
        with open(cache_file, 'w') as f:
            json.dump({'data_points': old_data_points}, f)
        
        # Mock fresh data fetch
        mock_fresh_data = Mock()
        mock_fresh_data.data_points = [
            Mock(date=test_date - timedelta(days=i), open=100+i, high=105+i,
                 low=95+i, close=102+i, volume=1000000)
            for i in range(365)
        ]
        
        self.collector.market_data.get_batch_data.return_value = {symbol: mock_fresh_data}
        
        # Mock daily update
        mock_daily_data = Mock()
        mock_daily_data.data_points = [
            Mock(date=test_date, open=150, high=155, low=145, close=152, volume=1200000)
        ]
        
        self.collector.market_data.get_batch_data_with_incremental_update.return_value = {symbol: mock_daily_data}
        
        # Should detect stale cache and refresh
        daily_snapshot = self.collector.fetch_latest_data(symbol, test_date)
        
        # Verify fresh data was fetched due to stale cache
        self.collector.market_data.get_batch_data.assert_called()
        self.assertIsNotNone(daily_snapshot)


if __name__ == '__main__':
    unittest.main()
