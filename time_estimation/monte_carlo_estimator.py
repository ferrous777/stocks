"""
Monte Carlo Time Estimator

Simulates thousands of price paths using historical volatility
to estimate probability distribution of time-to-target.
"""

from typing import List, Optional
from .base import TimeEstimator, TimeEstimate
import random
import math


class MonteCarloTimeEstimator(TimeEstimator):
    """
    Estimates time-to-target using Monte Carlo simulation.
    
    Logic: Generate random price paths based on historical returns
    distribution and measure how long it takes to hit targets.
    """
    
    def __init__(self, num_simulations: int = 1000, max_days: int = 120):
        super().__init__(
            name="Monte Carlo Time Estimator",
            description="Uses simulation to estimate time distribution"
        )
        self.num_simulations = num_simulations
        self.max_days = max_days
    
    def get_min_data_points(self) -> int:
        return 30  # Need enough for return distribution
    
    def _calculate_return_distribution(self, data_points: List[dict]) -> tuple:
        """Calculate mean and std of daily returns"""
        returns = []
        for i in range(1, len(data_points)):
            ret = (data_points[i-1]['close'] - data_points[i]['close']) / data_points[i]['close']
            returns.append(ret)
        
        if len(returns) < 2:
            return 0, 0.01
        
        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / len(returns)
        std = variance ** 0.5
        
        return mean, max(std, 0.001)  # Ensure non-zero std
    
    def _simulate_path(
        self,
        start_price: float,
        target_price: float,
        stop_price: float,
        mean_return: float,
        std_return: float,
        direction: str
    ) -> tuple:
        """
        Simulate a single price path.
        Returns (hit_target, hit_stop, days)
        """
        price = start_price
        
        for day in range(1, self.max_days + 1):
            # Generate random return using normal distribution (Box-Muller)
            u1 = max(1e-10, random.random())
            u2 = random.random()
            z = math.sqrt(-2 * math.log(u1)) * math.cos(2 * math.pi * u2)
            daily_return = mean_return + std_return * z
            
            # Apply return
            price = price * (1 + daily_return)
            
            # Check targets
            if direction == "long":
                if price >= target_price:
                    return (True, False, day)
                if price <= stop_price:
                    return (False, True, day)
            else:  # short
                if price <= target_price:
                    return (True, False, day)
                if price >= stop_price:
                    return (False, True, day)
        
        return (False, False, self.max_days)  # Neither hit
    
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
        
        # Calculate return distribution
        mean_return, std_return = self._calculate_return_distribution(sorted_data)
        
        # Apply drift adjustment for direction
        if direction == "long":
            # Slight positive drift expected for long
            adjusted_mean = max(mean_return, 0.0001)
        else:
            # Slight negative drift expected for short
            adjusted_mean = min(mean_return, -0.0001)
        
        # Run simulations
        target_days = []
        stop_days = []
        neither_count = 0
        
        for _ in range(self.num_simulations):
            hit_target, hit_stop, days = self._simulate_path(
                current_price, target_price, stop_price,
                adjusted_mean, std_return, direction
            )
            
            if hit_target:
                target_days.append(days)
            elif hit_stop:
                stop_days.append(days)
            else:
                neither_count += 1
        
        # Analyze results
        if not target_days:
            # No simulations hit target - low confidence estimate
            return TimeEstimate(
                estimator_name=self.name,
                days_to_target=self.max_days,
                days_to_stop=sum(stop_days) / len(stop_days) if stop_days else self.max_days / 2,
                confidence=0.1,
                range_low=self.max_days * 0.5,
                range_high=self.max_days,
                methodology=f"0/{self.num_simulations} sims hit target, {len(stop_days)} hit stop"
            )
        
        # Calculate statistics
        avg_target_days = sum(target_days) / len(target_days)
        avg_stop_days = sum(stop_days) / len(stop_days) if stop_days else avg_target_days
        
        # Sort for percentiles
        sorted_target = sorted(target_days)
        range_low = sorted_target[int(len(sorted_target) * 0.1)]
        range_high = sorted_target[int(len(sorted_target) * 0.9)]
        
        # Confidence based on success rate and consistency
        success_rate = len(target_days) / self.num_simulations
        
        if len(target_days) > 1:
            variance = sum((d - avg_target_days) ** 2 for d in target_days) / len(target_days)
            std_days = variance ** 0.5
            consistency = 1 - min(1.0, std_days / avg_target_days) if avg_target_days > 0 else 0.5
        else:
            consistency = 0.5
        
        confidence = success_rate * 0.6 + consistency * 0.4
        
        return TimeEstimate(
            estimator_name=self.name,
            days_to_target=avg_target_days,
            days_to_stop=avg_stop_days,
            confidence=round(confidence, 2),
            range_low=max(1, range_low),
            range_high=range_high,
            methodology=f"{len(target_days)}/{self.num_simulations} sims hit target, mean={mean_return:.4f}, std={std_return:.4f}"
        )
