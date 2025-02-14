from datetime import datetime, timedelta
from typing import List, Dict, Any
from .recommendation import Recommendation, RecommendationType
from strategies.strategy import Strategy
from market_data.market_data import MarketData

class RecommendationEngine:
    def __init__(self):
        self.min_confidence = 0.6
        self.account_size = 100000  # Default $100k account
    
    def generate_recommendations(
        self,
        symbols: List[str],
        analysis_results: Dict[str, Dict],
        backtest_results: Dict[str, Dict]
    ) -> Dict[str, Any]:
        """Generate trading recommendations by combining analysis and backtest results"""
        recommendations = {}
        
        for symbol in symbols:
            # Collect signals from all strategies
            signals = []
            for strategy_name, analysis in analysis_results.items():
                if symbol not in analysis:
                    continue
                    
                signal_data = analysis[symbol]
                if signal_data["signal"] != "hold" and signal_data["confidence"] >= self.min_confidence:
                    # Get current price from metrics, with fallback
                    metrics = signal_data.get("metrics", {})
                    current_price = metrics.get("close", 0)
                    
                    # Skip if we can't get a valid price
                    if current_price == 0:
                        continue
                    
                    # Get volatility and trend metrics
                    atr = metrics.get("atr", current_price * 0.02)
                    trend_strength = metrics.get("trend_strength", 0.5)
                    volatility = metrics.get("volatility", 0.02)
                    
                    # Base multipliers - increased profit potential
                    base_stop = 1.5
                    base_profit = 4.5  # Increased from 3.0 to 4.5
                    
                    # Adjust multipliers based on trend strength and volatility
                    stop_multiplier = base_stop * (1 + volatility)
                    # More aggressive profit scaling with trend strength
                    profit_multiplier = base_profit * (1 + (trend_strength * 1.5))
                    
                    if signal_data["signal"] == "long":
                        # Tighter stop loss (1.5-2% range)
                        stop_loss = current_price * (1 - (stop_multiplier * 0.015))
                        # More aggressive take profit (4.5-12% range depending on trend)
                        take_profit = current_price * (1 + (profit_multiplier * 0.02))
                    else:  # short or exit
                        stop_loss = current_price * (1 + (stop_multiplier * 0.015))
                        take_profit = current_price * (1 - (profit_multiplier * 0.02))
                        
                    signals.append({
                        "strategy": strategy_name,
                        "signal": signal_data["signal"],
                        "confidence": signal_data["confidence"],
                        "details": signal_data["details"],
                        "entry_price": current_price,
                        "stop_loss": stop_loss,
                        "take_profit": take_profit,
                    })
            
            if not signals:
                continue
            
            # Determine consensus action
            long_signals = [s for s in signals if s["signal"] == "long"]
            short_signals = [s for s in signals if s["signal"] == "short"]
            exit_signals = [s for s in signals if s["signal"] == "exit"]
            
            if long_signals and len(long_signals) > len(short_signals):
                action = "BUY"
                supporting_signals = long_signals
            elif short_signals and len(short_signals) > len(long_signals):
                action = "SELL"
                supporting_signals = short_signals
            elif exit_signals:
                action = "EXIT"
                supporting_signals = exit_signals
            else:
                continue
            
            # Calculate aggregate confidence
            total_confidence = sum(s["confidence"] for s in supporting_signals)
            avg_confidence = total_confidence / len(supporting_signals)
            
            # Get supporting strategy names
            supporting_strategies = [s["strategy"] for s in supporting_signals]
            
            # Combine details
            details = " | ".join(f"{s['strategy']}: {s['details']}" for s in supporting_signals)
            
            # Calculate position size based on account risk
            risk_per_trade = self.account_size * 0.02  # 2% risk per trade
            entry_price = supporting_signals[0]["entry_price"]
            stop_loss = supporting_signals[0]["stop_loss"]
            take_profit = supporting_signals[0]["take_profit"]
            risk_per_share = abs(entry_price - stop_loss)
            position_size = int(risk_per_trade / risk_per_share) if risk_per_share > 0 else 0
            
            recommendations[symbol] = {
                "action": action,
                "type": "LONG" if action == "BUY" else "SHORT" if action == "SELL" else "CLOSE",
                "confidence": avg_confidence,
                "supporting_strategies": supporting_strategies,
                "details": details,
                "entry_price": entry_price,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "position_size": position_size,
                "order_type": "LIMIT",
                "risk_reward": abs((take_profit - entry_price) / (stop_loss - entry_price)) if stop_loss != entry_price else 0
            }
        
        return recommendations

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