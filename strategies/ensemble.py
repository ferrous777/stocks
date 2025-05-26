from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from .strategy import Strategy, SignalType
import numpy as np
from market_data.data_types import BacktestResult, TradeMetrics, Trade, HistoricalData

class EnsembleStrategy(Strategy):
    def __init__(self, strategies: List[Strategy]):
        super().__init__(
            name="Ensemble Strategy",
            description="Combines signals from multiple strategies"
        )
        self.strategies = strategies
        self.min_confidence_threshold = 0.3
        self.evaluation_window = 20  # Trading days to evaluate performance
        self.learning_rate = 0.1  # Rate at which weights adjust
        self.strategy_weights = {s.name: 1.0 for s in strategies}  # Initial equal weights
        self.performance_history = {s.name: [] for s in strategies}
    
    def requires_fundamentals(self) -> bool:
        return any(s.requires_fundamentals() for s in self.strategies)
    
    def get_min_required_points(self) -> int:
        return max(s.get_min_required_points() for s in self.strategies)
    
    def add_data(self, symbol: str, historical, fundamental=None):
        """Add data to all underlying strategies"""
        super().add_data(symbol, historical, fundamental)
        for strategy in self.strategies:
            strategy.add_data(symbol, historical, fundamental)
    
    def _evaluate_strategy_performance(self, symbol: str, date: datetime) -> None:
        """Evaluate recent performance of each strategy and adjust weights"""
        historical, _ = self.get_data(symbol)
        
        # Get historical data points within evaluation window
        end_idx = next((i for i, p in enumerate(historical.data_points) 
                       if datetime.strptime(p.date, '%Y-%m-%d') > date), len(historical.data_points))
        start_idx = max(0, end_idx - self.evaluation_window)
        evaluation_points = historical.data_points[start_idx:end_idx]
        
        if len(evaluation_points) < 2:
            return
        
        # Calculate returns for each strategy's signals
        for strategy in self.strategies:
            signals = strategy.analyze(date)
            if symbol not in signals:
                continue
            
            returns = []
            position = "none"
            entry_price = 0
            
            for point in evaluation_points:
                point_date = datetime.strptime(point.date, '%Y-%m-%d')
                signal = strategy.analyze(point_date)[symbol]
                
                if signal['signal'] == "long" and position == "none":
                    position = "long"
                    entry_price = point.close
                elif signal['signal'] == "short" and position == "none":
                    position = "short"
                    entry_price = point.close
                elif signal['signal'] == "exit" and position != "none":
                    if position == "long":
                        returns.append((point.close / entry_price) - 1)
                    else:  # short
                        returns.append((entry_price / point.close) - 1)
                    position = "none"
            
            # Calculate strategy performance score
            if returns:
                avg_return = np.mean(returns)
                sharpe = np.mean(returns) / (np.std(returns) if len(returns) > 1 else 1)
                performance_score = (avg_return * sharpe) if sharpe > 0 else -abs(avg_return)
                self.performance_history[strategy.name].append(performance_score)
                
                # Keep only recent history
                if len(self.performance_history[strategy.name]) > self.evaluation_window:
                    self.performance_history[strategy.name].pop(0)
    
    def _update_weights(self) -> None:
        """Update strategy weights based on recent performance"""
        total_score = 0
        new_weights = {}
        
        # Calculate new weights based on exponential moving average of performance
        for strategy_name, history in self.performance_history.items():
            if not history:
                new_weights[strategy_name] = self.strategy_weights[strategy_name]
                continue
            
            # Calculate exponentially weighted performance score
            weights = np.exp([i/len(history) for i in range(len(history))])
            weighted_score = np.average(history, weights=weights)
            new_weights[strategy_name] = max(0.1, weighted_score)  # Minimum weight of 10%
            total_score += new_weights[strategy_name]
        
        # Normalize weights
        if total_score > 0:
            for strategy_name in new_weights:
                target_weight = new_weights[strategy_name] / total_score
                current_weight = self.strategy_weights[strategy_name]
                # Apply learning rate to smooth weight changes
                self.strategy_weights[strategy_name] = current_weight + \
                    self.learning_rate * (target_weight - current_weight)
    
    def generate_signals(self, data_points: List[HistoricalData], index: int) -> Tuple[SignalType, float, str]:
        """Generate trading signals by combining signals from all strategies"""
        if index < self.get_min_required_points():
            return "hold", 0.0, "Insufficient data"
        
        # Collect signals from all strategies
        strategy_signals = []
        for strategy in self.strategies:
            signal, confidence, details = strategy.generate_signals(data_points, index)
            if signal != "hold":
                strategy_signals.append({
                    "strategy_name": strategy.name,
                    "signal": signal,
                    "confidence": confidence * self.strategy_weights[strategy.name],  # Apply strategy weight
                    "details": details
                })
        
        if not strategy_signals:
            return "hold", 0.0, "No signals from component strategies"
        
        # Count weighted signals
        signal_counts = {"long": 0.0, "short": 0.0, "exit": 0.0}
        total_confidence = 0.0
        details = []
        
        for s in strategy_signals:
            signal_counts[s["signal"]] += s["confidence"]
            total_confidence += s["confidence"]
            details.append(f"{s['strategy_name']}: {s['details']}")
        
        # Determine ensemble signal
        if total_confidence == 0:
            return "hold", 0.0, "No confident signals"
        
        # Normalize signal counts
        for signal_type in signal_counts:
            signal_counts[signal_type] /= total_confidence
        
        # Find dominant signal
        dominant_signal = max(signal_counts.items(), key=lambda x: x[1])
        if dominant_signal[1] > self.min_confidence_threshold:
            confidence = dominant_signal[1]
            signal = dominant_signal[0]
            return signal, confidence, "\n".join(details)
        
        return "hold", 0.0, "No clear consensus"
    
    def analyze(self, date: Optional[datetime] = None) -> Dict[str, Dict[str, any]]:
        results = {}
        
        for symbol in self.symbols:
            historical, _ = self.get_data(symbol)
            
            # Collect and combine signals from all strategies
            strategy_signals = []
            for strategy in self.strategies:
                analysis = strategy.analyze(date)
                if symbol in analysis:
                    signal_data = analysis[symbol]
                    if signal_data["signal"] != "hold":  # Only include non-hold signals
                        strategy_signals.append({
                            "strategy_name": strategy.name,
                            "signal": signal_data["signal"],
                            "confidence": signal_data["confidence"] * self.strategy_weights[strategy.name],
                            "metrics": signal_data["metrics"],
                            "details": signal_data["details"]
                        })
            
            if not strategy_signals:
                results[symbol] = {
                    "signal": "hold",
                    "confidence": 0.0,
                    "metrics": {
                        f"{s.name}_weight": self.strategy_weights[s.name]
                        for s in self.strategies
                    },
                    "details": "No active signals from component strategies"
                }
                continue
            
            # Count weighted signals
            signal_counts = {"long": 0.0, "short": 0.0, "exit": 0.0}
            total_confidence = 0.0
            details = []
            
            for s in strategy_signals:
                signal_counts[s["signal"]] += s["confidence"]
                total_confidence += s["confidence"]
                details.append(f"{s['strategy_name']}: {s['details']}")
            
            # Determine ensemble signal
            if total_confidence == 0:
                results[symbol] = {
                    "signal": "hold",
                    "confidence": 0.0,
                    "metrics": {},
                    "details": "No confident signals"
                }
                continue
            
            # Normalize signal counts
            for signal_type in signal_counts:
                signal_counts[signal_type] /= total_confidence if total_confidence > 0 else 1.0
            
            # Find dominant signal
            dominant_signal = max(signal_counts.items(), key=lambda x: x[1])
            
            # Add weight information to metrics
            combined_metrics = {
                f"{s.name}_weight": self.strategy_weights[s.name]
                for s in self.strategies
            }
            
            # Add other metrics from strategies
            for s in strategy_signals:
                strategy_name = s['strategy_name']
                for metric_name, value in s['metrics'].items():
                    combined_metrics[f"{strategy_name}_{metric_name}"] = value
            
            results[symbol] = {
                "signal": dominant_signal[0] if dominant_signal[1] > self.min_confidence_threshold else "hold",
                "confidence": dominant_signal[1],
                "metrics": combined_metrics,
                "details": "\n".join(details)
            }
        
        return results
    
    def backtest(self, start_date: datetime, end_date: datetime) -> Dict[str, BacktestResult]:
        """Run strategy backtest"""
        results = {}
        
        # Get backtest results from all strategies
        strategy_results = {}
        for strategy in self.strategies:
            strategy_results[strategy.name] = strategy.backtest(start_date, end_date)
        
        # Process each symbol
        for symbol in self.symbols:
            all_trades: List[Trade] = []
            
            # Combine trades from all strategies
            for strategy_name, symbol_results in strategy_results.items():
                if symbol in symbol_results:
                    result = symbol_results[symbol]
                    all_trades.extend(result.trades)
            
            # Sort trades by date
            all_trades.sort(key=lambda x: x.entry_date)
            
            # Calculate combined returns
            total_return = sum(t.return_pct for t in all_trades)
            trading_days = (end_date - start_date).days
            annualized_return = ((1 + total_return) ** (365/trading_days)) - 1 if trading_days > 0 else 0
            avg_return = total_return / len(all_trades) if all_trades else 0
            
            results[symbol] = BacktestResult(
                trades=all_trades,
                strategy_returns=TradeMetrics(
                    total_return=total_return,
                    annualized_return=annualized_return,
                    total_trades_executed=len(all_trades),
                    avg_return_per_trade=avg_return
                ),
                buy_and_hold=self.calculate_buy_and_hold(symbol, start_date, end_date),
                total_trades=len(all_trades)
            )
        
        return results
    
    def _calculate_strategy_metrics(self, trades: List[Dict[str, any]]) -> Dict[str, any]:
        """Calculate strategy-specific metrics for backtest summary"""
        if not trades:
            return {}
        
        total_signals = len(trades)
        signal_counts = {
            "long": sum(1 for t in trades if t['signal'] == 'long'),
            "short": sum(1 for t in trades if t['signal'] == 'short'),
            "exit": sum(1 for t in trades if t['signal'] == 'exit')
        }
        
        # Calculate agreement metrics
        strategy_agreement = sum(
            1 for t in trades 
            if len([d for d in t['details'].split('\n') if 'Strategy' in d]) > 1
        ) / total_signals if total_signals > 0 else 0
        
        return {
            "long_signal_ratio": signal_counts['long'] / total_signals if total_signals > 0 else 0,
            "short_signal_ratio": signal_counts['short'] / total_signals if total_signals > 0 else 0,
            "exit_signal_ratio": signal_counts['exit'] / total_signals if total_signals > 0 else 0,
            "strategy_agreement_ratio": strategy_agreement
        } 