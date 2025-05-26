from datetime import datetime
from typing import Dict, List, Optional, Tuple
from .strategy import Strategy, SignalType
import numpy as np
from market_data.data_types import BacktestResult, TradeMetrics, Trade, HistoricalData

class BollingerBandsStrategy(Strategy):
    def __init__(self):
        super().__init__(
            name="Bollinger Bands",
            description="Uses price volatility bands for trading signals"
        )
        self.period = 20  # Period for moving average
        self.std_dev = 2  # Number of standard deviations for bands
        self.oversold_threshold = 0.05  # How close to lower band to consider oversold
        self.overbought_threshold = 0.05  # How close to upper band to consider overbought
    
    def requires_fundamentals(self) -> bool:
        return False
    
    def get_min_required_points(self) -> int:
        return self.period
    
    def generate_signals(self, data_points: List[HistoricalData], index: int) -> Tuple[SignalType, float, str]:
        """Generate trading signals based on Bollinger Bands"""
        if index < self.period:
            return "hold", 0.0, "Insufficient data"
        
        # Get recent closing prices
        closes = np.array([p.close for p in data_points[max(0, index-self.period):index+1]])
        
        # Calculate Bollinger Bands
        middle_band = np.mean(closes)
        std = np.std(closes)
        upper_band = middle_band + (self.std_dev * std)
        lower_band = middle_band - (self.std_dev * std)
        
        current_price = closes[-1]
        
        # Calculate price position relative to bands
        band_width = upper_band - lower_band
        upper_distance = (upper_band - current_price) / band_width
        lower_distance = (current_price - lower_band) / band_width
        
        # Generate signals
        if lower_distance < self.oversold_threshold:
            # Price near lower band - potential buy signal
            confidence = min((self.oversold_threshold - lower_distance) / self.oversold_threshold, 1.0)
            details = (f"Price ({current_price:.2f}) near lower band ({lower_band:.2f}), "
                      f"band width: {band_width:.2f}")
            return "long", confidence, details
            
        elif upper_distance < self.overbought_threshold:
            # Price near upper band - potential sell signal
            confidence = min((self.overbought_threshold - upper_distance) / self.overbought_threshold, 1.0)
            details = (f"Price ({current_price:.2f}) near upper band ({upper_band:.2f}), "
                      f"band width: {band_width:.2f}")
            return "short", confidence, details
        
        # Generate exit signals
        if 0.4 < lower_distance < 0.6 and 0.4 < upper_distance < 0.6:
            # Price returning to middle band
            confidence = 0.5
            details = f"Price ({current_price:.2f}) returning to middle band ({middle_band:.2f})"
            return "exit", confidence, details
        
        return "hold", 0.0, "Price within normal range"
    
    def analyze(self, date: Optional[datetime] = None) -> Dict[str, Dict[str, any]]:
        """Analyze current market data"""
        results = {}
        
        for symbol in self.symbols:
            historical, _ = self.get_data(symbol)
            
            if len(historical.data_points) < self.period:
                results[symbol] = {
                    "signal": "hold",
                    "confidence": 0.0,
                    "metrics": {},
                    "details": "Insufficient data for Bollinger Bands calculation"
                }
                continue
            
            # Calculate Bollinger Bands
            closes = np.array([p.close for p in historical.data_points[-self.period:]])
            middle_band = np.mean(closes)
            std = np.std(closes)
            upper_band = middle_band + (self.std_dev * std)
            lower_band = middle_band - (self.std_dev * std)
            
            current_price = closes[-1]
            band_width = upper_band - lower_band
            
            # Calculate relative position
            price_position = (current_price - lower_band) / band_width
            
            # Generate signal
            signal: SignalType = "hold"
            confidence = 0.0
            details = []
            
            if price_position < self.oversold_threshold:
                signal = "long"
                confidence = min((self.oversold_threshold - price_position) / self.oversold_threshold, 1.0)
                details.append(f"Oversold: price near lower band")
            elif price_position > (1 - self.overbought_threshold):
                signal = "short"
                confidence = min((price_position - (1 - self.overbought_threshold)) / self.overbought_threshold, 1.0)
                details.append(f"Overbought: price near upper band")
            elif 0.4 < price_position < 0.6:
                signal = "exit"
                confidence = 0.5
                details.append(f"Price returning to middle band")
            
            results[symbol] = {
                "signal": signal,
                "confidence": confidence,
                "metrics": {
                    "middle_band": middle_band,
                    "upper_band": upper_band,
                    "lower_band": lower_band,
                    "band_width": band_width,
                    "price_position": price_position,
                    "volatility": std / middle_band
                },
                "details": " and ".join(details) if details else "Price within normal range"
            }
        
        return results
    
    def _calculate_strategy_metrics(self, trades: List[Dict[str, any]]) -> Dict[str, any]:
        """Calculate strategy-specific metrics for backtest summary"""
        if not trades:
            return {}
        
        # Calculate signal distribution
        total_signals = len(trades)
        long_ratio = sum(1 for t in trades if t['signal'] == 'long') / total_signals
        short_ratio = sum(1 for t in trades if t['signal'] == 'short') / total_signals
        exit_ratio = sum(1 for t in trades if t['signal'] == 'exit') / total_signals
        
        # Calculate average volatility
        volatilities = [t['metrics']['volatility'] for t in trades if 'volatility' in t['metrics']]
        avg_volatility = sum(volatilities) / len(volatilities) if volatilities else 0
        
        return {
            "long_signal_ratio": long_ratio,
            "short_signal_ratio": short_ratio,
            "exit_signal_ratio": exit_ratio,
            "avg_volatility": avg_volatility
        } 