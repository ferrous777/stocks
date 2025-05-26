"""
ATR-based Time Estimator

Uses Average True Range to estimate how long it will take
for price to move to target based on recent volatility.
"""

from typing import List, Optional
from .base import TimeEstimator, TimeEstimate


class ATRTimeEstimator(TimeEstimator):
    """
    Estimates time-to-target using Average True Range (ATR).
    
    Logic: If ATR represents average daily price movement,
    then days_to_target ≈ price_distance / daily_movement_rate
    """
    
    def __init__(self, atr_period: int = 14):
        super().__init__(
            name="ATR Time Estimator",
            description="Uses volatility (ATR) to estimate days to target"
        )
        self.atr_period = atr_period
    
    def get_min_data_points(self) -> int:
        return self.atr_period + 5
    
    def calculate_atr(self, data_points: List[dict]) -> float:
        """Calculate Average True Range"""
        if len(data_points) < 2:
            return 0
        
        true_ranges = []
        for i in range(1, min(len(data_points), self.atr_period + 1)):
            high = data_points[i]['high']
            low = data_points[i]['low']
            prev_close = data_points[i-1]['close']
            
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            true_ranges.append(tr)
        
        return sum(true_ranges) / len(true_ranges) if true_ranges else 0
    
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
        
        # Calculate ATR
        atr = self.calculate_atr(sorted_data)
        if atr <= 0:
            return None
        
        # Calculate distances
        if direction == "long":
            distance_to_target = target_price - current_price
            distance_to_stop = current_price - stop_price
        else:
            distance_to_target = current_price - target_price
            distance_to_stop = stop_price - current_price
        
        # ATR represents average movement, but not all movement is directional
        # Use a directional factor (empirically, about 30-50% of movement is trend-aligned)
        directional_factor = 0.4
        effective_daily_move = atr * directional_factor
        
        if effective_daily_move <= 0:
            return None
        
        # Calculate days
        days_to_target = abs(distance_to_target) / effective_daily_move
        days_to_stop = abs(distance_to_stop) / effective_daily_move
        
        # Calculate range based on ATR variability
        atr_std = self._calculate_atr_std(sorted_data)
        volatility_factor = atr_std / atr if atr > 0 else 0.3
        
        range_low = days_to_target * (1 - volatility_factor)
        range_high = days_to_target * (1 + volatility_factor * 2)
        
        # Confidence based on data quality and volatility stability
        confidence = self._calculate_confidence(sorted_data, atr, atr_std)
        
        return TimeEstimate(
            estimator_name=self.name,
            days_to_target=days_to_target,
            days_to_stop=days_to_stop,
            confidence=confidence,
            range_low=max(1, range_low),
            range_high=range_high,
            methodology=f"ATR({self.atr_period})={atr:.2f}, directional factor={directional_factor}"
        )
    
    def _calculate_atr_std(self, data_points: List[dict]) -> float:
        """Calculate standard deviation of true ranges"""
        if len(data_points) < 3:
            return 0
        
        true_ranges = []
        for i in range(1, min(len(data_points), self.atr_period + 1)):
            high = data_points[i]['high']
            low = data_points[i]['low']
            prev_close = data_points[i-1]['close']
            
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            true_ranges.append(tr)
        
        if len(true_ranges) < 2:
            return 0
        
        mean = sum(true_ranges) / len(true_ranges)
        variance = sum((x - mean) ** 2 for x in true_ranges) / len(true_ranges)
        return variance ** 0.5
    
    def _calculate_confidence(self, data_points: List[dict], atr: float, atr_std: float) -> float:
        """Calculate confidence based on data quality"""
        # Base confidence from data quantity
        data_confidence = min(1.0, len(data_points) / 50)
        
        # Volatility stability (lower std relative to atr = more stable = higher confidence)
        if atr > 0:
            stability = 1 - min(1.0, atr_std / atr)
        else:
            stability = 0.5
        
        return round(data_confidence * 0.4 + stability * 0.6, 2)
