from dataclasses import dataclass
from typing import Dict, List, Any, Optional
from datetime import datetime

@dataclass
class DataPoint:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'date': self.date,
            'open': self.open,
            'high': self.high,
            'low': self.low,
            'close': self.close,
            'volume': self.volume
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DataPoint':
        return cls(**data)

@dataclass
class HistoricalData:
    symbol: str
    data_points: List[DataPoint]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'symbol': self.symbol,
            'data_points': [dp.to_dict() for dp in self.data_points]
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'HistoricalData':
        return cls(
            symbol=data['symbol'],
            data_points=[DataPoint.from_dict(dp) for dp in data['data_points']]
        )

@dataclass
class FinancialStatement:
    """Container for financial statement data"""
    date: str
    data: Dict[str, float]

@dataclass
class CompanyInfo:
    """Basic company information"""
    symbol: str
    name: str
    sector: Optional[str] = None
    industry: Optional[str] = None
    market_cap: Optional[float] = None
    pe_ratio: Optional[float] = None
    beta: Optional[float] = None
    dividend_yield: Optional[float] = None

@dataclass
class FundamentalData:
    symbol: str
    market_cap: float = 0
    pe_ratio: float = 0
    dividend_yield: float = 0
    beta: float = 0
    sector: str = ''
    industry: str = ''
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'symbol': self.symbol,
            'market_cap': self.market_cap,
            'pe_ratio': self.pe_ratio,
            'dividend_yield': self.dividend_yield,
            'beta': self.beta,
            'sector': self.sector,
            'industry': self.industry
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'FundamentalData':
        return cls(**data)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format"""
        result = {
            'symbol': self.symbol,
            'market_cap': self.market_cap,
            'pe_ratio': self.pe_ratio,
            'dividend_yield': self.dividend_yield,
            'beta': self.beta,
            'sector': self.sector,
            'industry': self.industry
        }
        
        return result 

@dataclass 
class TradeMetrics:
    total_return: float
    annualized_return: float
    total_trades_executed: int
    avg_return_per_trade: float

@dataclass
class Trade:
    entry_date: datetime
    entry_price: float
    exit_date: datetime
    exit_price: float
    type: str
    pnl: float
    return_pct: float
    size: int = 100

@dataclass
class BacktestResult:
    trades: List[Trade]
    strategy_returns: TradeMetrics
    buy_and_hold: Dict[str, float]
    total_trades: int

@dataclass 
class TradingSignal:
    signal: str
    confidence: float
    details: str
    metrics: Dict[str, float] 