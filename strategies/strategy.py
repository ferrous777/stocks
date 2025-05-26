from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple, Literal
from datetime import datetime
from market_data.data_types import HistoricalData, FundamentalData, BacktestResult, TradeMetrics, Trade

SignalType = Literal["long", "short", "exit", "hold"]

class Strategy(ABC):
    """Base class for all trading strategies"""
    
    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        self._symbols: List[str] = []
        self.data: Dict[str, HistoricalData] = {}
        self.fundamentals: Dict[str, FundamentalData] = {}
        # Common strategy parameters
        self.position_size = 100
        self.profit_target = 0.15  # 15% profit target
        self.stop_loss = 0.08      # 8% stop loss
    
    def add_data(self, symbol: str, historical: HistoricalData, fundamental: Optional[FundamentalData] = None):
        """Add market data for a symbol"""
        if symbol not in self._symbols:
            self._symbols.append(symbol)
        self.data[symbol] = historical
        if fundamental:
            self.fundamentals[symbol] = fundamental
    
    @property
    def symbols(self) -> List[str]:
        """Get available symbols"""
        return self._symbols
    
    def get_data(self, symbol: str) -> Tuple[HistoricalData, Optional[FundamentalData]]:
        """Get data for a symbol"""
        if symbol not in self.data:
            raise KeyError(f"No data available for symbol {symbol}")
        return self.data[symbol], self.fundamentals.get(symbol)
    
    def calculate_buy_and_hold(self, symbol: str, start_date: datetime, end_date: datetime) -> Dict[str, float]:
        """Calculate buy and hold performance metrics"""
        historical, _ = self.get_data(symbol)
        
        # Find closest dates in data
        start_price = None
        end_price = None
        
        for point in historical.data_points:
            point_date = datetime.strptime(point.date, '%Y-%m-%d')
            if point_date >= start_date and start_price is None:
                start_price = point.close
            if point_date <= end_date:
                end_price = point.close
        
        if start_price is None or end_price is None:
            return {
                "start_price": 0,
                "end_price": 0,
                "total_return": 0,
                "annualized_return": 0
            }
        
        total_return = (end_price / start_price) - 1
        days = (end_date - start_date).days
        annualized_return = ((1 + total_return) ** (365/days)) - 1 if days > 0 else 0
        
        return {
            "start_price": start_price,
            "end_price": end_price,
            "total_return": total_return,
            "annualized_return": annualized_return
        }
    
    def calculate_strategy_returns(self, trades: List[Dict[str, any]], symbol: str) -> Dict[str, float]:
        """Calculate returns if all signals were executed"""
        if not trades:
            return {
                "total_return": 0,
                "annualized_return": 0,
                "total_trades_executed": 0,
                "current_position": "none"
            }
        
        historical, _ = self.get_data(symbol)
        position = "none"
        entry_price = 0
        total_return = 1.0  # Multiplicative returns
        trade_count = 0
        
        for trade in trades:
            price = trade['metrics']['close']
            signal = trade['signal']
            
            if signal == "long" and position == "none":
                # Enter long position
                position = "long"
                entry_price = price
            elif signal == "short" and position == "none":
                # Enter short position
                position = "short"
                entry_price = price
            elif signal == "exit":
                # Exit any position
                if position == "long":
                    trade_return = (price / entry_price) - 1
                    total_return *= (1 + trade_return)
                elif position == "short":
                    trade_return = (entry_price / price) - 1
                    total_return *= (1 + trade_return)
                position = "none"
                trade_count += 1
        
        # Account for open position using last available price
        if position != "none":
            last_price = historical.data_points[-1].close
            if position == "long":
                trade_return = (last_price / entry_price) - 1
            else:  # short
                trade_return = (entry_price / last_price) - 1
            total_return *= (1 + trade_return)
            trade_count += 1
        
        # Calculate annualized return
        days = (trades[-1]['date'] - trades[0]['date']).days
        annualized_return = ((total_return) ** (365/max(days, 1))) - 1
        
        return {
            "total_return": total_return - 1,  # Convert to percentage return
            "annualized_return": annualized_return,
            "total_trades_executed": trade_count,
            "current_position": position
        }
    
    def calculate_backtest_summary(self, trades: List[Dict[str, any]], symbol: str, 
                                 start_date: datetime, end_date: datetime) -> Dict[str, any]:
        """Calculate summary statistics for backtest trades"""
        if not trades:
            return {
                "total_trades": 0,
                "long_signals": 0,
                "short_signals": 0,
                "exit_signals": 0,
                "avg_confidence": 0,
                "max_confidence": 0,
                "period": "N/A",
                "metrics": {},
                "buy_and_hold": self.calculate_buy_and_hold(symbol, start_date, end_date),
                "strategy_returns": self.calculate_strategy_returns(trades, symbol)
            }
        
        long_signals = sum(1 for t in trades if t['signal'] == 'long')
        short_signals = sum(1 for t in trades if t['signal'] == 'short')
        exit_signals = sum(1 for t in trades if t['signal'] == 'exit')
        confidences = [t['confidence'] for t in trades]
        
        first_date = min(t['date'] for t in trades)
        last_date = max(t['date'] for t in trades)
        period = f"{first_date.strftime('%Y-%m-%d')} to {last_date.strftime('%Y-%m-%d')}"
        
        # Let derived classes add their own metrics
        metrics = self._calculate_strategy_metrics(trades)
        
        # Calculate buy and hold comparison
        buy_and_hold = self.calculate_buy_and_hold(symbol, start_date, end_date)
        
        # Calculate strategy returns
        strategy_returns = self.calculate_strategy_returns(trades, symbol)
        
        return {
            "total_trades": len(trades),
            "long_signals": long_signals,
            "short_signals": short_signals,
            "exit_signals": exit_signals,
            "avg_confidence": sum(confidences) / len(confidences) if confidences else 0,
            "max_confidence": max(confidences) if confidences else 0,
            "period": period,
            "metrics": metrics,
            "buy_and_hold": buy_and_hold,
            "strategy_returns": strategy_returns
        }
    
    @abstractmethod
    def analyze(self, date: Optional[datetime] = None) -> Dict[str, Dict[str, any]]:
        """Analyze current market data"""
        pass
    
    def backtest(self, start_date: datetime, end_date: datetime) -> Dict[str, BacktestResult]:
        """Run strategy backtest - common implementation"""
        results = {}
        
        for symbol in self.symbols:
            historical = self.data[symbol]
            
            # Get data points in date range
            data_points = [
                point for point in historical.data_points
                if start_date <= datetime.strptime(point.date, '%Y-%m-%d') <= end_date
            ]
            
            if len(data_points) < self.get_min_required_points():
                results[symbol] = self.create_empty_result(symbol, start_date, end_date)
                continue
            
            trades: List[Trade] = []
            position = None
            
            # Process each day
            for i in range(self.get_min_required_points(), len(data_points)):
                point = data_points[i]
                date = datetime.strptime(point.date, '%Y-%m-%d')
                current_close = point.close
                
                signal, confidence, details = self.generate_signals(data_points, i)
                
                # Handle entry signals
                if position is None and signal in ['long', 'short']:
                    position = {
                        'type': signal,
                        'entry_date': date,
                        'entry_price': current_close,
                        'size': self.position_size,
                        'stop_loss': current_close * (1 - self.stop_loss if signal == 'long' else -self.stop_loss),
                        'profit_target': current_close * (1 + self.profit_target if signal == 'long' else -self.profit_target)
                    }
                
                # Handle exit signals
                elif position is not None:
                    should_exit = signal == 'exit'
                    
                    # Check stop loss and profit target
                    if position['type'] == 'long':
                        should_exit = should_exit or current_close <= position['stop_loss'] or current_close >= position['profit_target']
                    else:  # short position
                        should_exit = should_exit or current_close >= position['stop_loss'] or current_close <= position['profit_target']
                    
                    if should_exit:
                        trades.append(Trade(
                            entry_date=position['entry_date'],
                            entry_price=position['entry_price'],
                            exit_date=date,
                            exit_price=current_close,
                            type=position['type'],
                            pnl=self.calculate_pnl(position['type'], current_close, position['entry_price'], position['size']),
                            return_pct=self.calculate_return(position['type'], current_close, position['entry_price']),
                            size=position['size']
                        ))
                        position = None
            
            # Close any open position at the end
            if position is not None:
                last_point = data_points[-1]
                trades.append(Trade(
                    entry_date=position['entry_date'],
                    entry_price=position['entry_price'],
                    exit_date=datetime.strptime(last_point.date, '%Y-%m-%d'),
                    exit_price=last_point.close,
                    type=position['type'],
                    pnl=self.calculate_pnl(position['type'], last_point.close, position['entry_price'], position['size']),
                    return_pct=self.calculate_return(position['type'], last_point.close, position['entry_price']),
                    size=position['size']
                ))
            
            results[symbol] = self.create_backtest_result(trades, symbol, start_date, end_date)
        
        return results
    
    def create_empty_result(self, symbol: str, start_date: datetime, end_date: datetime) -> BacktestResult:
        """Create empty backtest result for insufficient data"""
        return BacktestResult(
            trades=[],
            strategy_returns=TradeMetrics(
                total_return=0.0,
                annualized_return=0.0,
                total_trades_executed=0,
                avg_return_per_trade=0.0
            ),
            buy_and_hold=self.calculate_buy_and_hold(symbol, start_date, end_date),
            total_trades=0
        )
    
    def create_backtest_result(self, trades: List[Trade], symbol: str, 
                             start_date: datetime, end_date: datetime) -> BacktestResult:
        """Create BacktestResult from trades"""
        total_return = sum(t.return_pct for t in trades)
        trading_days = (end_date - start_date).days
        annualized_return = ((1 + total_return) ** (365/trading_days)) - 1 if trading_days > 0 else 0
        avg_return = total_return / len(trades) if trades else 0
        
        return BacktestResult(
            trades=trades,
            strategy_returns=TradeMetrics(
                total_return=total_return,
                annualized_return=annualized_return,
                total_trades_executed=len(trades),
                avg_return_per_trade=avg_return
            ),
            buy_and_hold=self.calculate_buy_and_hold(symbol, start_date, end_date),
            total_trades=len(trades)
        )
    
    def calculate_pnl(self, position_type: str, exit_price: float, entry_price: float, size: int) -> float:
        """Calculate P&L for a trade"""
        if position_type == 'long':
            return (exit_price - entry_price) * size
        return (entry_price - exit_price) * size
    
    def calculate_return(self, position_type: str, exit_price: float, entry_price: float) -> float:
        """Calculate return percentage for a trade"""
        if position_type == 'long':
            return (exit_price / entry_price) - 1
        return (entry_price / exit_price) - 1
    
    @abstractmethod
    def _calculate_strategy_metrics(self, trades: List[Dict[str, any]]) -> Dict[str, any]:
        """Calculate strategy-specific metrics for backtest summary"""
        pass
    
    @abstractmethod
    def requires_fundamentals(self) -> bool:
        """Whether fundamental data is required"""
        pass
    
    @abstractmethod
    def generate_signals(self, data_points: List[HistoricalData], index: int) -> Tuple[SignalType, float, str]:
        """Generate trading signals for a given point in time
        Returns: (signal_type, confidence, details)"""
        pass
    
    def __str__(self) -> str:
        return f"{self.name} - {self.description}" 