"""
Pattern-based Time Estimator

Looks at historical patterns with similar characteristics
and measures how long they took to reach similar targets.
"""

from typing import List, Optional, Tuple
from .base import TimeEstimator, TimeEstimate
import math


class PatternTimeEstimator(TimeEstimator):
    """
    Estimates time-to-target by finding similar historical patterns.
    
    Logic: Find past instances where price moved a similar % with
    similar volatility conditions, and see how long those moves took.
    """
    
    def __init__(self, lookback_days: int = 252, similarity_threshold: float = 0.7):
        super().__init__(
            name="Pattern Time Estimator",
            description="Uses historical pattern matching to estimate timing"
        )
        self.lookback_days = lookback_days
        self.similarity_threshold = similarity_threshold
        self.min_similar_patterns = 3
    
    def get_min_data_points(self) -> int:
        return 60  # At least 60 days for pattern matching
    
    def _calculate_volatility(self, data_points: List[dict], period: int = 14) -> float:
        """Calculate recent volatility as std of returns"""
        if len(data_points) < period:
            return 0
        
        returns = []
        for i in range(1, period):
            ret = (data_points[i-1]['close'] - data_points[i]['close']) / data_points[i]['close']
            returns.append(ret)
        
        if len(returns) < 2:
            return 0
        
        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / len(returns)
        return variance ** 0.5
    
    def _find_similar_moves(
        self,
        data_points: List[dict],
        target_move_pct: float,
        current_volatility: float,
        direction: str
    ) -> List[Tuple[float, int]]:
        """
        Find historical moves similar to target.
        Returns list of (actual_move_pct, days_taken)
        """
        similar_moves = []
        
        # Need at least some data to scan
        if len(data_points) < 30:
            return similar_moves
        
        # Sort oldest to newest for scanning
        sorted_data = sorted(data_points, key=lambda x: x['date'])
        
        # Scan through data looking for similar setups
        for start_idx in range(len(sorted_data) - 5):
            start_price = sorted_data[start_idx]['close']
            
            # Calculate volatility at this point
            if start_idx >= 14:
                local_returns = []
                for j in range(start_idx - 14, start_idx):
                    ret = (sorted_data[j+1]['close'] - sorted_data[j]['close']) / sorted_data[j]['close']
                    local_returns.append(ret)
                local_vol = (sum(r**2 for r in local_returns) / len(local_returns)) ** 0.5 if local_returns else 0
            else:
                local_vol = current_volatility  # Use current if not enough history
            
            # Check volatility similarity (within 50%)
            if current_volatility > 0:
                vol_ratio = local_vol / current_volatility
                if vol_ratio < 0.5 or vol_ratio > 2.0:
                    continue
            
            # Look for the move
            for end_idx in range(start_idx + 1, min(start_idx + 60, len(sorted_data))):
                end_price = sorted_data[end_idx]['close']
                move_pct = (end_price - start_price) / start_price
                
                # Check if direction matches
                if direction == "long" and move_pct <= 0:
                    continue
                if direction == "short" and move_pct >= 0:
                    continue
                
                # Check if move magnitude is similar (within 30%)
                actual_move = abs(move_pct)
                target_move = abs(target_move_pct)
                
                if target_move > 0:
                    move_ratio = actual_move / target_move
                    if 0.7 <= move_ratio <= 1.5:
                        days_taken = end_idx - start_idx
                        similar_moves.append((actual_move, days_taken))
                        break  # Found a matching move from this start point
        
        return similar_moves
    
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
        
        # Calculate current conditions
        current_volatility = self._calculate_volatility(sorted_data)
        target_move_pct = self.calculate_price_distance(current_price, target_price, direction)
        stop_move_pct = self.calculate_price_distance(current_price, stop_price, 
                                                       "short" if direction == "long" else "long")
        
        # Find similar historical moves
        similar_moves = self._find_similar_moves(
            sorted_data[:self.lookback_days],
            target_move_pct,
            current_volatility,
            direction
        )
        
        if len(similar_moves) < self.min_similar_patterns:
            # Not enough patterns found
            return None
        
        # Calculate statistics from similar moves
        days_list = [d for _, d in similar_moves]
        avg_days = sum(days_list) / len(days_list)
        
        # Calculate std deviation
        if len(days_list) > 1:
            variance = sum((d - avg_days) ** 2 for d in days_list) / len(days_list)
            std_days = variance ** 0.5
        else:
            std_days = avg_days * 0.3
        
        # Percentile-based range
        sorted_days = sorted(days_list)
        range_low = sorted_days[int(len(sorted_days) * 0.25)]
        range_high = sorted_days[int(len(sorted_days) * 0.75)]
        
        # Estimate stop timing (typically faster as stops are closer)
        stop_ratio = abs(stop_move_pct / target_move_pct) if target_move_pct != 0 else 0.5
        days_to_stop = avg_days * stop_ratio
        
        # Confidence based on number of patterns and consistency
        pattern_confidence = min(1.0, len(similar_moves) / 10)
        consistency = 1 - min(1.0, std_days / avg_days) if avg_days > 0 else 0.5
        confidence = pattern_confidence * 0.5 + consistency * 0.5
        
        return TimeEstimate(
            estimator_name=self.name,
            days_to_target=avg_days,
            days_to_stop=max(1, days_to_stop),
            confidence=round(confidence, 2),
            range_low=max(1, range_low),
            range_high=range_high,
            methodology=f"Found {len(similar_moves)} similar patterns, avg={avg_days:.1f} days, std={std_days:.1f}"
        )
