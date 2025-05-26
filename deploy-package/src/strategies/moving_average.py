from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from .strategy import Strategy, SignalType
from market_data.data_types import BacktestResult, TradeMetrics, Trade, HistoricalData

class MovingAverageStrategy(Strategy):
    def __init__(self):
        super().__init__(
            name="Moving Average Crossover",
            description="Analyzes SMA 50 and 200 crossovers"
        )
        self.short_period = 50
        self.long_period = 200
    
    def requires_fundamentals(self) -> bool:
        return False
    
    def get_min_required_points(self) -> int:
        return self.long_period
    
    def generate_signals(self, data_points: List[HistoricalData], index: int) -> Tuple[SignalType, float, str]:
        """Generate trading signals based on moving average crossovers"""
        if index < self.long_period:
            return "hold", 0.0, "Insufficient data"
        
        # Calculate moving averages
        closes = [p.close for p in data_points[max(0, index-self.long_period):index+1]]
        short_ma = sum(closes[-self.short_period:]) / self.short_period
        long_ma = sum(closes[-self.long_period:]) / self.long_period
        
        # Get previous day's values for crossover detection
        prev_closes = [p.close for p in data_points[max(0, index-self.long_period-1):index]]
        prev_short_ma = sum(prev_closes[-self.short_period:]) / self.short_period
        prev_long_ma = sum(prev_closes[-self.long_period:]) / self.long_period
        
        # Calculate spread and previous spread
        spread = (short_ma - long_ma) / long_ma
        prev_spread = (prev_short_ma - prev_long_ma) / prev_long_ma
        
        # Generate signals
        if spread > 0 and prev_spread <= 0:
            confidence = min(abs(spread) * 100, 1.0)
            details = f"Golden Cross: SMA 50 ({short_ma:.2f}) crossed above SMA 200 ({long_ma:.2f})"
            return "long", confidence, details
        elif spread < 0 and prev_spread >= 0:
            confidence = min(abs(spread) * 100, 1.0)
            details = f"Death Cross: SMA 50 ({short_ma:.2f}) crossed below SMA 200 ({long_ma:.2f})"
            return "short", confidence, details
        elif spread > 0:
            confidence = min(abs(spread) * 50, 1.0)
            details = f"Bullish trend: SMA 50 ({short_ma:.2f}) above SMA 200 ({long_ma:.2f})"
            return "long", confidence, details
        elif spread < 0:
            confidence = min(abs(spread) * 50, 1.0)
            details = f"Bearish trend: SMA 50 ({short_ma:.2f}) below SMA 200 ({long_ma:.2f})"
            return "short", confidence, details
        
        # Generate exit signals
        if (prev_spread > spread > 0) or (prev_spread < spread < 0):
            confidence = min(abs(spread) * 25, 1.0)
            details = f"Trend weakening: spread changed from {prev_spread:.2%} to {spread:.2%}"
            return "exit", confidence, details
        
        return "hold", 0.0, "No significant signals"
    
    def analyze(self, date: Optional[datetime] = None) -> Dict[str, Dict[str, any]]:
        results = {}
        
        for symbol in self.symbols:
            historical, _ = self.get_data(symbol)
            
            # Calculate SMAs
            closes = [point.close for point in historical.data_points]
            sma_50 = sum(closes[-50:]) / min(50, len(closes))
            sma_200 = sum(closes[-200:]) / min(200, len(closes))
            
            # Determine signal
            signal: SignalType = "hold"
            confidence = 0.0
            details = ""
            
            if len(closes) >= 50:  # Minimum data requirement
                spread = (sma_50 - sma_200) / sma_200
                
                # Previous day's values for crossover detection
                prev_closes = closes[:-1]
                prev_sma_50 = sum(prev_closes[-50:]) / min(50, len(prev_closes))
                prev_sma_200 = sum(prev_closes[-200:]) / min(200, len(prev_closes))
                prev_spread = (prev_sma_50 - prev_sma_200) / prev_sma_200
                
                # Detect crossovers
                if spread > 0 and prev_spread <= 0:
                    signal = "long"
                    confidence = min(abs(spread) * 100, 1.0)
                    details = f"Golden Cross: SMA 50 ({sma_50:.2f}) crossed above SMA 200 ({sma_200:.2f})"
                elif spread < 0 and prev_spread >= 0:
                    signal = "short"
                    confidence = min(abs(spread) * 100, 1.0)
                    details = f"Death Cross: SMA 50 ({sma_50:.2f}) crossed below SMA 200 ({sma_200:.2f})"
                elif spread > 0:
                    signal = "long"
                    confidence = min(abs(spread) * 50, 1.0)
                    details = f"Bullish trend: SMA 50 ({sma_50:.2f}) above SMA 200 ({sma_200:.2f})"
                elif spread < 0:
                    signal = "short"
                    confidence = min(abs(spread) * 50, 1.0)
                    details = f"Bearish trend: SMA 50 ({sma_50:.2f}) below SMA 200 ({sma_200:.2f})"
                
                # Generate exit signals
                if (signal == "long" and prev_spread > spread > 0) or \
                   (signal == "short" and prev_spread < spread < 0):
                    signal = "exit"
                    confidence = min(abs(spread) * 25, 1.0)
                    details = f"Trend weakening: spread changed from {prev_spread:.2%} to {spread:.2%}"
            
            results[symbol] = {
                "signal": signal,
                "confidence": confidence,
                "metrics": {
                    "sma_50": sma_50,
                    "sma_200": sma_200,
                    "close": closes[-1]
                },
                "details": details
            }
        
        return results
    
    def _calculate_strategy_metrics(self, trades: List[Dict[str, any]]) -> Dict[str, any]:
        """Calculate strategy-specific metrics for backtest summary"""
        if not trades:
            return {}
            
        # Calculate average SMA values and spreads
        sma_50_values = [t['metrics']['sma_50'] for t in trades if 'sma_50' in t['metrics']]
        sma_200_values = [t['metrics']['sma_200'] for t in trades if 'sma_200' in t['metrics']]
        
        if not sma_50_values or not sma_200_values:
            return {}
            
        avg_sma_50 = sum(sma_50_values) / len(sma_50_values)
        avg_sma_200 = sum(sma_200_values) / len(sma_200_values)
        avg_spread = sum((s50 - s200) for s50, s200 in zip(sma_50_values, sma_200_values)) / len(sma_50_values)
        
        # Calculate signal distribution
        total_signals = len(trades)
        long_ratio = sum(1 for t in trades if t['signal'] == 'long') / total_signals
        short_ratio = sum(1 for t in trades if t['signal'] == 'short') / total_signals
        exit_ratio = sum(1 for t in trades if t['signal'] == 'exit') / total_signals
        
        return {
            "avg_sma_50": avg_sma_50,
            "avg_sma_200": avg_sma_200,
            "avg_spread": avg_spread,
            "long_signal_ratio": long_ratio,
            "short_signal_ratio": short_ratio,
            "exit_signal_ratio": exit_ratio
        }
    
    def _calculate_ma(self, prices: List[float], period: int) -> List[float]:
        """Calculate Simple Moving Average"""
        ma = []
        for i in range(len(prices)):
            if i < period:
                ma.append(sum(prices[:i+1]) / (i+1))
            else:
                ma.append(sum(prices[i-period+1:i+1]) / period)
        return ma 