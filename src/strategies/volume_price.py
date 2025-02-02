from datetime import datetime
from typing import Dict, List, Optional
from .strategy import Strategy, SignalType
from market_data.data_types import BacktestResult, TradeMetrics, Trade

class VolumePriceStrategy(Strategy):
    def __init__(self):
        super().__init__(
            name="Volume-Price Analysis",
            description="Analyzes volume and price trends"
        )
        self.volume_threshold = 2.0  # Volume spike threshold
        self.price_threshold = 0.02  # 2% price change threshold
        self.period = 20  # Period for volume average calculation
    
    def requires_fundamentals(self) -> bool:
        return False
    
    def analyze(self, date: Optional[datetime] = None) -> Dict[str, Dict[str, any]]:
        results = {}
        
        for symbol in self.symbols:
            historical, _ = self.get_data(symbol)
            
            if len(historical.data_points) < 20:
                results[symbol] = {
                    "signal": "hold",
                    "confidence": 0,
                    "metrics": {},
                    "details": "Insufficient data"
                }
                continue
            
            # Calculate volume and price metrics
            volumes = [point.volume for point in historical.data_points[-20:]]
            closes = [point.close for point in historical.data_points[-20:]]
            
            avg_volume = sum(volumes[:-1]) / len(volumes[:-1])
            current_volume = volumes[-1]
            volume_ratio = current_volume / avg_volume
            
            prev_close = closes[-2]
            current_close = closes[-1]
            price_change = (current_close - prev_close) / prev_close
            
            # Determine signal
            signal: SignalType = "hold"
            confidence = 0.0
            details = []
            
            # Volume spike with price movement
            if volume_ratio > self.volume_threshold:
                if price_change > self.price_threshold:
                    signal = "long"
                    confidence = min(volume_ratio / self.volume_threshold, 1.0)
                    details.append(f"High volume up move: {volume_ratio:.1f}x avg volume")
                elif price_change < -self.price_threshold:
                    signal = "short"
                    confidence = min(volume_ratio / self.volume_threshold, 1.0)
                    details.append(f"High volume down move: {volume_ratio:.1f}x avg volume")
            
            # Exit signals on volume decline
            if signal != "hold" and volume_ratio < 0.5:
                signal = "exit"
                confidence = 0.5
                details.append("Volume returning to normal levels")
            
            results[symbol] = {
                "signal": signal,
                "confidence": confidence,
                "metrics": {
                    "volume_ratio": volume_ratio,
                    "daily_return": price_change,
                    "close": current_close
                },
                "details": " with ".join(details) if details else "No significant volume-price action"
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
            
            if len(data_points) < self.period:
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
            
            # Process each day
            for i in range(self.period, len(data_points)):
                window = data_points[i-self.period:i+1]
                point = data_points[i]
                date = datetime.strptime(point.date, '%Y-%m-%d')
                
                # Calculate volume and price changes
                avg_volume = sum(p.volume for p in window[:-1]) / len(window[:-1])
                volume_ratio = point.volume / avg_volume if avg_volume > 0 else 1.0
                price_change = (point.close - window[-2].close) / window[-2].close
                
                # Generate signals
                if volume_ratio > self.volume_threshold and price_change > self.price_threshold and position is None:
                    position = {
                        'type': 'long',
                        'entry_date': date,
                        'entry_price': point.close,
                        'size': 100
                    }
                elif volume_ratio > self.volume_threshold and price_change < -self.price_threshold and position is not None:
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
        
        # Calculate average volume ratios and returns
        volume_ratios = [t['metrics']['volume_ratio'] for t in trades if 'volume_ratio' in t['metrics']]
        daily_returns = [t['metrics']['daily_return'] for t in trades if 'daily_return' in t['metrics']]
        
        if not volume_ratios or not daily_returns:
            return {}
        
        # Signal distribution
        total_signals = len(trades)
        long_ratio = sum(1 for t in trades if t['signal'] == 'long') / total_signals
        short_ratio = sum(1 for t in trades if t['signal'] == 'short') / total_signals
        exit_ratio = sum(1 for t in trades if t['signal'] == 'exit') / total_signals
        
        return {
            "avg_volume_ratio": sum(volume_ratios) / len(volume_ratios),
            "max_volume_ratio": max(volume_ratios),
            "avg_daily_return": sum(daily_returns) / len(daily_returns),
            "long_signal_ratio": long_ratio,
            "short_signal_ratio": short_ratio,
            "exit_signal_ratio": exit_ratio
        } 