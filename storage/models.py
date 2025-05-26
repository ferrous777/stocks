from datetime import datetime
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass, asdict
import json

@dataclass
class DailySnapshot:
    """All metrics for a symbol on a given date"""
    date: str  # YYYY-MM-DD format
    symbol: str
    
    # Price data
    open: float
    high: float
    low: float
    close: float
    volume: int
    adjusted_close: float
    
    # Technical indicators
    sma_20: Optional[float] = None
    sma_50: Optional[float] = None
    sma_200: Optional[float] = None
    ema_12: Optional[float] = None
    ema_26: Optional[float] = None
    rsi: Optional[float] = None
    macd: Optional[float] = None
    macd_signal: Optional[float] = None
    macd_histogram: Optional[float] = None
    bollinger_upper: Optional[float] = None
    bollinger_lower: Optional[float] = None
    bollinger_middle: Optional[float] = None
    atr: Optional[float] = None
    
    # Additional metrics
    volatility: Optional[float] = None
    trend_strength: Optional[float] = None
    
    # Strategy signals (dict of strategy_name -> signal_data)
    strategy_signals: Optional[Dict[str, Any]] = None
    
    # Metadata
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    
    def __post_init__(self):
        if self.strategy_signals is None:
            self.strategy_signals = {}
        if self.created_at is None:
            self.created_at = datetime.now().isoformat()
        if self.updated_at is None:
            self.updated_at = datetime.now().isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DailySnapshot':
        """Create from dictionary"""
        return cls(**data)
    
    def to_json(self) -> str:
        """Convert to JSON string"""
        return json.dumps(self.to_dict(), default=str)
    
    @classmethod
    def from_json(cls, json_str: str) -> 'DailySnapshot':
        """Create from JSON string"""
        return cls.from_dict(json.loads(json_str))

@dataclass
class StrategySignal:
    """Individual strategy signal data"""
    strategy_name: str
    signal_type: str  # 'buy', 'sell', 'hold'
    confidence: float  # 0.0 to 1.0
    strength: float  # Signal strength
    details: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}

@dataclass
class StrategyTimeSeries:
    """Historical strategy performance over time"""
    strategy_name: str
    symbol: str
    start_date: str
    end_date: str
    
    # Performance metrics
    total_return: float
    annualized_return: float
    win_rate: float
    sharpe_ratio: float
    max_drawdown: float
    
    # Trade statistics
    total_trades: int
    winning_trades: int
    losing_trades: int
    avg_win: float
    avg_loss: float
    
    # Daily performance data (date -> metrics)
    daily_performance: Dict[str, Dict[str, float]]
    
    def __post_init__(self):
        if not hasattr(self, 'daily_performance') or self.daily_performance is None:
            self.daily_performance = {}

@dataclass
class ComparisonMetrics:
    """Normalized data for cross-symbol/strategy comparison"""
    date: str
    base_symbol: str  # The symbol being compared
    
    # Relative performance vs benchmarks
    vs_spy: float  # Performance vs S&P 500
    vs_sector: Optional[float] = None  # Performance vs sector average
    vs_market: Optional[float] = None  # Performance vs overall market
    
    # Ranking metrics
    percentile_rank: Optional[float] = None  # Percentile rank among peers
    sector_rank: Optional[int] = None
    
    # Risk metrics
    beta: Optional[float] = None
    alpha: Optional[float] = None
    correlation_spy: Optional[float] = None

@dataclass
class ProjectionData:
    """Future value predictions with confidence intervals"""
    symbol: str
    projection_date: str  # Date projection was made
    target_date: str  # Date being projected to
    
    # Price projections
    predicted_price: float
    confidence_interval_lower: float
    confidence_interval_upper: float
    confidence_level: float  # e.g., 0.95 for 95% confidence
    
    # Model information
    model_name: str
    model_version: str
    input_features: List[str]
    
    # Actual outcome (filled in later)
    actual_price: Optional[float] = None
    prediction_error: Optional[float] = None
    
    # Metadata
    created_at: Optional[str] = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now().isoformat()
