"""
Analysis module for market data aggregation and trend analysis
"""

from .aggregation import DataAggregator, AggregatedMetrics, RollingMetrics
from .fund_analyzer import FundAnalyzer, PerformanceMetrics, RiskMetrics, FundInfo

__all__ = [
    'DataAggregator', 
    'AggregatedMetrics', 
    'RollingMetrics',
    'FundAnalyzer',
    'PerformanceMetrics',
    'RiskMetrics',
    'FundInfo'
]
