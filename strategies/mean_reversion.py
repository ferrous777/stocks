from datetime import datetime
from typing import Dict, List, Optional, Tuple
from .strategy import Strategy, SignalType
import numpy as np
from market_data.data_types import BacktestResult, TradeMetrics, Trade, HistoricalData

class MeanReversionStrategy(Strategy):
    def __init__(self, symbols=None, historical_data=None):
        super().__init__(
            name="Mean Reversion",
            description="Mean reversion strategy using Bollinger Bands and price deviation"
        )
        self.bb_period = 20
        self.bb_std_dev = 2.0
        self.deviation_threshold = 1.5
        self.mean_period = 10
        self.profit_target = 0.08
        self.stop_loss = 0.05
        
        # Add data if provided
        if symbols and historical_data:
            for symbol in symbols:
                if symbol in historical_data:
                    self.add_data(symbol, historical_data[symbol])
    
    def requires_fundamentals(self) -> bool:
        return False
    
    def get_min_required_points(self) -> int:
        return max(self.bb_period, self.mean_period)
    
    def calculate_bollinger_bands(self, prices: List[float], period: int, std_dev: float) -> Tuple[float, float, float]:
        """Calculate Bollinger Bands (upper, middle, lower)"""
        if len(prices) < period:
            avg_price = np.mean(prices) if prices else 0
            return avg_price, avg_price, avg_price
        
        recent_prices = prices[-period:]
        middle = np.mean(recent_prices)
        std = np.std(recent_prices)
        
        upper = middle + (std * std_dev)
        lower = middle - (std * std_dev)
        
        return upper, middle, lower
    
    def calculate_price_deviation(self, prices: List[float], period: int) -> float:
        """Calculate how far current price deviates from mean"""
        if len(prices) < period + 1:
            return 0.0
        
        current_price = prices[-1]
        mean_price = np.mean(prices[-period:])
        
        if mean_price == 0:
            return 0.0
        
        deviation = (current_price - mean_price) / mean_price
        return deviation
    
    def generate_signals(self, data_points: List[HistoricalData], index: int) -> Tuple[SignalType, float, str]:
        """Generate trading signals based on mean reversion analysis"""
        if index < self.get_min_required_points():
            return "hold", 0.0, "Insufficient data"
        
        # Get recent prices
        recent_data = data_points[max(0, index - self.bb_period):index + 1]
        prices = [point.close for point in recent_data]
        
        if len(prices) < self.get_min_required_points():
            return "hold", 0.0, "Insufficient price data"
        
        current_price = prices[-1]
        
        # Calculate indicators
        bb_upper, bb_middle, bb_lower = self.calculate_bollinger_bands(prices, self.bb_period, self.bb_std_dev)
        price_deviation = self.calculate_price_deviation(prices, self.mean_period)
        
        # Generate signals
        if current_price <= bb_lower and price_deviation < -self.deviation_threshold / 100:
            # Price is below lower Bollinger Band and significantly below mean
            confidence = min(0.9, abs(price_deviation) * 10 + (bb_middle - current_price) / bb_middle)
            return "buy", confidence, f"Price below BB lower band (${current_price:.2f} vs ${bb_lower:.2f}), deviation {price_deviation:.3f}"
        
        elif current_price >= bb_upper and price_deviation > self.deviation_threshold / 100:
            # Price is above upper Bollinger Band and significantly above mean
            confidence = min(0.9, abs(price_deviation) * 10 + (current_price - bb_middle) / bb_middle)
            return "sell", confidence, f"Price above BB upper band (${current_price:.2f} vs ${bb_upper:.2f}), deviation {price_deviation:.3f}"
        
        else:
            return "hold", 0.0, f"Price within bands: ${bb_lower:.2f} < ${current_price:.2f} < ${bb_upper:.2f}"
    
    def get_min_required_points(self) -> int:
        return max(self.bb_period, self.mean_period) + 1
    
    def analyze(self, date: Optional[datetime] = None) -> Dict[str, Dict[str, any]]:
        """Analyze current market data for mean reversion signals"""
        results = {}
        
        for symbol in self.symbols:
            historical, _ = self.get_data(symbol)
            data_points = historical.data_points
            
            if len(data_points) < self.get_min_required_points():
                results[symbol] = {
                    'signal': 'hold',
                    'confidence': 0.0,
                    'reason': 'Insufficient data'
                }
                continue
            
            # Generate signal
            signal, confidence, reason = self.generate_signals(data_points, len(data_points) - 1)
            
            results[symbol] = {
                'signal': signal,
                'confidence': confidence,
                'reason': reason,
                'current_price': data_points[-1].close
            }
        
        return results
    
    def _calculate_strategy_metrics(self, trades: List[Dict[str, any]]) -> Dict[str, any]:
        """Calculate mean reversion strategy specific metrics"""
        if not trades:
            return {'mean_reversion_accuracy': 0}
        
        profitable_trades = sum(1 for trade in trades if trade.get('return_pct', 0) > 0)
        return {
            'mean_reversion_accuracy': profitable_trades / len(trades) if trades else 0
        }
    
    def generate_signal(self, symbol: str, date: datetime) -> Dict[str, any]:
        """Generate a trading signal for a specific symbol and date"""
        if symbol not in self.data:
            return {'signal': 'hold', 'confidence': 0.0, 'reason': 'No data available'}
        
        historical, _ = self.get_data(symbol)
        data_points = historical.data_points
        
        if len(data_points) < self.get_min_required_points():
            return {'signal': 'hold', 'confidence': 0.0, 'reason': 'Insufficient data'}
        
        # Find the most recent data point
        signal, confidence, reason = self.generate_signals(data_points, len(data_points) - 1)
        
        return {
            'signal': signal,
            'confidence': confidence,
            'reason': reason,
            'date': date.strftime('%Y-%m-%d')
        }
    
    def analyze(self, date: Optional[datetime] = None) -> Dict[str, Dict[str, any]]:
        """Analyze current market data for mean reversion signals"""
        results = {}
        
        for symbol in self.symbols:
            historical, _ = self.get_data(symbol)
            data_points = historical.data_points
            
            if len(data_points) < self.get_min_required_points():
                results[symbol] = {
                    'signal': 'hold',
                    'confidence': 0.0,
                    'reason': 'Insufficient data',
                    'bb_upper': None,
                    'bb_middle': None,
                    'bb_lower': None,
                    'deviation': None
                }
                continue
            
            # Calculate indicators
            closes = [p.close for p in data_points]
            bb_upper, bb_middle, bb_lower = self.calculate_bollinger_bands(closes, self.bb_period, self.bb_std_dev)
            deviation = self.calculate_price_deviation(closes, self.mean_period)
            
            # Generate signal
            signal, confidence, reason = self.generate_signals(data_points, len(data_points) - 1)
            
            results[symbol] = {
                'signal': signal,
                'confidence': confidence,
                'reason': reason,
                'bb_upper': bb_upper,
                'bb_middle': bb_middle,
                'bb_lower': bb_lower,
                'deviation': deviation,
                'current_price': closes[-1]
            }
        
        return results
    
    def _calculate_strategy_metrics(self, trades: List[Dict[str, any]]) -> Dict[str, any]:
        """Calculate mean reversion strategy specific metrics"""
        if not trades:
            return {
                'avg_deviation_at_entry': 0,
                'bb_signal_accuracy': 0,
                'mean_reversion_success_rate': 0,
                'avg_time_to_reversion': 0
            }
        
        deviation_values = []
        bb_signals = 0
        successful_reversions = 0
        profitable_trades = 0
        
        for trade in trades:
            if 'deviation' in trade:
                deviation_values.append(abs(trade['deviation']))
            
            if 'bb_signal' in trade and trade['bb_signal']:
                bb_signals += 1
                if trade.get('return_pct', 0) > 0:
                    successful_reversions += 1
            
            if trade.get('return_pct', 0) > 0:
                profitable_trades += 1
        
        return {
            'avg_deviation_at_entry': np.mean(deviation_values) if deviation_values else 0,
            'bb_signal_accuracy': successful_reversions / bb_signals if bb_signals > 0 else 0,
            'mean_reversion_success_rate': profitable_trades / len(trades) if trades else 0,
            'avg_time_to_reversion': 0  # Could be calculated from trade duration
        }
