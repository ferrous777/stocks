from datetime import datetime
from typing import Dict, List, Optional, Tuple
from .strategy import Strategy, SignalType
import numpy as np
from market_data.data_types import BacktestResult, TradeMetrics, Trade, HistoricalData

class MACDStrategy(Strategy):
    def __init__(self):
        super().__init__(
            name="MACD Strategy",
            description="Moving Average Convergence Divergence strategy"
        )
        self.fast_period = 12
        self.slow_period = 26
        self.signal_period = 9
        self.min_required = max(self.slow_period, self.fast_period) + self.signal_period
        self.min_divergence = 0.02
    
    def requires_fundamentals(self) -> bool:
        return False
    
    def get_min_required_points(self) -> int:
        return self.min_required
    
    def generate_signals(self, data_points: List[HistoricalData], index: int) -> Tuple[SignalType, float, str]:
        """Generate trading signals based on MACD crossovers"""
        if index < self.min_required:
            return "hold", 0.0, "Insufficient data"
        
        # Calculate MACD line and signal line
        closes = [p.close for p in data_points[max(0, index-self.min_required):index+1]]
        macd_line = self._calculate_macd_line(closes)
        signal_line = self._calculate_signal_line(macd_line)
        
        if len(signal_line) < 2:
            return "hold", 0.0, "Insufficient data for signal line"
        
        current_macd = macd_line[-1]
        current_signal = signal_line[-1]
        prev_macd = macd_line[-2]
        prev_signal = signal_line[-2]
        
        # Calculate histogram for signal strength
        histogram = current_macd - current_signal
        prev_histogram = prev_macd - prev_signal
        
        # Generate signals based on crossovers
        if current_macd > current_signal and prev_macd <= prev_signal:
            # Bullish crossover
            confidence = min(abs(histogram) * 2, 1.0)
            details = f"Bullish MACD crossover (MACD: {current_macd:.3f}, Signal: {current_signal:.3f})"
            return "long", confidence, details
            
        elif current_macd < current_signal and prev_macd >= prev_signal:
            # Bearish crossover
            confidence = min(abs(histogram) * 2, 1.0)
            details = f"Bearish MACD crossover (MACD: {current_macd:.3f}, Signal: {current_signal:.3f})"
            return "short", confidence, details
        
        # Generate exit signals
        if (histogram > 0 and histogram < prev_histogram) or \
           (histogram < 0 and histogram > prev_histogram):
            confidence = min(abs(histogram), 1.0)
            details = f"MACD momentum weakening (Histogram: {histogram:.3f})"
            return "exit", confidence, details
        
        return "hold", 0.0, "No significant MACD signals"
    
    def _calculate_macd_line(self, prices: List[float]) -> List[float]:
        """Calculate MACD line (difference between fast and slow EMAs)"""
        if len(prices) < self.slow_period:
            return []
        
        fast_ema = self._calculate_ema(np.array(prices), self.fast_period)
        slow_ema = self._calculate_ema(np.array(prices), self.slow_period)
        
        # MACD is the difference between fast and slow EMAs
        return list(fast_ema - slow_ema)
    
    def _calculate_signal_line(self, macd_line: List[float]) -> List[float]:
        """Calculate signal line (EMA of MACD line)"""
        return self._calculate_ema(np.array(macd_line), self.signal_period).tolist()
    
    def _calculate_ema(self, prices: np.ndarray, period: int) -> np.ndarray:
        """Calculate Exponential Moving Average"""
        if len(prices) < period:
            return np.array([])
        
        multiplier = 2 / (period + 1)
        ema = np.array([np.mean(prices[:period])])  # First EMA is SMA
        
        for price in prices[period:]:
            ema = np.append(ema, (price - ema[-1]) * multiplier + ema[-1])
        
        return ema
    
    def _calculate_strategy_metrics(self, trades: List[Dict[str, any]]) -> Dict[str, any]:
        """Calculate strategy-specific metrics for backtest summary"""
        if not trades:
            return {}
        
        # Calculate signal distribution
        total_signals = len(trades)
        long_ratio = sum(1 for t in trades if t['signal'] == 'long') / total_signals
        short_ratio = sum(1 for t in trades if t['signal'] == 'short') / total_signals
        exit_ratio = sum(1 for t in trades if t['signal'] == 'exit') / total_signals
        
        return {
            "long_signal_ratio": long_ratio,
            "short_signal_ratio": short_ratio,
            "exit_signal_ratio": exit_ratio
        }
    
    def analyze(self, date: Optional[datetime] = None) -> Dict[str, Dict[str, any]]:
        results = {}
        
        for symbol in self.symbols:
            historical, _ = self.get_data(symbol)
            close_prices = [point.close for point in historical.data_points]
            
            if len(close_prices) < self.slow_period:
                results[symbol] = {
                    "signal": "hold",
                    "confidence": 0,
                    "metrics": {},
                    "details": "Insufficient data for MACD calculation"
                }
                continue
            
            macd, signal, histogram = self._calculate_macd(close_prices)
            
            current_macd = macd[-1]
            current_signal = signal[-1]
            current_hist = histogram[-1]
            prev_hist = histogram[-2]
            
            bullish_div, bearish_div = self._check_divergence(
                close_prices[-10:], 
                macd[-10:]
            )
            
            signal_type: SignalType = "hold"
            confidence = 0.0
            details = []
            
            # Generate trading signals
            if current_hist > 0 and prev_hist < 0:  # Bullish crossover
                signal_type = "long"
                confidence = min(abs(current_hist / current_macd), 1.0)
                details.append("MACD crossed above signal line")
                if bullish_div:
                    confidence = min(confidence * 1.5, 1.0)
                    details.append("with bullish divergence")
            elif current_hist < 0 and prev_hist > 0:  # Bearish crossover
                signal_type = "short"
                confidence = min(abs(current_hist / current_macd), 1.0)
                details.append("MACD crossed below signal line")
                if bearish_div:
                    confidence = min(confidence * 1.5, 1.0)
                    details.append("with bearish divergence")
            elif (current_hist > 0 and current_hist < prev_hist) or \
                 (current_hist < 0 and current_hist > prev_hist):
                signal_type = "exit"
                confidence = min(abs(current_hist / current_macd) * 0.5, 1.0)
                details.append("MACD momentum weakening")
            
            results[symbol] = {
                "signal": signal_type,
                "confidence": confidence,
                "metrics": {
                    "macd": current_macd,
                    "signal": current_signal,
                    "histogram": current_hist,
                    "close": close_prices[-1]
                },
                "details": " ".join(details) if details else "No significant MACD signals"
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
            
            if len(data_points) < self.slow_period + self.signal_period:
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
            
            # Calculate MACD for the entire period
            closes = [p.close for p in data_points]
            macd_line, signal_line, histogram = self._calculate_macd(closes)
            
            # Process each day
            for i in range(self.slow_period + self.signal_period, len(data_points)):
                point = data_points[i]
                date = datetime.strptime(point.date, '%Y-%m-%d')
                
                current_hist = histogram[i]
                prev_hist = histogram[i-1]
                
                # Generate signals
                if prev_hist < 0 and current_hist > 0 and position is None:  # Bullish crossover
                    position = {
                        'type': 'long',
                        'entry_date': date,
                        'entry_price': point.close,
                        'size': 100
                    }
                elif prev_hist > 0 and current_hist < 0 and position is not None:  # Bearish crossover
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
    
    def _calculate_macd(self, close_prices: List[float]) -> tuple[List[float], List[float], List[float]]:
        """Calculate MACD, Signal, and Histogram values"""
        prices = np.array(close_prices)
        
        # Calculate EMAs with proper padding
        fast_ema = np.zeros(len(prices))
        slow_ema = np.zeros(len(prices))
        
        # Calculate initial EMAs
        fast_ema[:self.fast_period] = np.mean(prices[:self.fast_period])
        slow_ema[:self.slow_period] = np.mean(prices[:self.slow_period])
        
        # Calculate remaining EMA values
        multiplier_fast = 2 / (self.fast_period + 1)
        multiplier_slow = 2 / (self.slow_period + 1)
        
        for i in range(self.fast_period, len(prices)):
            fast_ema[i] = (prices[i] - fast_ema[i-1]) * multiplier_fast + fast_ema[i-1]
        
        for i in range(self.slow_period, len(prices)):
            slow_ema[i] = (prices[i] - slow_ema[i-1]) * multiplier_slow + slow_ema[i-1]
        
        # Calculate MACD line
        macd_line = fast_ema - slow_ema
        
        # Calculate Signal line
        signal_line = np.zeros(len(macd_line))
        signal_line[:self.signal_period] = np.mean(macd_line[:self.signal_period])
        multiplier_signal = 2 / (self.signal_period + 1)
        
        for i in range(self.signal_period, len(macd_line)):
            signal_line[i] = (macd_line[i] - signal_line[i-1]) * multiplier_signal + signal_line[i-1]
        
        # Calculate histogram
        histogram = macd_line - signal_line
        
        return macd_line.tolist(), signal_line.tolist(), histogram.tolist()
    
    def _check_divergence(self, prices: List[float], macd_values: List[float], 
                         window: int = 5) -> tuple[bool, bool]:
        """Check for bullish/bearish divergences"""
        if len(prices) < window or len(macd_values) < window:
            return False, False
        
        price_min = min(prices[-window:])
        price_max = max(prices[-window:])
        macd_min = min(macd_values[-window:])
        macd_max = max(macd_values[-window:])
        
        price_change = (price_max - price_min) / price_min
        macd_change = macd_max - macd_min
        
        bullish = (price_change < 0 and macd_change > 0 and abs(price_change) > self.min_divergence)
        bearish = (price_change > 0 and macd_change < 0 and abs(price_change) > self.min_divergence)
        
        return bullish, bearish 