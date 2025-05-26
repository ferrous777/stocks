"""
Momentum-based Time Estimator

Uses current momentum (rate of change, trend strength) to estimate
time to target, adjusting for acceleration/deceleration.
"""

from typing import List, Optional
from .base import TimeEstimator, TimeEstimate


class MomentumTimeEstimator(TimeEstimator):
    """
    Estimates time-to-target using momentum indicators.
    
    Logic: Strong momentum = faster time to target
    Weak/opposing momentum = slower time to target
    """
    
    def __init__(self, roc_period: int = 10, trend_period: int = 20):
        super().__init__(
            name="Momentum Time Estimator",
            description="Uses momentum and trend strength to adjust time estimates"
        )
        self.roc_period = roc_period
        self.trend_period = trend_period
    
    def get_min_data_points(self) -> int:
        return max(self.roc_period, self.trend_period) + 5
    
    def calculate_roc(self, data_points: List[dict], period: int) -> float:
        """Calculate Rate of Change"""
        if len(data_points) <= period:
            return 0
        
        current = data_points[0]['close']
        past = data_points[period]['close']
        
        if past <= 0:
            return 0
        
        return (current - past) / past
    
    def calculate_trend_strength(self, data_points: List[dict]) -> float:
        """
        Calculate trend strength using linear regression slope.
        Returns normalized value: positive = uptrend, negative = downtrend
        """
        if len(data_points) < self.trend_period:
            return 0
        
        # Get closing prices for trend period
        closes = [p['close'] for p in data_points[:self.trend_period]]
        closes.reverse()  # Oldest to newest
        
        n = len(closes)
        x_mean = (n - 1) / 2
        y_mean = sum(closes) / n
        
        # Calculate slope
        numerator = sum((i - x_mean) * (closes[i] - y_mean) for i in range(n))
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        
        if denominator == 0:
            return 0
        
        slope = numerator / denominator
        
        # Normalize by average price
        return slope / y_mean if y_mean > 0 else 0
    
    def calculate_rsi(self, data_points: List[dict], period: int = 14) -> float:
        """Calculate RSI for momentum context"""
        if len(data_points) < period + 1:
            return 50  # Neutral
        
        gains = []
        losses = []
        
        for i in range(1, period + 1):
            change = data_points[i-1]['close'] - data_points[i]['close']
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        
        if avg_loss == 0:
            return 100
        
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))
    
    def estimate(
        self,
        current_price: float,
        target_price: float,
        stop_price: float,
        data_points: List[dict],
        direction: str = "long"
    ) -> Optional[TimeEstimate]:
        
        if not self.validate_inputs(current_price, target_price, stop_price, data_points):
            return None
        
        # Sort by date descending (most recent first)
        sorted_data = sorted(data_points, key=lambda x: x['date'], reverse=True)
        
        # Calculate momentum indicators
        roc = self.calculate_roc(sorted_data, self.roc_period)
        trend_strength = self.calculate_trend_strength(sorted_data)
        rsi = self.calculate_rsi(sorted_data)
        
        # Calculate base daily move rate from recent data
        daily_returns = []
        for i in range(1, min(len(sorted_data), 20)):
            ret = (sorted_data[i-1]['close'] - sorted_data[i]['close']) / sorted_data[i]['close']
            daily_returns.append(ret)
        
        if not daily_returns:
            return None
        
        avg_daily_return = sum(daily_returns) / len(daily_returns)
        
        # Calculate distance to target
        distance_pct = self.calculate_price_distance(current_price, target_price, direction)
        
        # Momentum alignment factor
        # If momentum is aligned with direction, speed up; if opposed, slow down
        if direction == "long":
            momentum_aligned = (roc > 0 and trend_strength > 0)
            momentum_strength = (roc + trend_strength * 10) / 2
        else:
            momentum_aligned = (roc < 0 and trend_strength < 0)
            momentum_strength = (-roc - trend_strength * 10) / 2
        
        # RSI context: overbought/oversold affects timing
        if direction == "long":
            rsi_factor = 1.0 + (50 - rsi) / 100  # Oversold = faster recovery expected
        else:
            rsi_factor = 1.0 + (rsi - 50) / 100  # Overbought = faster drop expected
        
        # Calculate base time
        if abs(avg_daily_return) > 0.0001:
            base_days = abs(distance_pct / avg_daily_return)
        else:
            base_days = abs(distance_pct / 0.005) * 10  # Assume 0.5% daily if no movement
        
        # Apply momentum adjustment
        if momentum_aligned and momentum_strength > 0:
            momentum_factor = 1.0 / (1.0 + momentum_strength)  # Faster
        else:
            momentum_factor = 1.0 + abs(momentum_strength)  # Slower
        
        days_to_target = base_days * momentum_factor * rsi_factor
        
        # Stop loss timing (assume momentum reversal needed)
        days_to_stop = base_days * (1.0 / momentum_factor) if momentum_aligned else base_days * momentum_factor
        
        # Range based on momentum stability
        range_factor = 0.3 if momentum_aligned else 0.5
        range_low = days_to_target * (1 - range_factor)
        range_high = days_to_target * (1 + range_factor * 2)
        
        # Confidence based on momentum alignment and strength
        if momentum_aligned:
            confidence = min(0.8, 0.4 + abs(momentum_strength) * 2)
        else:
            confidence = max(0.2, 0.4 - abs(momentum_strength))
        
        return TimeEstimate(
            estimator_name=self.name,
            days_to_target=max(1, days_to_target),
            days_to_stop=max(1, days_to_stop),
            confidence=round(confidence, 2),
            range_low=max(1, range_low),
            range_high=range_high,
            methodology=f"ROC={roc:.3f}, Trend={trend_strength:.4f}, RSI={rsi:.1f}, Aligned={momentum_aligned}"
        )
