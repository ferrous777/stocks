from datetime import datetime
from typing import Dict, List, Optional, Tuple
from .strategy import Strategy, SignalType
import numpy as np
from market_data.data_types import BacktestResult, TradeMetrics, Trade, HistoricalData

class MomentumStrategy(Strategy):
    def __init__(self):
        super().__init__(
            name="Momentum",
            description="Price momentum strategy using RSI and rate of change"
        )
        self.rsi_period = 14
        self.roc_period = 10
        self.rsi_oversold = 30
        self.rsi_overbought = 70
        self.min_momentum = 0.05
        self.profit_target = 0.12
        self.stop_loss = 0.06
    
    def requires_fundamentals(self) -> bool:
        return False
    
    def get_min_required_points(self) -> int:
        return max(self.rsi_period, self.roc_period)
    
    def calculate_rsi(self, prices: List[float], period: int) -> float:
        """Calculate Relative Strength Index"""
        if len(prices) < period + 1:
            return 50.0
        
        gains = []
        losses = []
        
        for i in range(1, len(prices)):
            change = prices[i] - prices[i-1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        
        if len(gains) < period:
            return 50.0
        
        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    def calculate_rate_of_change(self, prices: List[float], period: int) -> float:
        """Calculate Rate of Change"""
        if len(prices) < period + 1:
            return 0.0
        
        current_price = prices[-1]
        past_price = prices[-period-1]
        
        if past_price == 0:
            return 0.0
        
        roc = (current_price - past_price) / past_price
        return roc
    
    def generate_signals(self, data_points: List[HistoricalData], index: int) -> Tuple[SignalType, float, str]:
        """Generate trading signals based on momentum analysis"""
        if index < self.get_min_required_points():
            return "hold", 0.0, "Insufficient data"
        
        # Get recent prices
        recent_data = data_points[max(0, index - self.rsi_period):index + 1]
        prices = [point.close for point in recent_data]
        
        if len(prices) < self.get_min_required_points():
            return "hold", 0.0, "Insufficient price data"
        
        # Calculate momentum indicators
        rsi = self.calculate_rsi(prices, self.rsi_period)
        roc = self.calculate_rate_of_change(prices, self.roc_period)
        
        current_price = prices[-1]
        
        # Generate signals
        if rsi < self.rsi_oversold and roc > self.min_momentum:
            confidence = min(0.9, (self.rsi_oversold - rsi) / 20 + abs(roc) * 2)
            return "buy", confidence, f"Oversold RSI ({rsi:.1f}) with positive momentum ({roc:.3f})"
        
        elif rsi > self.rsi_overbought and roc < -self.min_momentum:
            confidence = min(0.9, (rsi - self.rsi_overbought) / 20 + abs(roc) * 2)
            return "sell", confidence, f"Overbought RSI ({rsi:.1f}) with negative momentum ({roc:.3f})"
        
        else:
            return "hold", 0.0, f"Neutral momentum: RSI {rsi:.1f}, ROC {roc:.3f}"
    
    def backtest(self, data_points: List[HistoricalData]) -> BacktestResult:
        """Run backtest on historical data"""
        if len(data_points) < self.get_min_required_points():
            return BacktestResult(
                strategy_name=self.name,
                symbol="",
                start_date=data_points[0].date if data_points else datetime.now().date(),
                end_date=data_points[-1].date if data_points else datetime.now().date(),
                initial_capital=10000.0,
                final_capital=10000.0,
                total_return=0.0,
                trades=[],
                metrics=TradeMetrics()
            )
        
        trades = []
        capital = 10000.0
        position = 0
        entry_price = 0
        entry_date = None
        
        for i in range(self.get_min_required_points(), len(data_points)):
            signal, confidence, reason = self.generate_signals(data_points, i)
            current_data = data_points[i]
            
            # Exit position logic
            if position > 0:  # Long position
                exit_condition = (
                    signal == "sell" or
                    current_data.close >= entry_price * (1 + self.profit_target) or
                    current_data.close <= entry_price * (1 - self.stop_loss)
                )
                
                if exit_condition:
                    exit_price = current_data.close
                    profit = (exit_price - entry_price) * position
                    capital += profit
                    
                    trades.append(Trade(
                        entry_date=entry_date,
                        exit_date=current_data.date,
                        entry_price=entry_price,
                        exit_price=exit_price,
                        quantity=position,
                        profit=profit,
                        strategy=self.name
                    ))
                    
                    position = 0
                    entry_price = 0
                    entry_date = None
            
            # Enter position logic
            if position == 0 and signal == "buy" and confidence > 0.6:
                shares_to_buy = int(capital * 0.95 / current_data.close)
                if shares_to_buy > 0:
                    position = shares_to_buy
                    entry_price = current_data.close
                    entry_date = current_data.date
                    capital -= shares_to_buy * current_data.close
        
        # Close any remaining position
        if position > 0 and data_points:
            final_price = data_points[-1].close
            profit = (final_price - entry_price) * position
            capital += profit
            
            trades.append(Trade(
                entry_date=entry_date,
                exit_date=data_points[-1].date,
                entry_price=entry_price,
                exit_price=final_price,
                quantity=position,
                profit=profit,
                strategy=self.name
            ))
        
        # Calculate metrics
        total_return = (capital - 10000.0) / 10000.0
        
        metrics = TradeMetrics()
        if trades:
            profits = [trade.profit for trade in trades]
            metrics.total_trades = len(trades)
            metrics.winning_trades = len([p for p in profits if p > 0])
            metrics.losing_trades = len([p for p in profits if p < 0])
            metrics.win_rate = metrics.winning_trades / metrics.total_trades
            metrics.avg_profit = np.mean(profits)
            metrics.max_profit = max(profits)
            metrics.max_loss = min(profits)
            metrics.profit_factor = abs(sum([p for p in profits if p > 0]) / sum([p for p in profits if p < 0])) if any(p < 0 for p in profits) else float('inf')
        
        return BacktestResult(
            strategy_name=self.name,
            symbol="",
            start_date=data_points[0].date,
            end_date=data_points[-1].date,
            initial_capital=10000.0,
            final_capital=capital,
            total_return=total_return,
            trades=trades,
            metrics=metrics
        )
