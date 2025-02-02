from datetime import datetime
from typing import Dict, List, Optional
from .strategy import Strategy, SignalType

class VolumePriceStrategy(Strategy):
    def __init__(self):
        super().__init__(
            name="Volume-Price Analysis",
            description="Analyzes volume and price trends"
        )
        self.volume_threshold = 2.0  # Volume spike threshold
        self.price_change_threshold = 0.02  # 2% price change threshold
    
    def requires_fundamentals(self) -> bool:
        return False
    
    def analyze(self, date: Optional[datetime] = None) -> Dict[str, Dict[str, any]]:
        results = {}
        
        for symbol in self.symbols:
            historical, _ = self.get_data(symbol)
            
            if len(historical.data_points) < 20:
                results[symbol] = {
                    "signal": "hold",
                    "confidence": 0,
                    "metrics": {},
                    "details": "Insufficient data"
                }
                continue
            
            # Calculate volume and price metrics
            volumes = [point.volume for point in historical.data_points[-20:]]
            closes = [point.close for point in historical.data_points[-20:]]
            
            avg_volume = sum(volumes[:-1]) / len(volumes[:-1])
            current_volume = volumes[-1]
            volume_ratio = current_volume / avg_volume
            
            prev_close = closes[-2]
            current_close = closes[-1]
            price_change = (current_close - prev_close) / prev_close
            
            # Determine signal
            signal: SignalType = "hold"
            confidence = 0.0
            details = []
            
            # Volume spike with price movement
            if volume_ratio > self.volume_threshold:
                if price_change > self.price_change_threshold:
                    signal = "long"
                    confidence = min(volume_ratio / self.volume_threshold, 1.0)
                    details.append(f"High volume up move: {volume_ratio:.1f}x avg volume")
                elif price_change < -self.price_change_threshold:
                    signal = "short"
                    confidence = min(volume_ratio / self.volume_threshold, 1.0)
                    details.append(f"High volume down move: {volume_ratio:.1f}x avg volume")
            
            # Exit signals on volume decline
            if signal != "hold" and volume_ratio < 0.5:
                signal = "exit"
                confidence = 0.5
                details.append("Volume returning to normal levels")
            
            results[symbol] = {
                "signal": signal,
                "confidence": confidence,
                "metrics": {
                    "volume_ratio": volume_ratio,
                    "daily_return": price_change,
                    "close": current_close
                },
                "details": " with ".join(details) if details else "No significant volume-price action"
            }
        
        return results
    
    def backtest(self, start_date: datetime, end_date: datetime) -> Dict[str, List[Dict[str, any]]]:
        results = {}
        
        for symbol in self.symbols:
            historical, _ = self.get_data(symbol)
            trades = []
            
            # Filter data points within date range
            data_points = [
                point for point in historical.data_points
                if start_date <= datetime.strptime(point.date, '%Y-%m-%d') <= end_date
            ]
            
            if len(data_points) < 20:
                results[symbol] = trades
                continue
            
            # Calculate signals for each day
            for i in range(20, len(data_points)):
                volumes = [p.volume for p in data_points[i-20:i+1]]
                closes = [p.close for p in data_points[i-20:i+1]]
                
                avg_volume = sum(volumes[:-1]) / len(volumes[:-1])
                current_volume = volumes[-1]
                volume_ratio = current_volume / avg_volume
                
                prev_close = closes[-2]
                current_close = closes[-1]
                price_change = (current_close - prev_close) / prev_close
                
                signal: SignalType = "hold"
                confidence = 0.0
                details = []
                
                # Volume spike with price movement
                if volume_ratio > self.volume_threshold:
                    if price_change > self.price_change_threshold:
                        signal = "long"
                        confidence = min(volume_ratio / self.volume_threshold, 1.0)
                        details.append(f"High volume up move: {volume_ratio:.1f}x avg volume")
                    elif price_change < -self.price_change_threshold:
                        signal = "short"
                        confidence = min(volume_ratio / self.volume_threshold, 1.0)
                        details.append(f"High volume down move: {volume_ratio:.1f}x avg volume")
                
                # Exit signals
                if signal != "hold" and volume_ratio < 0.5:
                    signal = "exit"
                    confidence = 0.5
                    details.append("Volume returning to normal levels")
                
                if signal != "hold":
                    trades.append({
                        "date": datetime.strptime(data_points[i].date, '%Y-%m-%d'),
                        "signal": signal,
                        "confidence": confidence,
                        "metrics": {
                            "volume_ratio": volume_ratio,
                            "daily_return": price_change,
                            "close": current_close
                        },
                        "details": " with ".join(details)
                    })
            
            results[symbol] = trades
        
        return results
    
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