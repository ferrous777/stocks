"""
Base classes for time estimation plugins.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from datetime import datetime


@dataclass
class TimeEstimate:
    """Result of a time estimation"""
    estimator_name: str
    days_to_target: float          # Expected days to reach take profit
    days_to_stop: float            # Expected days to reach stop loss (if going wrong)
    confidence: float              # 0.0 to 1.0, how confident in this estimate
    range_low: float               # Optimistic estimate (fewer days)
    range_high: float              # Pessimistic estimate (more days)
    methodology: str               # Brief description of how this was calculated
    
    def to_dict(self) -> dict:
        return {
            'estimator_name': self.estimator_name,
            'days_to_target': round(self.days_to_target, 1),
            'days_to_stop': round(self.days_to_stop, 1),
            'confidence': round(self.confidence, 2),
            'range_low': round(self.range_low, 1),
            'range_high': round(self.range_high, 1),
            'methodology': self.methodology
        }


class TimeEstimator(ABC):
    """
    Abstract base class for time-to-target estimators.
    
    Each estimator plugin implements its own methodology for predicting
    how long it will take for a price to reach a target.
    """
    
    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        self.weight = 1.0  # Default weight in ensemble
    
    @abstractmethod
    def estimate(
        self,
        current_price: float,
        target_price: float,
        stop_price: float,
        data_points: List[dict],
        direction: str = "long"  # "long" or "short"
    ) -> Optional[TimeEstimate]:
        """
        Estimate time to reach target price.
        
        Args:
            current_price: Current market price
            target_price: Take profit target
            stop_price: Stop loss level
            data_points: Historical OHLCV data (list of dicts with date, open, high, low, close, volume)
            direction: Trade direction - "long" (expecting price up) or "short" (expecting price down)
            
        Returns:
            TimeEstimate with predicted days and confidence, or None if cannot estimate
        """
        pass
    
    @abstractmethod
    def get_min_data_points(self) -> int:
        """Minimum number of data points required for this estimator"""
        pass
    
    def validate_inputs(
        self,
        current_price: float,
        target_price: float,
        stop_price: float,
        data_points: List[dict]
    ) -> bool:
        """Validate inputs before estimation"""
        if current_price <= 0 or target_price <= 0 or stop_price <= 0:
            return False
        if len(data_points) < self.get_min_data_points():
            return False
        return True
    
    def calculate_price_distance(
        self,
        current_price: float,
        target_price: float,
        direction: str
    ) -> float:
        """Calculate percentage distance to target"""
        if direction == "long":
            return (target_price - current_price) / current_price
        else:
            return (current_price - target_price) / current_price
