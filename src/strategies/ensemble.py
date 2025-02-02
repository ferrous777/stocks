from datetime import datetime, timedelta
from typing import Dict, List, Optional
from .strategy import Strategy, SignalType
import numpy as np
from market_data.data_types import BacktestResult, TradeMetrics, Trade

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
    
    def _combine_signals(self, signals: List[Dict[str, any]]) -> tuple[SignalType, float, List[str]]:
        """Combine multiple strategy signals using dynamic weights"""
        if not signals:
            return "hold", 0.0, []
        
        signal_weights = {
            "long": 0.0,
            "short": 0.0,
            "exit": 0.0,
            "hold": 0.0
        }
        
        total_weight = 0
        details = []
        
        # Combine signals using strategy weights
        for signal in signals:
            if signal['confidence'] >= self.min_confidence_threshold:
                strategy_weight = self.strategy_weights[signal['strategy_name']]
                weighted_confidence = signal['confidence'] * strategy_weight
                signal_weights[signal['signal']] += weighted_confidence
                total_weight += weighted_confidence
                details.append(
                    f"{signal['strategy_name']} ({strategy_weight:.2f}): "
                    f"{signal['signal']} ({signal['confidence']:.1%})"
                )
        
        if total_weight == 0:
            return "hold", 0.0, ["No significant signals"]
        
        # Normalize weights
        for signal_type in signal_weights:
            signal_weights[signal_type] /= total_weight
        
        # Determine final signal
        max_weight = max(signal_weights.values())
        final_signals = [s for s, w in signal_weights.items() if w == max_weight]
        
        if len(final_signals) > 1:
            if "exit" in final_signals:
                final_signal = "exit"
            else:
                final_signal = "hold"
        else:
            final_signal = final_signals[0]
        
        return final_signal, max_weight, details
    
    def analyze(self, date: Optional[datetime] = None) -> Dict[str, Dict[str, any]]:
        results = {}
        
        for symbol in self.symbols:
            # Update strategy weights based on recent performance
            self._evaluate_strategy_performance(symbol, date if date else datetime.now())
            self._update_weights()
            
            # Collect and combine signals as before
            strategy_signals = []
            for strategy in self.strategies:
                analysis = strategy.analyze(date)
                if symbol in analysis:
                    signal_data = analysis[symbol]
                    strategy_signals.append({
                        "strategy_name": strategy.name,
                        "signal": signal_data["signal"],
                        "confidence": signal_data["confidence"],
                        "metrics": signal_data["metrics"],
                        "details": signal_data["details"]
                    })
            
            signal, confidence, details = self._combine_signals(strategy_signals)
            
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
                "signal": signal,
                "confidence": confidence,
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
        if not trades:
            return {}
        
        total_signals = len(trades)
        signal_counts = {
            "long": sum(1 for t in trades if t['signal'] == 'long'),
            "short": sum(1 for t in trades if t['signal'] == 'short'),
            "exit": sum(1 for t in trades if t['signal'] == 'exit')
        }
        
        avg_confidence = sum(t['confidence'] for t in trades) / total_signals
        max_confidence = max(t['confidence'] for t in trades)
        
        # Calculate agreement metrics
        strategy_agreement = sum(
            1 for t in trades 
            if len([d for d in t['details'].split('\n') if 'Strategy' in d]) > 1
        ) / total_signals
        
        return {
            "long_signal_ratio": signal_counts['long'] / total_signals,
            "short_signal_ratio": signal_counts['short'] / total_signals,
            "exit_signal_ratio": signal_counts['exit'] / total_signals,
            "avg_confidence": avg_confidence,
            "max_confidence": max_confidence,
            "strategy_agreement_ratio": strategy_agreement
        } 