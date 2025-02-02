from datetime import datetime
from typing import Dict, List, Optional
from .strategy import Strategy, SignalType
import numpy as np
from market_data.data_types import BacktestResult, TradeMetrics, Trade

class TrendFollowingStrategy(Strategy):
    def __init__(self):
        super().__init__(
            name="Trend Following",
            description="Multi-indicator trend following strategy"
        )
        self.atr_period = 10
        self.trend_period = 15
        self.breakout_threshold = 1.2
        self.min_trend_strength = 0.65
        self.profit_target = 0.15
        self.stop_loss = 0.08
    
    def requires_fundamentals(self) -> bool:
        return False
    
    def _calculate_atr(self, highs: List[float], lows: List[float], 
                      closes: List[float], period: int) -> List[float]:
        """Calculate Average True Range"""
        tr = []  # True Range
        for i in range(len(closes)):
            if i == 0:
                tr.append(highs[0] - lows[0])
            else:
                true_range = max([
                    highs[i] - lows[i],  # Current high-low
                    abs(highs[i] - closes[i-1]),  # Current high - prev close
                    abs(lows[i] - closes[i-1])  # Current low - prev close
                ])
                tr.append(true_range)
        
        # Calculate ATR using Simple Moving Average
        atr = []
        for i in range(len(tr)):
            if i < period:
                atr.append(sum(tr[:i+1]) / (i+1))
            else:
                atr.append(sum(tr[i-period+1:i+1]) / period)
        return atr
    
    def _calculate_trend_strength(self, closes: List[float], period: int) -> tuple[float, bool]:
        """Calculate trend strength and direction"""
        if len(closes) < period + 1:  # Need period + 1 points to calculate period returns
            return 0.0, True
        
        # Get the last period points
        window = closes[-period:]
        
        # Calculate daily returns
        returns = [window[i] > window[i-1] for i in range(1, len(window))]
        up_days = sum(returns)
        trend_strength = up_days / (period - 1)  # -1 because we look at changes between points
        uptrend = trend_strength > 0.5
        
        return trend_strength, uptrend
    
    def _calculate_support_resistance(self, highs: List[float], lows: List[float], 
                                    period: int) -> tuple[float, float]:
        """Calculate dynamic support and resistance levels"""
        if len(highs) < period:
            return highs[-1], lows[-1]
        
        recent_highs = highs[-period:]
        recent_lows = lows[-period:]
        
        resistance = max(recent_highs)
        support = min(recent_lows)
        
        return support, resistance
    
    def analyze(self, date: Optional[datetime] = None) -> Dict[str, Dict[str, any]]:
        results = {}
        
        for symbol in self.symbols:
            historical, _ = self.get_data(symbol)
            
            if len(historical.data_points) < self.trend_period:
                results[symbol] = {
                    "signal": "hold",
                    "confidence": 0,
                    "metrics": {},
                    "details": "Insufficient data for trend analysis"
                }
                continue
            
            # Prepare price data
            closes = [point.close for point in historical.data_points]
            highs = [point.high for point in historical.data_points]
            lows = [point.low for point in historical.data_points]
            
            # Calculate using the appropriate window of data
            window_closes = closes[-self.trend_period-1:]  # Get enough points for trend calculation
            trend_strength, uptrend = self._calculate_trend_strength(window_closes, self.trend_period)
            
            # Calculate indicators
            atr = self._calculate_atr(highs, lows, closes, self.atr_period)
            support, resistance = self._calculate_support_resistance(highs, lows, self.trend_period)
            
            current_close = closes[-1]
            current_atr = atr[-1]
            
            # Generate trading signal
            signal: SignalType = "hold"
            confidence = 0.0
            details = []
            
            # Check for breakouts and trend strength
            if current_close > resistance + (current_atr * self.breakout_threshold):
                signal = "long"
                confidence = min(trend_strength * 1.5, 1.0)
                details.append("Price breakout above resistance")
            elif current_close < support - (current_atr * self.breakout_threshold):
                signal = "short"
                confidence = min((1 - trend_strength) * 1.5, 1.0)
                details.append("Price breakdown below support")
            elif trend_strength > self.min_trend_strength:
                if uptrend:
                    signal = "long"
                    confidence = trend_strength
                    details.append(f"Strong uptrend ({trend_strength:.1%} strength)")
                else:
                    signal = "short"
                    confidence = 1 - trend_strength
                    details.append(f"Strong downtrend ({(1-trend_strength):.1%} strength)")
            
            # Generate exit signals
            if signal in ["long", "short"]:
                if abs(current_close - (support + resistance) / 2) < current_atr:
                    signal = "exit"
                    confidence = 0.5
                    details.append("Price reverting to mean")
            
            results[symbol] = {
                "signal": signal,
                "confidence": confidence,
                "metrics": {
                    "trend_strength": trend_strength,
                    "atr": current_atr,
                    "support": support,
                    "resistance": resistance,
                    "close": current_close
                },
                "details": " with ".join(details) if details else "No significant trend"
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
            
            if len(data_points) < self.trend_period:
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
            for i in range(self.trend_period, len(data_points)):
                current_slice = slice(max(0, i-self.trend_period), i+1)
                highs = [p.high for p in data_points[current_slice]]
                lows = [p.low for p in data_points[current_slice]]
                closes = [p.close for p in data_points[current_slice]]
                
                atr = self._calculate_atr(highs, lows, closes, self.atr_period)[-1]
                trend_strength, uptrend = self._calculate_trend_strength(closes, self.trend_period)
                support, resistance = self._calculate_support_resistance(highs, lows, self.trend_period)
                
                current_close = closes[-1]
                point = data_points[i]
                date = datetime.strptime(point.date, '%Y-%m-%d')
                
                # Generate signals
                if position is None:  # Look for entry signals
                    # Strong trend entry conditions
                    strong_trend = trend_strength > self.min_trend_strength * 1.2
                    # Volume confirmation (if available)
                    volume_increase = point.volume > sum([p.volume for p in data_points[i-5:i]]) / 5 * 1.5 if i >= 5 else False
                    
                    if ((current_close > resistance + (atr * self.breakout_threshold) and trend_strength > self.min_trend_strength) or \
                       (strong_trend and uptrend)) and volume_increase:
                        position = {
                            'type': 'long',
                            'entry_date': date,
                            'entry_price': current_close,
                            'size': 100,
                            'stop_loss': current_close * (1 - self.stop_loss),
                            'profit_target': current_close * (1 + self.profit_target)
                        }
                    elif ((current_close < support - (atr * self.breakout_threshold) and trend_strength > self.min_trend_strength) or \
                         (strong_trend and not uptrend)) and volume_increase:
                        position = {
                            'type': 'short',
                            'entry_date': date,
                            'entry_price': current_close,
                            'size': 100,
                            'stop_loss': current_close * (1 + self.stop_loss),
                            'profit_target': current_close * (1 - self.profit_target)
                        }
                else:  # Look for exit signals
                    # Check stop loss and profit target
                    if position['type'] == 'long':
                        if current_close <= position['stop_loss'] or current_close >= position['profit_target']:
                            should_exit = True
                        else:
                            should_exit = (
                                (current_close < support - (atr * self.breakout_threshold)) or
                                (trend_strength < self.min_trend_strength * 0.7) or  # More lenient trend weakening
                                (not uptrend and trend_strength > self.min_trend_strength * 1.1)  # Stronger reversal confirmation
                            )
                    else:  # short position
                        if current_close >= position['stop_loss'] or current_close <= position['profit_target']:
                            should_exit = True
                        else:
                            should_exit = (
                                (current_close > resistance + (atr * self.breakout_threshold)) or
                                (trend_strength < self.min_trend_strength * 0.7) or  # More lenient trend weakening
                                (uptrend and trend_strength > self.min_trend_strength * 1.1)  # Stronger reversal confirmation
                            )
                    
                    if should_exit:
                        trades.append(Trade(
                            entry_date=position['entry_date'],
                            entry_price=position['entry_price'],
                            exit_date=date,
                            exit_price=current_close,
                            type=position['type'],
                            pnl=(current_close - position['entry_price']) * position['size'] if position['type'] == 'long'
                                else (position['entry_price'] - current_close) * position['size'],
                            return_pct=(current_close / position['entry_price'] - 1) if position['type'] == 'long'
                                else (position['entry_price'] / current_close - 1),
                            size=position['size']
                        ))
                        position = None
            
            # Close any open position at the end
            if position is not None:
                last_point = data_points[-1]
                last_close = last_point.close
                trades.append(Trade(
                    entry_date=position['entry_date'],
                    entry_price=position['entry_price'],
                    exit_date=datetime.strptime(last_point.date, '%Y-%m-%d'),
                    exit_price=last_close,
                    type=position['type'],
                    pnl=(last_close - position['entry_price']) * position['size'] if position['type'] == 'long'
                        else (position['entry_price'] - last_close) * position['size'],
                    return_pct=(last_close / position['entry_price'] - 1) if position['type'] == 'long'
                        else (position['entry_price'] / last_close - 1),
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
        if not trades:
            return {}
        
        trend_strengths = [t['metrics']['trend_strength'] for t in trades]
        atr_values = [t['metrics']['atr'] for t in trades]
        
        total_signals = len(trades)
        long_ratio = sum(1 for t in trades if t['signal'] == 'long') / total_signals
        short_ratio = sum(1 for t in trades if t['signal'] == 'short') / total_signals
        exit_ratio = sum(1 for t in trades if t['signal'] == 'exit') / total_signals
        
        breakouts_up = sum(1 for t in trades if t['signal'] == 'long' and 'breakout' in t['details'].lower())
        breakouts_down = sum(1 for t in trades if t['signal'] == 'short' and 'breakdown' in t['details'].lower())
        
        return {
            "avg_trend_strength": sum(trend_strengths) / len(trend_strengths),
            "avg_atr": sum(atr_values) / len(atr_values),
            "breakouts_up": breakouts_up,
            "breakouts_down": breakouts_down,
            "breakout_ratio": (breakouts_up + breakouts_down) / total_signals,
            "long_signal_ratio": long_ratio,
            "short_signal_ratio": short_ratio,
            "exit_signal_ratio": exit_ratio
        } 