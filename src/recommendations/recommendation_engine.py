from datetime import datetime, timedelta
from typing import List, Dict, Any
from .recommendation import Recommendation, RecommendationType
from strategies.strategy import Strategy
from market_data.market_data import MarketData

class RecommendationEngine:
    def __init__(self, market_data: MarketData, strategies: List[Strategy]):
        self.market_data = market_data
        self.strategies = strategies
        self.min_confidence = 0.6
        self.account_size = 100000  # Default $100k account
    
    def get_recommendations(
        self,
        symbol: str,
        days: int = 5,
        risk_per_trade: float = 0.02
    ) -> List[Recommendation]:
        """Get trading recommendations for a symbol"""
        recommendations = []
        
        # Get historical data
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days+5)  # Extra days for calculations
        historical_data = self.market_data.get_historical_data(
            symbol,
            start_date.strftime('%Y-%m-%d'),
            end_date.strftime('%Y-%m-%d')
        )
        
        # Get recent trading days
        trading_days = sorted(list(set(
            dp.date for dp in historical_data.data_points[-days:]
        )))
        
        # Get recommendations from each strategy
        for strategy in self.strategies:
            strategy.add_data(symbol, historical_data)
            
            for trade_date in trading_days:
                date = datetime.strptime(trade_date, '%Y-%m-%d')
                signals = strategy.get_live_signals(risk_per_trade, target_date=date)
                
                if not signals or symbol not in signals:
                    continue
                    
                signal = signals[symbol]['live_signal']
                
                if signal['confidence'] < self.min_confidence:
                    continue
                
                recommendations.append(Recommendation(
                    symbol=symbol,
                    date=date,
                    type=RecommendationType(signal['direction']),
                    strategy_name=strategy.name,
                    confidence=signal['confidence'],
                    entry_price=signal['entry_price'],
                    stop_loss=signal['stop_loss'],
                    take_profit=signal['take_profit'],
                    position_size=int(signal['position_size']),
                    order_type=signal['order_type'],
                    details=signal['details']
                ))
        
        return sorted(recommendations, key=lambda x: x.date, reverse=True) 