from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

class RecommendationType(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"

@dataclass
class Recommendation:
    symbol: str
    date: datetime
    type: RecommendationType
    strategy_name: str
    confidence: float
    entry_price: float
    stop_loss: float
    take_profit: float
    position_size: int
    order_type: str = "LIMIT"
    details: Optional[str] = None
    
    @property
    def risk_reward_ratio(self) -> float:
        """Calculate risk/reward ratio"""
        if self.entry_price == self.stop_loss:
            return 0.0
        return abs((self.take_profit - self.entry_price) / (self.stop_loss - self.entry_price))
    
    def to_dict(self):
        """Convert to dictionary format"""
        return {
            'date': self.date.strftime('%Y-%m-%d'),
            'symbol': self.symbol,
            'type': self.type.value,
            'strategy': self.strategy_name,
            'confidence': self.confidence,
            'entry_price': self.entry_price,
            'stop_loss': self.stop_loss,
            'take_profit': self.take_profit,
            'position_size': self.position_size,
            'order_type': self.order_type,
            'risk_reward': self.risk_reward_ratio,
            'details': self.details
        } 