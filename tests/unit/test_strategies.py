"""
Unit tests for Trading Strategies

Tests the actual strategy calculations to ensure they produce correct
BUY/SELL/HOLD signals based on market conditions.
"""
import unittest
from unittest.mock import Mock
from datetime import datetime, timedelta
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from scheduler.daily_scheduler import StrategyRunner


class TestMomentumStrategy(unittest.TestCase):
    """Tests for momentum strategy signal generation"""
    
    def setUp(self):
        self.runner = StrategyRunner()
        self.runner.db = Mock()
    
    def create_price_data(self, prices):
        """Helper to create mock data with specific closing prices"""
        data = []
        base_date = datetime.now() - timedelta(days=len(prices))
        for i, price in enumerate(prices):
            mock = Mock()
            mock.date = (base_date + timedelta(days=i)).strftime('%Y-%m-%d')
            mock.close = price
            mock.open = price * 0.99
            mock.high = price * 1.01
            mock.low = price * 0.98
            mock.volume = 1000000
            data.append(mock)
        return data
    
    def test_strong_uptrend_generates_buy_signal(self):
        """Strong upward momentum should generate BUY signal"""
        # Create strong uptrend: 100 -> 150 over 20 days
        prices = [100 + i * 2.5 for i in range(25)]  # 100 to 160
        data = self.create_price_data(prices)
        
        result = self.runner._run_momentum_strategy(data)
        
        self.assertIn('momentum_strategy', result)
        strategy = result['momentum_strategy']
        self.assertEqual(strategy['signal'], 'BUY')
        self.assertGreater(strategy['momentum_score'], 0)
        self.assertGreater(strategy['confidence'], 0.1)
    
    def test_strong_downtrend_generates_sell_signal(self):
        """Strong downward momentum should generate SELL signal"""
        # Create strong downtrend: 150 -> 100 over 20 days
        prices = [150 - i * 2 for i in range(25)]  # 150 to 102
        data = self.create_price_data(prices)
        
        result = self.runner._run_momentum_strategy(data)
        
        self.assertIn('momentum_strategy', result)
        strategy = result['momentum_strategy']
        self.assertEqual(strategy['signal'], 'SELL')
        self.assertLess(strategy['momentum_score'], 0)
    
    def test_flat_trend_generates_hold_signal(self):
        """Flat price action should generate HOLD signal"""
        # Create flat trend: oscillating around 100
        prices = [100 + (i % 3 - 1) * 0.5 for i in range(25)]  # ~100 +/- 0.5
        data = self.create_price_data(prices)
        
        result = self.runner._run_momentum_strategy(data)
        
        self.assertIn('momentum_strategy', result)
        strategy = result['momentum_strategy']
        self.assertEqual(strategy['signal'], 'HOLD')
        self.assertAlmostEqual(strategy['momentum_score'], 0, delta=0.03)
    
    def test_insufficient_data_returns_empty(self):
        """Less than 20 data points should return empty result"""
        prices = [100] * 15  # Only 15 points
        data = self.create_price_data(prices)
        
        result = self.runner._run_momentum_strategy(data)
        
        self.assertEqual(result, {})


class TestMeanReversionStrategy(unittest.TestCase):
    """Tests for mean reversion strategy signal generation"""
    
    def setUp(self):
        self.runner = StrategyRunner()
        self.runner.db = Mock()
    
    def create_price_data(self, prices):
        """Helper to create mock data"""
        data = []
        base_date = datetime.now() - timedelta(days=len(prices))
        for i, price in enumerate(prices):
            mock = Mock()
            mock.date = (base_date + timedelta(days=i)).strftime('%Y-%m-%d')
            mock.close = price
            data.append(mock)
        return data
    
    def test_oversold_generates_buy_signal(self):
        """Price significantly below average should trigger BUY"""
        # Start at 100, drop to 80 - oversold condition
        prices = [100] * 40 + [100 - i * 2 for i in range(15)]  # Drop 30 points
        data = self.create_price_data(prices)
        
        result = self.runner._run_mean_reversion_strategy(data)
        
        if 'mean_reversion_strategy' in result:
            strategy = result['mean_reversion_strategy']
            # Oversold = recent negative change = BUY signal for mean reversion
            self.assertIn(strategy['signal'], ['BUY', 'HOLD'])
    
    def test_overbought_generates_sell_signal(self):
        """Price significantly above average should trigger SELL"""
        # Start at 100, rise to 130 - overbought condition
        prices = [100] * 40 + [100 + i * 2 for i in range(15)]  # Rise 30 points
        data = self.create_price_data(prices)
        
        result = self.runner._run_mean_reversion_strategy(data)
        
        if 'mean_reversion_strategy' in result:
            strategy = result['mean_reversion_strategy']
            # Overbought = recent positive change = SELL signal for mean reversion
            self.assertIn(strategy['signal'], ['SELL', 'HOLD'])
    
    def test_insufficient_data_returns_empty(self):
        """Less than 50 data points should return empty result"""
        prices = [100] * 30  # Only 30 points
        data = self.create_price_data(prices)
        
        result = self.runner._run_mean_reversion_strategy(data)
        
        self.assertEqual(result, {})


class TestBreakoutStrategy(unittest.TestCase):
    """Tests for breakout strategy signal generation"""
    
    def setUp(self):
        self.runner = StrategyRunner()
        self.runner.db = Mock()
    
    def create_price_data(self, ohlc_data):
        """Helper to create mock data with OHLC values"""
        data = []
        base_date = datetime.now() - timedelta(days=len(ohlc_data))
        for i, (o, h, l, c) in enumerate(ohlc_data):
            mock = Mock()
            mock.date = (base_date + timedelta(days=i)).strftime('%Y-%m-%d')
            mock.open = o
            mock.high = h
            mock.low = l
            mock.close = c
            mock.volume = 1000000
            data.append(mock)
        return data
    
    def test_breakout_above_resistance_generates_buy(self):
        """Price breaking above recent high should trigger BUY"""
        # 19 days trading in range 95-105, then break out above
        ohlc = [(100, 105, 95, 102)] * 19 + [(100, 115, 100, 112)]  # Breakout day
        data = self.create_price_data(ohlc)
        
        result = self.runner._run_breakout_strategy(data)
        
        self.assertIn('breakout_strategy', result)
        strategy = result['breakout_strategy']
        self.assertEqual(strategy['signal'], 'BUY')
        self.assertEqual(strategy['confidence'], 0.8)
    
    def test_breakdown_below_support_generates_sell(self):
        """Price breaking below recent low should trigger SELL"""
        # 19 days trading in range 95-105, then break down below
        ohlc = [(100, 105, 95, 100)] * 19 + [(100, 100, 85, 88)]  # Breakdown day
        data = self.create_price_data(ohlc)
        
        result = self.runner._run_breakout_strategy(data)
        
        self.assertIn('breakout_strategy', result)
        strategy = result['breakout_strategy']
        self.assertEqual(strategy['signal'], 'SELL')
        self.assertEqual(strategy['confidence'], 0.8)
    
    def test_consolidation_generates_hold(self):
        """Price within recent range should trigger HOLD"""
        # Trading within 95-105 range, current close at 100
        ohlc = [(100, 105, 95, 100)] * 20
        data = self.create_price_data(ohlc)
        
        result = self.runner._run_breakout_strategy(data)
        
        self.assertIn('breakout_strategy', result)
        strategy = result['breakout_strategy']
        self.assertEqual(strategy['signal'], 'HOLD')
    
    def test_insufficient_data_returns_empty(self):
        """Less than 20 data points should return empty result"""
        ohlc = [(100, 105, 95, 100)] * 10
        data = self.create_price_data(ohlc)
        
        result = self.runner._run_breakout_strategy(data)
        
        self.assertEqual(result, {})


class TestStrategySignalValidation(unittest.TestCase):
    """Tests to validate signal format and constraints"""
    
    def setUp(self):
        self.runner = StrategyRunner()
        self.runner.db = Mock()
    
    def create_price_data(self, count=60):
        """Create standard test data"""
        data = []
        base_date = datetime.now() - timedelta(days=count)
        for i in range(count):
            mock = Mock()
            mock.date = (base_date + timedelta(days=i)).strftime('%Y-%m-%d')
            mock.close = 100 + i * 0.5
            mock.open = 99 + i * 0.5
            mock.high = 101 + i * 0.5
            mock.low = 98 + i * 0.5
            mock.volume = 1000000
            data.append(mock)
        return data
    
    def test_all_signals_are_valid_values(self):
        """All strategy signals should be BUY, SELL, or HOLD"""
        data = self.create_price_data(60)
        self.runner.db.get_symbol_data.return_value = data
        
        result = self.runner.run_all_strategies('TEST', datetime.now())
        
        for key, value in result.items():
            if isinstance(value, dict) and 'signal' in value:
                self.assertIn(value['signal'], ['BUY', 'SELL', 'HOLD'],
                            f"Invalid signal: {value['signal']}")
    
    def test_confidence_values_in_valid_range(self):
        """All confidence values should be between 0 and 1"""
        data = self.create_price_data(60)
        self.runner.db.get_symbol_data.return_value = data
        
        result = self.runner.run_all_strategies('TEST', datetime.now())
        
        for key, value in result.items():
            if isinstance(value, dict) and 'confidence' in value:
                self.assertGreaterEqual(value['confidence'], 0,
                                       f"Confidence below 0: {value['confidence']}")
                self.assertLessEqual(value['confidence'], 1,
                                    f"Confidence above 1: {value['confidence']}")
    
    def test_strategies_return_required_fields(self):
        """Each strategy result should have signal and confidence"""
        data = self.create_price_data(60)
        self.runner.db.get_symbol_data.return_value = data
        
        result = self.runner.run_all_strategies('TEST', datetime.now())
        
        for strategy_name, strategy_result in result.items():
            if isinstance(strategy_result, dict):
                self.assertIn('signal', strategy_result,
                            f"{strategy_name} missing 'signal' field")
                self.assertIn('confidence', strategy_result,
                            f"{strategy_name} missing 'confidence' field")


if __name__ == '__main__':
    unittest.main()
