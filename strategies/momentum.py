from datetime import datetime
from typing import Dict, List, Optional, Tuple
from .strategy import Strategy, SignalType
import numpy as np
from market_data.data_types import BacktestResult, TradeMetrics, Trade, HistoricalData

class MomentumStrategy(Strategy):
    def __init__(self, symbols=None, historical_data=None):
        super().__init__(
            name="Momentum",
            description="Price momentum strategy using RSI and rate of change"
        )
        self.rsi_period = 14
        self.roc_period = 10
        self.rsi_oversold = 30
        self.rsi_overbought = 70
        self.min_momentum = 0.05
        self.profit_target = 0.12
        self.stop_loss = 0.06
        
        # Add data if provided
        if symbols and historical_data:
            for symbol in symbols:
                if symbol in historical_data:
                    self.add_data(symbol, historical_data[symbol])
    
    def requires_fundamentals(self) -> bool:
        return False
    
    def get_min_required_points(self) -> int:
        return max(self.rsi_period, self.roc_period)
    
    def calculate_rsi(self, prices: List[float], period: int) -> float:
        """Calculate Relative Strength Index"""
        if len(prices) < period + 1:
            return 50.0
        
        gains = []
        losses = []
        
        for i in range(1, len(prices)):
            change = prices[i] - prices[i-1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        
        if len(gains) < period:
            return 50.0
        
        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    def calculate_rate_of_change(self, prices: List[float], period: int) -> float:
        """Calculate Rate of Change"""
        if len(prices) < period + 1:
            return 0.0
        
        current_price = prices[-1]
        past_price = prices[-period-1]
        
        if past_price == 0:
            return 0.0
        
        roc = (current_price - past_price) / past_price
        return roc
    
    def generate_signals(self, data_points: List[HistoricalData], index: int) -> Tuple[SignalType, float, str]:
        """Generate trading signals based on momentum analysis"""
        if index < self.get_min_required_points():
            return "hold", 0.0, "Insufficient data"
        
        # Get recent prices
        recent_data = data_points[max(0, index - self.rsi_period):index + 1]
        prices = [point.close for point in recent_data]
        
        if len(prices) < self.get_min_required_points():
            return "hold", 0.0, "Insufficient price data"
        
        # Calculate momentum indicators
        rsi = self.calculate_rsi(prices, self.rsi_period)
        roc = self.calculate_rate_of_change(prices, self.roc_period)
        
        current_price = prices[-1]
        
        # Generate signals
        if rsi < self.rsi_oversold and roc > self.min_momentum:
            confidence = min(0.9, (self.rsi_oversold - rsi) / 20 + abs(roc) * 2)
            return "buy", confidence, f"Oversold RSI ({rsi:.1f}) with positive momentum ({roc:.3f})"
        
        elif rsi > self.rsi_overbought and roc < -self.min_momentum:
            confidence = min(0.9, (rsi - self.rsi_overbought) / 20 + abs(roc) * 2)
            return "sell", confidence, f"Overbought RSI ({rsi:.1f}) with negative momentum ({roc:.3f})"
        
        else:
            return "hold", 0.0, f"Neutral momentum: RSI {rsi:.1f}, ROC {roc:.3f}"
    
    def get_min_required_points(self) -> int:
        return max(self.rsi_period, self.roc_period) + 1
    
    def analyze(self, date: Optional[datetime] = None) -> Dict[str, Dict[str, any]]:
        """Analyze current market data for momentum signals"""
        results = {}
        
        for symbol in self.symbols:
            historical, _ = self.get_data(symbol)
            data_points = historical.data_points
            
            if len(data_points) < self.get_min_required_points():
                results[symbol] = {
                    'signal': 'hold',
                    'confidence': 0.0,
                    'reason': 'Insufficient data',
                    'rsi': None,
                    'momentum': None
                }
                continue
            
            # Calculate indicators
            closes = [p.close for p in data_points]
            rsi = self.calculate_rsi(closes, self.rsi_period)
            momentum = self.calculate_rate_of_change(closes, self.roc_period)
            
            # Generate signal
            signal, confidence, reason = self.generate_signals(data_points, len(data_points) - 1)
            
            results[symbol] = {
                'signal': signal,
                'confidence': confidence,
                'reason': reason,
                'rsi': rsi,
                'momentum': momentum,
                'current_price': closes[-1]
            }
        
        return results
    
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
    
    def _calculate_strategy_metrics(self, trades: List[Dict[str, any]]) -> Dict[str, any]:
        """Calculate momentum strategy specific metrics"""
        if not trades:
            return {'momentum_accuracy': 0}
        
        profitable_trades = sum(1 for trade in trades if trade.get('return_pct', 0) > 0)
        return {
            'momentum_accuracy': profitable_trades / len(trades) if trades else 0
        }
