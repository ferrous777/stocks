from datetime import datetime, timedelta
from typing import Dict, List, Optional
from .strategy import Strategy, SignalType
from market_data.data_types import BacktestResult, TradeMetrics, Trade

class MovingAverageStrategy(Strategy):
    def __init__(self):
        super().__init__(
            name="Moving Average Crossover",
            description="Analyzes SMA 50 and 200 crossovers"
        )
        self.short_period = 50
        self.long_period = 200
    
    def requires_fundamentals(self) -> bool:
        return False
    
    def analyze(self, date: Optional[datetime] = None) -> Dict[str, Dict[str, any]]:
        results = {}
        
        for symbol in self.symbols:
            historical, _ = self.get_data(symbol)
            
            # Calculate SMAs
            closes = [point.close for point in historical.data_points]
            sma_50 = sum(closes[-50:]) / min(50, len(closes))
            sma_200 = sum(closes[-200:]) / min(200, len(closes))
            
            # Determine signal
            signal: SignalType = "hold"
            confidence = 0.0
            details = ""
            
            if len(closes) >= 50:  # Minimum data requirement
                spread = (sma_50 - sma_200) / sma_200
                
                # Previous day's values for crossover detection
                prev_closes = closes[:-1]
                prev_sma_50 = sum(prev_closes[-50:]) / min(50, len(prev_closes))
                prev_sma_200 = sum(prev_closes[-200:]) / min(200, len(prev_closes))
                prev_spread = (prev_sma_50 - prev_sma_200) / prev_sma_200
                
                # Detect crossovers
                if spread > 0 and prev_spread <= 0:
                    signal = "long"
                    confidence = min(abs(spread) * 100, 1.0)
                    details = f"Golden Cross: SMA 50 ({sma_50:.2f}) crossed above SMA 200 ({sma_200:.2f})"
                elif spread < 0 and prev_spread >= 0:
                    signal = "short"
                    confidence = min(abs(spread) * 100, 1.0)
                    details = f"Death Cross: SMA 50 ({sma_50:.2f}) crossed below SMA 200 ({sma_200:.2f})"
                elif spread > 0:
                    signal = "long"
                    confidence = min(abs(spread) * 50, 1.0)
                    details = f"Bullish trend: SMA 50 ({sma_50:.2f}) above SMA 200 ({sma_200:.2f})"
                elif spread < 0:
                    signal = "short"
                    confidence = min(abs(spread) * 50, 1.0)
                    details = f"Bearish trend: SMA 50 ({sma_50:.2f}) below SMA 200 ({sma_200:.2f})"
                
                # Generate exit signals
                if (signal == "long" and prev_spread > spread > 0) or \
                   (signal == "short" and prev_spread < spread < 0):
                    signal = "exit"
                    confidence = min(abs(spread) * 25, 1.0)
                    details = f"Trend weakening: spread changed from {prev_spread:.2%} to {spread:.2%}"
            
            results[symbol] = {
                "signal": signal,
                "confidence": confidence,
                "metrics": {
                    "sma_50": sma_50,
                    "sma_200": sma_200,
                    "close": closes[-1]
                },
                "details": details
            }
        
        return results
    
    def backtest(self, start_date: datetime, end_date: datetime) -> Dict[str, BacktestResult]:
        """Run strategy backtest"""
        results = {}
        
        for symbol in self.symbols:
            historical = self.data[symbol]
            
            # Get data points in date range
            data_points = [
                point for point in historical.data_points
                if start_date <= datetime.strptime(point.date, '%Y-%m-%d') <= end_date
            ]
            
            if len(data_points) < self.long_period:
                results[symbol] = BacktestResult(
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
                continue
            
            trades: List[Trade] = []
            position = None
            
            # Calculate moving averages for the entire period
            closes = [p.close for p in data_points]
            short_ma = self._calculate_ma(closes, self.short_period)
            long_ma = self._calculate_ma(closes, self.long_period)
            
            # Process each day
            for i in range(self.long_period, len(data_points)):
                point = data_points[i]
                date = datetime.strptime(point.date, '%Y-%m-%d')
                
                # Check for crossovers
                if short_ma[i] > long_ma[i] and short_ma[i-1] <= long_ma[i-1] and position is None:
                    # Golden cross - buy signal
                    position = {
                        'type': 'long',
                        'entry_date': date,
                        'entry_price': point.close,
                        'size': 100
                    }
                elif short_ma[i] < long_ma[i] and short_ma[i-1] >= long_ma[i-1] and position is not None:
                    # Death cross - sell signal
                    trades.append(Trade(
                        entry_date=position['entry_date'],
                        entry_price=position['entry_price'],
                        exit_date=date,
                        exit_price=point.close,
                        type=position['type'],
                        pnl=(point.close - position['entry_price']) * position['size'],
                        return_pct=(point.close / position['entry_price']) - 1,
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
                    pnl=(last_point.close - position['entry_price']) * position['size'],
                    return_pct=(last_point.close / position['entry_price']) - 1,
                    size=position['size']
                ))
            
            # Calculate returns
            total_return = sum(t.return_pct for t in trades)
            trading_days = (end_date - start_date).days
            annualized_return = ((1 + total_return) ** (365/trading_days)) - 1 if trading_days > 0 else 0
            avg_return = total_return / len(trades) if trades else 0
            
            results[symbol] = BacktestResult(
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
        
        return results
    
    def _calculate_strategy_metrics(self, trades: List[Dict[str, any]]) -> Dict[str, any]:
        """Calculate strategy-specific metrics for backtest summary"""
        if not trades:
            return {}
            
        # Calculate average SMA values and spreads
        sma_50_values = [t['metrics']['sma_50'] for t in trades if 'sma_50' in t['metrics']]
        sma_200_values = [t['metrics']['sma_200'] for t in trades if 'sma_200' in t['metrics']]
        
        if not sma_50_values or not sma_200_values:
            return {}
            
        avg_sma_50 = sum(sma_50_values) / len(sma_50_values)
        avg_sma_200 = sum(sma_200_values) / len(sma_200_values)
        avg_spread = sum((s50 - s200) for s50, s200 in zip(sma_50_values, sma_200_values)) / len(sma_50_values)
        
        # Calculate signal distribution
        total_signals = len(trades)
        long_ratio = sum(1 for t in trades if t['signal'] == 'long') / total_signals
        short_ratio = sum(1 for t in trades if t['signal'] == 'short') / total_signals
        exit_ratio = sum(1 for t in trades if t['signal'] == 'exit') / total_signals
        
        return {
            "avg_sma_50": avg_sma_50,
            "avg_sma_200": avg_sma_200,
            "avg_spread": avg_spread,
            "long_signal_ratio": long_ratio,
            "short_signal_ratio": short_ratio,
            "exit_signal_ratio": exit_ratio
        }
    
    def _calculate_ma(self, prices: List[float], period: int) -> List[float]:
        """Calculate Simple Moving Average"""
        ma = []
        for i in range(len(prices)):
            if i < period:
                ma.append(sum(prices[:i+1]) / (i+1))
            else:
                ma.append(sum(prices[i-period+1:i+1]) / period)
        return ma 