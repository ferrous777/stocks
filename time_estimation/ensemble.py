"""
Ensemble Time Estimator

Combines multiple time estimators using weighted averaging
based on confidence and historical accuracy.
"""

from typing import List, Optional, Dict
from .base import TimeEstimator, TimeEstimate
from dataclasses import dataclass


@dataclass
class EnsembleTimeEstimate:
    """Combined estimate from ensemble"""
    days_to_target: float
    days_to_stop: float
    confidence: float
    range_low: float
    range_high: float
    time_horizon: str  # "SHORT", "MEDIUM", "LONG"
    individual_estimates: List[TimeEstimate]
    weights_used: Dict[str, float]
    
    def to_dict(self) -> dict:
        return {
            'days_to_target': round(self.days_to_target, 1),
            'days_to_stop': round(self.days_to_stop, 1),
            'confidence': round(self.confidence, 2),
            'range_low': round(self.range_low, 1),
            'range_high': round(self.range_high, 1),
            'time_horizon': self.time_horizon,
            'estimate_range': f"{round(self.range_low)}-{round(self.range_high)} days",
            'individual_estimates': [e.to_dict() for e in self.individual_estimates],
            'weights_used': {k: round(v, 3) for k, v in self.weights_used.items()}
        }


class EnsembleTimeEstimator:
    """
    Combines multiple time estimators into a weighted ensemble.
    
    Features:
    - Weighted averaging based on confidence scores
    - Automatic weight adjustment based on estimator agreement
    - Robust handling of missing estimates
    """
    
    def __init__(self, estimators: List[TimeEstimator] = None):
        self.estimators = estimators or []
        self.estimator_weights: Dict[str, float] = {}
        self.min_estimators = 2  # Minimum estimators needed for valid ensemble
        
        # Initialize equal weights
        for est in self.estimators:
            self.estimator_weights[est.name] = est.weight
    
    def add_estimator(self, estimator: TimeEstimator):
        """Add an estimator to the ensemble (plugin pattern)"""
        self.estimators.append(estimator)
        self.estimator_weights[estimator.name] = estimator.weight
    
    def remove_estimator(self, name: str):
        """Remove an estimator by name"""
        self.estimators = [e for e in self.estimators if e.name != name]
        self.estimator_weights.pop(name, None)
    
    def set_weight(self, estimator_name: str, weight: float):
        """Manually set weight for an estimator"""
        if estimator_name in self.estimator_weights:
            self.estimator_weights[estimator_name] = max(0, min(2.0, weight))
    
    def _classify_time_horizon(self, days: float) -> str:
        """Classify estimate into time horizon categories"""
        if days <= 5:
            return "SHORT"
        elif days <= 20:
            return "MEDIUM"
        else:
            return "LONG"
    
    def _calculate_agreement_bonus(self, estimates: List[TimeEstimate]) -> float:
        """
        Calculate bonus confidence when estimators agree.
        Higher agreement = higher confidence in ensemble.
        """
        if len(estimates) < 2:
            return 0
        
        days_list = [e.days_to_target for e in estimates]
        mean_days = sum(days_list) / len(days_list)
        
        if mean_days <= 0:
            return 0
        
        # Calculate coefficient of variation
        variance = sum((d - mean_days) ** 2 for d in days_list) / len(days_list)
        cv = (variance ** 0.5) / mean_days
        
        # Lower CV = higher agreement = higher bonus
        agreement = 1 - min(1.0, cv)
        return agreement * 0.2  # Up to 20% confidence bonus
    
    def estimate(
        self,
        current_price: float,
        target_price: float,
        stop_price: float,
        data_points: List[dict],
        direction: str = "long"
    ) -> Optional[EnsembleTimeEstimate]:
        """
        Generate ensemble time estimate by combining all estimators.
        """
        if not self.estimators:
            return None
        
        # Collect estimates from all estimators
        individual_estimates: List[TimeEstimate] = []
        
        for estimator in self.estimators:
            try:
                estimate = estimator.estimate(
                    current_price, target_price, stop_price,
                    data_points, direction
                )
                if estimate:
                    individual_estimates.append(estimate)
            except Exception as e:
                # Log but continue with other estimators
                print(f"Warning: {estimator.name} failed: {e}")
                continue
        
        if len(individual_estimates) < self.min_estimators:
            # Not enough valid estimates
            if individual_estimates:
                # Return single estimate if we have one
                est = individual_estimates[0]
                return EnsembleTimeEstimate(
                    days_to_target=est.days_to_target,
                    days_to_stop=est.days_to_stop,
                    confidence=est.confidence * 0.5,  # Reduced confidence
                    range_low=est.range_low,
                    range_high=est.range_high,
                    time_horizon=self._classify_time_horizon(est.days_to_target),
                    individual_estimates=individual_estimates,
                    weights_used={est.estimator_name: 1.0}
                )
            return None
        
        # Calculate weighted average
        total_weight = 0
        weighted_target_days = 0
        weighted_stop_days = 0
        weighted_confidence = 0
        all_range_lows = []
        all_range_highs = []
        weights_used = {}
        
        for est in individual_estimates:
            # Weight = base weight * confidence
            base_weight = self.estimator_weights.get(est.estimator_name, 1.0)
            effective_weight = base_weight * est.confidence
            
            weights_used[est.estimator_name] = effective_weight
            total_weight += effective_weight
            
            weighted_target_days += est.days_to_target * effective_weight
            weighted_stop_days += est.days_to_stop * effective_weight
            weighted_confidence += est.confidence * effective_weight
            all_range_lows.append(est.range_low)
            all_range_highs.append(est.range_high)
        
        if total_weight <= 0:
            return None
        
        # Normalize
        avg_target_days = weighted_target_days / total_weight
        avg_stop_days = weighted_stop_days / total_weight
        avg_confidence = weighted_confidence / total_weight
        
        # Normalize weights for reporting
        for name in weights_used:
            weights_used[name] /= total_weight
        
        # Range: use min of lows and max of highs (conservative)
        range_low = min(all_range_lows)
        range_high = max(all_range_highs)
        
        # Apply agreement bonus
        agreement_bonus = self._calculate_agreement_bonus(individual_estimates)
        final_confidence = min(0.95, avg_confidence + agreement_bonus)
        
        return EnsembleTimeEstimate(
            days_to_target=avg_target_days,
            days_to_stop=avg_stop_days,
            confidence=final_confidence,
            range_low=range_low,
            range_high=range_high,
            time_horizon=self._classify_time_horizon(avg_target_days),
            individual_estimates=individual_estimates,
            weights_used=weights_used
        )


def create_default_ensemble(include_ml: bool = True) -> EnsembleTimeEstimator:
    """
    Factory function to create ensemble with default estimators.
    
    Args:
        include_ml: Whether to include the SVM estimator (default True)
        
    Returns:
        Configured EnsembleTimeEstimator with all plugins loaded
    """
    from .atr_estimator import ATRTimeEstimator
    from .momentum_estimator import MomentumTimeEstimator
    from .pattern_estimator import PatternTimeEstimator
    from .monte_carlo_estimator import MonteCarloTimeEstimator
    from .svm_estimator import SVMTimeEstimator
    
    ensemble = EnsembleTimeEstimator()
    
    # Add core estimators
    ensemble.add_estimator(ATRTimeEstimator())
    ensemble.add_estimator(MomentumTimeEstimator())
    ensemble.add_estimator(PatternTimeEstimator())
    ensemble.add_estimator(MonteCarloTimeEstimator())
    
    # Optionally add ML estimator
    if include_ml:
        ensemble.add_estimator(SVMTimeEstimator())
    
    return ensemble


def list_available_estimators() -> List[str]:
    """List all available estimator classes"""
    return [
        "ATRTimeEstimator - Volatility-based timing",
        "MomentumTimeEstimator - Momentum indicator analysis",
        "PatternTimeEstimator - Historical pattern matching",
        "MonteCarloTimeEstimator - Simulation-based probability",
        "SVMTimeEstimator - Machine learning (trainable)",
    ]
