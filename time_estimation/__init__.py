"""
Time Estimation Module

Plugin architecture for estimating time-to-target for trading predictions.
Each estimator can be added independently and the ensemble combines them.

Available Estimators:
- ATRTimeEstimator: Uses volatility (ATR) to estimate timing
- MomentumTimeEstimator: Uses momentum indicators (ROC, RSI, trend)
- PatternTimeEstimator: Finds similar historical patterns
- MonteCarloTimeEstimator: Simulates price paths
- SVMTimeEstimator: Machine learning based (can be trained)

Usage:
    from time_estimation import create_default_ensemble
    
    ensemble = create_default_ensemble()
    estimate = ensemble.estimate(
        current_price=100.0,
        target_price=110.0,
        stop_price=95.0,
        data_points=historical_data,
        direction="long"
    )
    print(f"Expected: {estimate.days_to_target} days")
"""

from .base import TimeEstimator, TimeEstimate
from .atr_estimator import ATRTimeEstimator
from .momentum_estimator import MomentumTimeEstimator
from .pattern_estimator import PatternTimeEstimator
from .monte_carlo_estimator import MonteCarloTimeEstimator
from .svm_estimator import SVMTimeEstimator
from .ensemble import EnsembleTimeEstimator, EnsembleTimeEstimate, create_default_ensemble, list_available_estimators

__all__ = [
    'TimeEstimator',
    'TimeEstimate',
    'ATRTimeEstimator',
    'MomentumTimeEstimator',
    'PatternTimeEstimator',
    'MonteCarloTimeEstimator',
    'SVMTimeEstimator',
    'EnsembleTimeEstimator',
    'EnsembleTimeEstimate',
    'create_default_ensemble',
    'list_available_estimators',
]
