"""
Adapter to convert existing data structures to new storage models
"""
from datetime import datetime
from typing import Dict, Any, Optional
import sys
import os

# Add market_data to path if not running from package
try:
    from ..market_data.data_types import DataPoint, HistoricalData, FundamentalData
except ImportError:
    # Direct import for standalone testing
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    from market_data.data_types import DataPoint, HistoricalData, FundamentalData

from .models import DailySnapshot, StrategySignal

class DataAdapter:
    """Convert between old and new data formats"""
    
    @staticmethod
    def datapoint_to_snapshot(datapoint: DataPoint, symbol: str, 
                            indicators: Optional[Dict[str, float]] = None,
                            strategy_signals: Optional[Dict[str, Any]] = None) -> DailySnapshot:
        """Convert DataPoint to DailySnapshot"""
        
        # Parse indicators if provided
        tech_indicators = indicators or {}
        
        return DailySnapshot(
            date=datapoint.date,
            symbol=symbol,
            open=datapoint.open,
            high=datapoint.high,
            low=datapoint.low,
            close=datapoint.close,
            volume=datapoint.volume,
            adjusted_close=datapoint.close,  # Use close as adjusted_close if not available
            
            # Technical indicators
            sma_20=tech_indicators.get('sma_20'),
            sma_50=tech_indicators.get('sma_50'),
            sma_200=tech_indicators.get('sma_200'),
            ema_12=tech_indicators.get('ema_12'),
            ema_26=tech_indicators.get('ema_26'),
            rsi=tech_indicators.get('rsi'),
            macd=tech_indicators.get('macd'),
            macd_signal=tech_indicators.get('macd_signal'),
            macd_histogram=tech_indicators.get('macd_histogram'),
            bollinger_upper=tech_indicators.get('bollinger_upper'),
            bollinger_lower=tech_indicators.get('bollinger_lower'),
            bollinger_middle=tech_indicators.get('bollinger_middle'),
            atr=tech_indicators.get('atr'),
            volatility=tech_indicators.get('volatility'),
            trend_strength=tech_indicators.get('trend_strength'),
            
            # Strategy signals
            strategy_signals=strategy_signals or {}
        )
    
    @staticmethod
    def historical_to_snapshots(historical: HistoricalData, symbol: str) -> list[DailySnapshot]:
        """Convert HistoricalData to list of DailySnapshots"""
        snapshots = []
        
        for datapoint in historical.data_points:
            snapshot = DataAdapter.datapoint_to_snapshot(datapoint, symbol)
            snapshots.append(snapshot)
        
        return snapshots
    
    @staticmethod
    def snapshot_to_datapoint(snapshot: DailySnapshot) -> DataPoint:
        """Convert DailySnapshot back to DataPoint (for backward compatibility)"""
        return DataPoint(
            date=snapshot.date,
            open=snapshot.open,
            high=snapshot.high,
            low=snapshot.low,
            close=snapshot.close,
            volume=snapshot.volume,
            adjusted_close=snapshot.adjusted_close
        )
    
    @staticmethod
    def add_technical_indicators(snapshot: DailySnapshot, indicators: Dict[str, float]) -> DailySnapshot:
        """Add technical indicators to existing snapshot"""
        # Update the snapshot with new indicators
        for key, value in indicators.items():
            if hasattr(snapshot, key):
                setattr(snapshot, key, value)
        
        snapshot.updated_at = datetime.now().isoformat()
        return snapshot
    
    @staticmethod
    def add_strategy_signal(snapshot: DailySnapshot, strategy_name: str, 
                          signal_data: Dict[str, Any]) -> DailySnapshot:
        """Add strategy signal to snapshot"""
        if snapshot.strategy_signals is None:
            snapshot.strategy_signals = {}
        
        snapshot.strategy_signals[strategy_name] = signal_data
        snapshot.updated_at = datetime.now().isoformat()
        return snapshot
