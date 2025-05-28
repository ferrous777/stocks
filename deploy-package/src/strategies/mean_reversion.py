from datetime import datetime
from typing import Dict, List, Optional, Tuple
from .strategy import Strategy, SignalType
import numpy as np
from market_data.data_types import BacktestResult, TradeMetrics, Trade, HistoricalData

class MeanReversionStrategy(Strategy):
    def __init__(self):
        super().__init__(
            name="Mean Reversion",
            description="Mean reversion strategy using Bollinger Bands and price deviation"
        )
        self.bb_period = 20
        self.bb_std_dev = 2.0
        self.deviation_threshold = 1.5
        self.mean_period = 10
        self.profit_target = 0.08
        self.stop_loss = 0.05
    
    def requires_fundamentals(self) -> bool:
        return False
    
    def get_min_required_points(self) -> int:
        return max(self.bb_period, self.mean_period)
    
    def calculate_bollinger_bands(self, prices: List[float], period: int, std_dev: float) -> Tuple[float, float, float]:
        """Calculate Bollinger Bands (upper, middle, lower)"""
        if len(prices) < period:
            avg_price = np.mean(prices) if prices else 0
            return avg_price, avg_price, avg_price
        
        recent_prices = prices[-period:]
        middle = np.mean(recent_prices)
        std = np.std(recent_prices)
        
        upper = middle + (std * std_dev)
        lower = middle - (std * std_dev)
        
        return upper, middle, lower
    
    def calculate_price_deviation(self, prices: List[float], period: int) -> float:
        """Calculate how far current price deviates from mean"""
        if len(prices) < period + 1:
            return 0.0
        
        current_price = prices[-1]
        mean_price = np.mean(prices[-period:])
        
        if mean_price == 0:
            return 0.0
        
        deviation = (current_price - mean_price) / mean_price
        return deviation
    
    def generate_signals(self, data_points: List[HistoricalData], index: int) -> Tuple[SignalType, float, str]:
        """Generate trading signals based on mean reversion analysis"""
        if index < self.get_min_required_points():
            return "hold", 0.0, "Insufficient data"
        
        # Get recent prices
        recent_data = data_points[max(0, index - self.bb_period):index + 1]
        prices = [point.close for point in recent_data]
        
        if len(prices) < self.get_min_required_points():
            return "hold", 0.0, "Insufficient price data"
        
        current_price = prices[-1]
        
        # Calculate indicators
        bb_upper, bb_middle, bb_lower = self.calculate_bollinger_bands(prices, self.bb_period, self.bb_std_dev)
        price_deviation = self.calculate_price_deviation(prices, self.mean_period)
        
        # Generate signals
        if current_price <= bb_lower and price_deviation < -self.deviation_threshold / 100:
            # Price is below lower Bollinger Band and significantly below mean
            confidence = min(0.9, abs(price_deviation) * 10 + (bb_middle - current_price) / bb_middle)
            return "buy", confidence, f"Price below BB lower band (${current_price:.2f} vs ${bb_lower:.2f}), deviation {price_deviation:.3f}"
        
        elif current_price >= bb_upper and price_deviation > self.deviation_threshold / 100:
            # Price is above upper Bollinger Band and significantly above mean
            confidence = min(0.9, abs(price_deviation) * 10 + (current_price - bb_middle) / bb_middle)
            return "sell", confidence, f"Price above BB upper band (${current_price:.2f} vs ${bb_upper:.2f}), deviation {price_deviation:.3f}"
        
        else:
            return "hold", 0.0, f"Price within bands: ${bb_lower:.2f} < ${current_price:.2f} < ${bb_upper:.2f}"
    
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
                # Mean reversion: exit when price returns to mean or stop loss
                recent_prices = [dp.close for dp in data_points[max(0, i-self.mean_period):i+1]]
                mean_price = np.mean(recent_prices)
                
                exit_condition = (
                    current_data.close >= mean_price or  # Price returned to mean
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
            
            elif position < 0:  # Short position
                # Mean reversion: exit when price returns to mean or stop loss
                recent_prices = [dp.close for dp in data_points[max(0, i-self.mean_period):i+1]]
                mean_price = np.mean(recent_prices)
                
                exit_condition = (
                    current_data.close <= mean_price or  # Price returned to mean
                    current_data.close <= entry_price * (1 - self.profit_target) or
                    current_data.close >= entry_price * (1 + self.stop_loss)
                )
                
                if exit_condition:
                    exit_price = current_data.close
                    profit = (entry_price - exit_price) * abs(position)
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
            if position == 0 and confidence > 0.6:
                if signal == "buy":
                    shares_to_buy = int(capital * 0.95 / current_data.close)
                    if shares_to_buy > 0:
                        position = shares_to_buy
                        entry_price = current_data.close
                        entry_date = current_data.date
                        capital -= shares_to_buy * current_data.close
                
                elif signal == "sell":
                    # For mean reversion, we can short when price is too high
                    shares_to_short = int(capital * 0.95 / current_data.close)
                    if shares_to_short > 0:
                        position = -shares_to_short
                        entry_price = current_data.close
                        entry_date = current_data.date
                        capital += shares_to_short * current_data.close
        
        # Close any remaining position
        if position != 0 and data_points:
            final_price = data_points[-1].close
            if position > 0:
                profit = (final_price - entry_price) * position
            else:
                profit = (entry_price - final_price) * abs(position)
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
