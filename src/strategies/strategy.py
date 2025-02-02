from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple, Literal
from datetime import datetime
from market_data.data_types import HistoricalData, FundamentalData

SignalType = Literal["long", "short", "exit", "hold"]

class Strategy(ABC):
    """Base class for all trading strategies"""
    
    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        self._symbols: List[str] = []
        self.data: Dict[str, HistoricalData] = {}
        self.fundamentals: Dict[str, FundamentalData] = {}
    
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
    
    @abstractmethod
    def backtest(self, start_date: datetime, end_date: datetime) -> Dict[str, List[Dict[str, any]]]:
        """Run strategy backtest"""
        pass
    
    @abstractmethod
    def _calculate_strategy_metrics(self, trades: List[Dict[str, any]]) -> Dict[str, any]:
        """Calculate strategy-specific metrics for backtest summary"""
        pass
    
    @abstractmethod
    def requires_fundamentals(self) -> bool:
        """Whether fundamental data is required"""
        pass
    
    def __str__(self) -> str:
        return f"{self.name} - {self.description}" 