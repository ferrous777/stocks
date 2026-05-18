"""
Unit tests for FundAnalyzer

Tests the fund prospectus calculations including:
- Multi-year performance (1, 3, 5, 10 year)
- Risk metrics (volatility, Sharpe ratio, max drawdown)
- Benchmark comparison
"""
import unittest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta
import sys
import os
import math

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from analysis.fund_analyzer import FundAnalyzer, FundAnalyzerConfig, PerformanceMetrics, RiskMetrics, FundInfo


class TestPerformanceCalculations(unittest.TestCase):
    """Tests for performance metric calculations"""
    
    def setUp(self):
        self.analyzer = FundAnalyzer(cache_dir='test_cache')
    
    def create_data_points(self, start_price, end_price, days, volatility=0):
        """Create test data with linear price movement and optional volatility"""
        data = []
        daily_change = (end_price - start_price) / days
        base_date = datetime.now() - timedelta(days=days)
        
        for i in range(days):
            price = start_price + (daily_change * i)
            # Add some noise for more realistic data
            noise = volatility * (i % 3 - 1) if volatility else 0
            data.append({
                'date': (base_date + timedelta(days=i)).strftime('%Y-%m-%d'),
                'open': price - 0.5,
                'high': price + 1 + noise,
                'low': price - 1 - noise,
                'close': price + noise,
                'volume': 1000000
            })
        return data
    
    def test_total_return_calculation(self):
        """Total return should be (end - start) / start * 100"""
        # 100 -> 150 = 50% return
        data = self.create_data_points(100, 150, 365)
        
        result = self.analyzer.calculate_period_performance(data, 1)
        
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result.total_return, 50.0, delta=5.0)
    
    def test_annualized_return_calculation(self):
        """Annualized return should use CAGR formula"""
        # 100 -> 121 over 2 years = 10% annualized (1.1^2 = 1.21)
        data = self.create_data_points(100, 121, 730)  # 2 years
        
        result = self.analyzer.calculate_period_performance(data, 2)
        
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result.annualized_return, 10.0, delta=2.0)
    
    def test_negative_return_calculation(self):
        """Should correctly calculate negative returns"""
        # 100 -> 80 = -20% return
        data = self.create_data_points(100, 80, 365)
        
        result = self.analyzer.calculate_period_performance(data, 1)
        
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result.total_return, -20.0, delta=5.0)
    
    def test_insufficient_data_returns_none(self):
        """Should return None when insufficient data for period"""
        data = self.create_data_points(100, 110, 100)  # Only 100 days
        
        result = self.analyzer.calculate_period_performance(data, 1)  # Need 365 days
        
        self.assertIsNone(result)

    def test_custom_coverage_threshold_allows_shorter_window(self):
        """Custom config should control the minimum coverage requirement"""
        analyzer = FundAnalyzer(cache_dir='test_cache', config=FundAnalyzerConfig(min_period_coverage=0.1))
        data = self.create_data_points(100, 110, 100)

        result = analyzer.calculate_period_performance(data, 1)

        self.assertIsNotNone(result)
    
    def test_all_periods_calculated(self):
        """calculate_all_periods should return dict with 1, 3, 5, 10 year results"""
        data = self.create_data_points(100, 200, 3700)  # ~10 years
        
        result = self.analyzer.calculate_all_periods(data)
        
        self.assertIn(1, result)
        self.assertIn(3, result)
        self.assertIn(5, result)
        self.assertIn(10, result)
        
        # Should have results for all periods with sufficient data
        self.assertIsNotNone(result[1])
        self.assertIsNotNone(result[3])
        self.assertIsNotNone(result[5])
    
    def test_volatility_calculation(self):
        """Volatility should be annualized standard deviation"""
        # Create volatile data
        data = self.create_data_points(100, 120, 365, volatility=5)
        
        result = self.analyzer.calculate_period_performance(data, 1)
        
        self.assertIsNotNone(result)
        self.assertGreater(result.volatility, 0)
    
    def test_max_drawdown_calculation(self):
        """Max drawdown should be the largest peak-to-trough decline"""
        # Create data with a drawdown: 100 -> 120 -> 100 -> 130
        data = []
        base_date = datetime.now() - timedelta(days=400)
        prices = (
            [100 + i for i in range(100)] +  # Rise to 200
            [200 - i for i in range(50)] +    # Fall to 150 (25% drawdown)
            [150 + i * 0.5 for i in range(250)]  # Rise to 275
        )
        for i, price in enumerate(prices):
            data.append({
                'date': (base_date + timedelta(days=i)).strftime('%Y-%m-%d'),
                'close': price,
                'open': price - 0.5,
                'high': price + 1,
                'low': price - 1,
                'volume': 1000000
            })
        
        result = self.analyzer.calculate_period_performance(data, 1)
        
        self.assertIsNotNone(result)
        self.assertGreater(result.max_drawdown, 20)  # Should catch the ~25% drawdown
    
    def test_sharpe_ratio_positive_for_good_returns(self):
        """Sharpe ratio should be positive for returns above risk-free rate"""
        # Strong uptrend with low volatility
        data = self.create_data_points(100, 130, 365, volatility=1)
        
        result = self.analyzer.calculate_period_performance(data, 1)
        
        self.assertIsNotNone(result)
        self.assertGreater(result.sharpe_ratio, 0)


class TestRiskMetrics(unittest.TestCase):
    """Tests for risk metric calculations"""
    
    def setUp(self):
        self.analyzer = FundAnalyzer(cache_dir='test_cache')
    
    def create_data_points(self, prices):
        """Create test data from price list"""
        data = []
        base_date = datetime.now() - timedelta(days=len(prices))
        for i, price in enumerate(prices):
            data.append({
                'date': (base_date + timedelta(days=i)).strftime('%Y-%m-%d'),
                'close': price,
                'open': price - 0.5,
                'high': price + 1,
                'low': price - 1,
                'volume': 1000000
            })
        return data
    
    def test_insufficient_data_returns_none(self):
        """Should return None when less than 252 days (1 year)"""
        prices = [100 + i * 0.1 for i in range(200)]
        data = self.create_data_points(prices)
        
        result = self.analyzer.calculate_risk_metrics(data)
        
        self.assertIsNone(result)
    
    def test_standard_deviation_calculated(self):
        """Should calculate annualized standard deviation"""
        prices = [100 + i * 0.1 + (i % 5 - 2) for i in range(300)]
        data = self.create_data_points(prices)
        
        result = self.analyzer.calculate_risk_metrics(data)
        
        self.assertIsNotNone(result)
        self.assertGreater(result.standard_deviation, 0)
    
    def test_downside_deviation_less_than_standard(self):
        """Downside deviation should be <= standard deviation"""
        prices = [100 + i * 0.1 + (i % 5 - 2) for i in range(300)]
        data = self.create_data_points(prices)
        
        result = self.analyzer.calculate_risk_metrics(data)
        
        self.assertIsNotNone(result)
        # For an uptrend, downside deviation should be lower
        self.assertLessEqual(result.downside_deviation, result.standard_deviation + 1)
    
    def test_beta_defaults_to_one_without_benchmark(self):
        """Beta should default to 1.0 when no benchmark provided"""
        prices = [100 + i * 0.1 for i in range(300)]
        data = self.create_data_points(prices)
        
        result = self.analyzer.calculate_risk_metrics(data, benchmark_data=None)
        
        self.assertIsNotNone(result)
        self.assertEqual(result.beta, 1.0)


class TestFundInfoFetching(unittest.TestCase):
    """Tests for fund info fetching from Yahoo Finance"""
    
    def setUp(self):
        self.analyzer = FundAnalyzer(cache_dir='test_cache')
    
    @patch('analysis.fund_analyzer.yf.Ticker')
    def test_fetch_fund_info_success(self, mock_ticker_class):
        """Should correctly parse Yahoo Finance fund info"""
        mock_ticker = MagicMock()
        mock_ticker.info = {
            'longName': 'Test Fund',
            'quoteType': 'ETF',
            'category': 'Large Blend',
            'annualReportExpenseRatio': 0.003,
            'fundFamily': 'Test Family',
            'totalAssets': 1000000000,
            'yield': 0.02,
            'ytdReturn': 0.15,
            'threeYearAverageReturn': 0.12,
            'fiveYearAverageReturn': 0.10
        }
        mock_ticker_class.return_value = mock_ticker
        
        result = self.analyzer.fetch_fund_info('TEST', use_cache=False)
        
        self.assertIsNotNone(result)
        self.assertEqual(result.name, 'Test Fund')
        self.assertEqual(result.fund_type, 'ETF')
        self.assertEqual(result.expense_ratio, 0.003)
    
    @patch('analysis.fund_analyzer.yf.Ticker')
    def test_fetch_fund_info_handles_missing_fields(self, mock_ticker_class):
        """Should handle missing fields gracefully"""
        mock_ticker = MagicMock()
        mock_ticker.info = {
            'shortName': 'Test Fund',
            'quoteType': 'MUTUALFUND'
        }
        mock_ticker_class.return_value = mock_ticker
        
        result = self.analyzer.fetch_fund_info('TEST', use_cache=False)
        
        self.assertIsNotNone(result)
        self.assertIsNone(result.expense_ratio)
        self.assertIsNone(result.total_assets)


class TestProspectusGeneration(unittest.TestCase):
    """Tests for complete prospectus generation"""
    
    def setUp(self):
        self.analyzer = FundAnalyzer(cache_dir='test_cache')
    
    def create_data_points(self, days):
        """Create test data"""
        data = []
        base_date = datetime.now() - timedelta(days=days)
        for i in range(days):
            price = 100 + i * 0.05
            data.append({
                'date': (base_date + timedelta(days=i)).strftime('%Y-%m-%d'),
                'close': price,
                'open': price - 0.5,
                'high': price + 1,
                'low': price - 1,
                'volume': 1000000
            })
        return data
    
    @patch.object(FundAnalyzer, 'fetch_fund_info')
    @patch.object(FundAnalyzer, 'get_benchmark_data')
    def test_generate_prospectus_returns_complete_data(self, mock_benchmark, mock_fund_info):
        """Prospectus should contain all required sections"""
        mock_fund_info.return_value = None
        mock_benchmark.return_value = []
        
        data = self.create_data_points(1500)  # ~4 years
        
        result = self.analyzer.generate_prospectus_data('TEST', data)
        
        self.assertIn('symbol', result)
        self.assertIn('generated_at', result)
        self.assertIn('performance', result)
        self.assertIn('current_price', result)
        
        # Should have performance data
        self.assertIn('1yr', result['performance'])
    
    def test_current_price_from_latest_data(self):
        """Current price should be the most recent close"""
        data = self.create_data_points(400)
        
        with patch.object(self.analyzer, 'fetch_fund_info', return_value=None):
            with patch.object(self.analyzer, 'get_benchmark_data', return_value=[]):
                result = self.analyzer.generate_prospectus_data('TEST', data)
        
        expected_price = data[-1]['close']
        self.assertAlmostEqual(result['current_price'], expected_price, delta=0.1)


class TestHelperMethods(unittest.TestCase):
    """Tests for internal helper methods"""
    
    def setUp(self):
        self.analyzer = FundAnalyzer()
    
    def test_calculate_std_normal_values(self):
        """Standard deviation calculation should be correct"""
        values = [10, 12, 14, 16, 18]  # Mean = 14, std = 3.16
        
        result = self.analyzer._calculate_std(values)
        
        self.assertAlmostEqual(result, 3.16, delta=0.1)
    
    def test_calculate_std_empty_list(self):
        """Should return 0 for empty list"""
        result = self.analyzer._calculate_std([])
        self.assertEqual(result, 0)
    
    def test_calculate_std_single_value(self):
        """Should return 0 for single value"""
        result = self.analyzer._calculate_std([100])
        self.assertEqual(result, 0)
    
    def test_max_drawdown_no_drawdown(self):
        """Max drawdown should be 0 for constantly rising prices"""
        data = [{'close': 100 + i} for i in range(100)]
        
        result = self.analyzer._calculate_max_drawdown(data)
        
        self.assertEqual(result, 0)
    
    def test_max_drawdown_simple_case(self):
        """Max drawdown should capture peak-to-trough decline"""
        # 100 -> 110 -> 90 -> 100 = 18.18% drawdown (90/110 - 1)
        data = [
            {'close': 100}, {'close': 105}, {'close': 110},
            {'close': 100}, {'close': 90}, {'close': 95}, {'close': 100}
        ]
        
        result = self.analyzer._calculate_max_drawdown(data)
        
        # (110 - 90) / 110 * 100 = 18.18%
        self.assertAlmostEqual(result, 18.18, delta=0.5)


if __name__ == '__main__':
    unittest.main()
