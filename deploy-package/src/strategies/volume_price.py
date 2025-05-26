from datetime import datetime
from typing import Dict, List, Optional, Tuple
from .strategy import Strategy, SignalType
from market_data.data_types import BacktestResult, TradeMetrics, Trade, HistoricalData

class VolumePriceStrategy(Strategy):
    def __init__(self):
        super().__init__(
            name="Volume-Price Analysis",
            description="Analyzes volume and price trends"
        )
        self.volume_threshold = 2.0  # Volume spike threshold
        self.price_threshold = 0.02  # 2% price change threshold
        self.period = 20  # Period for volume average calculation
    
    def requires_fundamentals(self) -> bool:
        return False
    
    def get_min_required_points(self) -> int:
        return self.period
    
    def generate_signals(self, data_points: List[HistoricalData], index: int) -> Tuple[SignalType, float, str]:
        """Generate trading signals based on volume and price analysis"""
        if index < self.period:
            return "hold", 0.0, "Insufficient data"
        
        # Calculate volume and price metrics
        current_point = data_points[index]
        prev_point = data_points[index-1]
        
        # Calculate average volume over period
        recent_volume = [p.volume for p in data_points[index-self.period:index]]
        avg_volume = sum(recent_volume) / len(recent_volume)
        
        # Calculate metrics
        volume_ratio = current_point.volume / avg_volume if avg_volume > 0 else 1.0
        price_change = (current_point.close - prev_point.close) / prev_point.close
        
        # Generate signals
        if volume_ratio > self.volume_threshold:
            if price_change > self.price_threshold:
                confidence = min(volume_ratio / self.volume_threshold, 1.0)
                details = f"High volume up move: {volume_ratio:.1f}x avg volume, {price_change:.1%} price change"
                return "long", confidence, details
            elif price_change < -self.price_threshold:
                confidence = min(volume_ratio / self.volume_threshold, 1.0)
                details = f"High volume down move: {volume_ratio:.1f}x avg volume, {price_change:.1%} price change"
                return "short", confidence, details
        
        # Exit signals on volume decline
        if volume_ratio < 0.5:
            confidence = 0.5
            details = f"Volume declining: {volume_ratio:.1f}x avg volume"
            return "exit", confidence, details
        
        return "hold", 0.0, "No significant volume-price action"
    
    def _calculate_strategy_metrics(self, trades: List[Dict[str, any]]) -> Dict[str, any]:
        """Calculate strategy-specific metrics for backtest summary"""
        if not trades:
            return {}
        
        # Calculate average volume ratios and returns
        volume_ratios = [t['metrics']['volume_ratio'] for t in trades if 'volume_ratio' in t['metrics']]
        daily_returns = [t['metrics']['daily_return'] for t in trades if 'daily_return' in t['metrics']]
        
        if not volume_ratios or not daily_returns:
            return {}
        
        # Signal distribution
        total_signals = len(trades)
        long_ratio = sum(1 for t in trades if t['signal'] == 'long') / total_signals
        short_ratio = sum(1 for t in trades if t['signal'] == 'short') / total_signals
        exit_ratio = sum(1 for t in trades if t['signal'] == 'exit') / total_signals
        
        return {
            "avg_volume_ratio": sum(volume_ratios) / len(volume_ratios),
            "max_volume_ratio": max(volume_ratios),
            "avg_daily_return": sum(daily_returns) / len(daily_returns),
            "long_signal_ratio": long_ratio,
            "short_signal_ratio": short_ratio,
            "exit_signal_ratio": exit_ratio
        }
    
    def analyze(self, date: Optional[datetime] = None) -> Dict[str, Dict[str, any]]:
        """Analyze current market data"""
        results = {}
        
        for symbol in self.symbols:
            historical, _ = self.get_data(symbol)
            
            if len(historical.data_points) < self.period:
                results[symbol] = {
                    "signal": "hold",
                    "confidence": 0,
                    "metrics": {},
                    "details": "Insufficient data for volume analysis"
                }
                continue
            
            # Get current and previous data points
            current_point = historical.data_points[-1]
            prev_point = historical.data_points[-2]
            
            # Calculate average volume over period
            recent_volume = [p.volume for p in historical.data_points[-self.period:-1]]
            avg_volume = sum(recent_volume) / len(recent_volume)
            
            # Calculate metrics
            volume_ratio = current_point.volume / avg_volume if avg_volume > 0 else 1.0
            price_change = (current_point.close - prev_point.close) / prev_point.close
            
            # Generate signal
            signal: SignalType = "hold"
            confidence = 0.0
            details = []
            
            if volume_ratio > self.volume_threshold:
                if price_change > self.price_threshold:
                    signal = "long"
                    confidence = min(volume_ratio / self.volume_threshold, 1.0)
                    details.append(f"High volume up move: {volume_ratio:.1f}x avg volume")
                    details.append(f"Price change: {price_change:.1%}")
                elif price_change < -self.price_threshold:
                    signal = "short"
                    confidence = min(volume_ratio / self.volume_threshold, 1.0)
                    details.append(f"High volume down move: {volume_ratio:.1f}x avg volume")
                    details.append(f"Price change: {price_change:.1%}")
            
            # Exit signals on volume decline
            if volume_ratio < 0.5:
                signal = "exit"
                confidence = 0.5
                details.append(f"Volume declining: {volume_ratio:.1f}x avg volume")
            
            results[symbol] = {
                "signal": signal,
                "confidence": confidence,
                "metrics": {
                    "volume_ratio": volume_ratio,
                    "daily_return": price_change,
                    "close": current_point.close
                },
                "details": " with ".join(details) if details else "No significant volume-price action"
            }
        
        return results 