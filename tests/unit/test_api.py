"""
Unit tests for Flask API Endpoints

Tests the web API to ensure:
- Routes return correct data
- Error handling works properly
- API contracts are maintained
"""
import unittest
from unittest.mock import Mock, patch, MagicMock
import json
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from app import app


class TestAPIBase(unittest.TestCase):
    """Base class for API tests"""
    
    def setUp(self):
        """Set up test client"""
        app.config['TESTING'] = True
        self.client = app.test_client()


class TestHealthEndpoint(TestAPIBase):
    """Tests for /health endpoint"""
    
    def test_health_returns_200(self):
        """Health endpoint should return 200 OK"""
        response = self.client.get('/health')
        
        self.assertEqual(response.status_code, 200)
    
    def test_health_returns_json(self):
        """Health endpoint should return JSON"""
        response = self.client.get('/health')
        
        self.assertEqual(response.content_type, 'application/json')
    
    def test_health_contains_status(self):
        """Health response should contain status field"""
        response = self.client.get('/health')
        data = json.loads(response.data)
        
        self.assertIn('status', data)
        self.assertEqual(data['status'], 'healthy')
    
    def test_health_contains_timestamp(self):
        """Health response should contain timestamp"""
        response = self.client.get('/health')
        data = json.loads(response.data)
        
        self.assertIn('timestamp', data)


class TestSymbolsEndpoint(TestAPIBase):
    """Tests for /api/symbols endpoint"""
    
    @patch('app.get_available_symbols')
    def test_symbols_returns_list(self, mock_symbols):
        """Should return a list of symbols"""
        mock_symbols.return_value = ['AAPL', 'MSFT', 'GOOGL']
        
        response = self.client.get('/api/symbols')
        data = json.loads(response.data)
        
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 3)
        self.assertIn('AAPL', data)
    
    @patch('app.get_available_symbols')
    def test_symbols_empty_returns_empty_list(self, mock_symbols):
        """Should return empty list when no symbols"""
        mock_symbols.return_value = []
        
        response = self.client.get('/api/symbols')
        data = json.loads(response.data)
        
        self.assertEqual(data, [])


class TestDatesEndpoint(TestAPIBase):
    """Tests for /api/dates endpoint"""
    
    @patch('app.get_available_dates')
    def test_dates_returns_list(self, mock_dates):
        """Should return a list of dates"""
        mock_dates.return_value = ['20240115', '20240114', '20240113']
        
        response = self.client.get('/api/dates')
        data = json.loads(response.data)
        
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 3)


class TestBacktestEndpoint(TestAPIBase):
    """Tests for /api/backtest/<symbol>/<date> endpoint"""
    
    @patch('app.load_backtest_results')
    def test_backtest_returns_data(self, mock_load):
        """Should return backtest data for valid symbol/date"""
        mock_load.return_value = {
            'symbol': 'AAPL',
            'total_returns': 15.5,
            'win_rate': 0.65
        }
        
        response = self.client.get('/api/backtest/AAPL/20240115')
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['symbol'], 'AAPL')
    
    @patch('app.load_backtest_results')
    def test_backtest_not_found_returns_404(self, mock_load):
        """Should return 404 when backtest not found"""
        mock_load.return_value = None
        
        response = self.client.get('/api/backtest/FAKE/20240115')
        
        self.assertEqual(response.status_code, 404)


class TestRecommendationsEndpoint(TestAPIBase):
    """Tests for /api/recommendations/<symbol>/<date> endpoint"""
    
    @patch('app.load_recommendations')
    def test_recommendations_returns_data(self, mock_load):
        """Should return recommendations for valid symbol/date"""
        mock_load.return_value = {
            'symbol': 'AAPL',
            'recommendations': {
                'action': 'BUY',
                'confidence': 0.8
            }
        }
        
        response = self.client.get('/api/recommendations/AAPL/20240115')
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIn('recommendations', data)
    
    @patch('app.load_recommendations')
    def test_recommendations_not_found_returns_404(self, mock_load):
        """Should return 404 when recommendations not found"""
        mock_load.return_value = None
        
        response = self.client.get('/api/recommendations/FAKE/20240115')
        
        self.assertEqual(response.status_code, 404)


class TestHistoricalEndpoint(TestAPIBase):
    """Tests for /api/historical/<symbol> endpoint"""
    
    @patch('app.load_historical_data')
    def test_historical_returns_data(self, mock_load):
        """Should return historical data for valid symbol"""
        mock_load.return_value = {
            'symbol': 'AAPL',
            'data_points': [
                {'date': '2024-01-15', 'close': 150.0}
            ]
        }
        
        response = self.client.get('/api/historical/AAPL')
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIn('data_points', data)
    
    @patch('app.load_historical_data')
    def test_historical_not_found_returns_404(self, mock_load):
        """Should return 404 when historical data not found"""
        mock_load.return_value = None
        
        response = self.client.get('/api/historical/FAKE')
        
        self.assertEqual(response.status_code, 404)


class TestFundProspectusEndpoint(TestAPIBase):
    """Tests for /api/fund/<symbol>/prospectus endpoint"""
    
    @patch('app.load_historical_data')
    @patch('app.FundAnalyzer')
    def test_prospectus_returns_data(self, mock_analyzer_class, mock_load):
        """Should return prospectus data for valid fund symbol"""
        mock_load.return_value = {
            'symbol': 'QQQ',
            'data_points': [{'date': '2024-01-15', 'close': 400.0}]
        }
        
        mock_analyzer = MagicMock()
        mock_analyzer.generate_prospectus_data.return_value = {
            'symbol': 'QQQ',
            'performance': {'1yr': {'annualized_return': 25.0}}
        }
        mock_analyzer_class.return_value = mock_analyzer
        
        response = self.client.get('/api/fund/QQQ/prospectus')
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIn('symbol', data)
    
    @patch('app.load_historical_data')
    def test_prospectus_no_data_returns_404(self, mock_load):
        """Should return 404 when no historical data"""
        mock_load.return_value = None
        
        response = self.client.get('/api/fund/FAKE/prospectus')
        
        self.assertEqual(response.status_code, 404)


class TestTickerManagement(TestAPIBase):
    """Tests for ticker management endpoints"""
    
    @patch('app.load_config')
    @patch('app.save_config')
    def test_add_ticker_success(self, mock_save, mock_load):
        """Should add ticker successfully"""
        mock_load.return_value = {'symbols': []}
        mock_save.return_value = True
        
        response = self.client.post('/api/add_ticker',
            data=json.dumps({'symbol': 'TSLA', 'sector': 'Technology'}),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertTrue(data['success'])
    
    @patch('app.load_config')
    def test_add_ticker_duplicate_fails(self, mock_load):
        """Should fail when adding duplicate ticker"""
        mock_load.return_value = {'symbols': [{'symbol': 'TSLA'}]}
        
        response = self.client.post('/api/add_ticker',
            data=json.dumps({'symbol': 'TSLA', 'sector': 'Technology'}),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 400)
    
    def test_add_ticker_no_symbol_fails(self):
        """Should fail when symbol is missing"""
        response = self.client.post('/api/add_ticker',
            data=json.dumps({'sector': 'Technology'}),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 400)
    
    @patch('app.load_config')
    @patch('app.save_config')
    def test_remove_ticker_success(self, mock_save, mock_load):
        """Should remove ticker successfully"""
        mock_load.return_value = {'symbols': [{'symbol': 'TSLA'}]}
        mock_save.return_value = True
        
        response = self.client.post('/api/remove_ticker',
            data=json.dumps({'symbol': 'TSLA'}),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertTrue(data['success'])
    
    @patch('app.load_config')
    def test_remove_nonexistent_ticker_fails(self, mock_load):
        """Should fail when removing non-existent ticker"""
        mock_load.return_value = {'symbols': []}
        
        response = self.client.post('/api/remove_ticker',
            data=json.dumps({'symbol': 'FAKE'}),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 404)


class TestErrorHandling(TestAPIBase):
    """Tests for error handling"""
    
    def test_404_returns_error_page(self):
        """Non-existent routes should return 404"""
        response = self.client.get('/nonexistent/route')
        
        self.assertEqual(response.status_code, 404)


if __name__ == '__main__':
    unittest.main()
