#!/usr/bin/env python3
"""
Prediction Performance Tracking System

This module tracks how well our trading predictions perform over time and generates
actionable buy/sell/short triggers based on prediction accuracy progression.
"""

import json
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Any, Tuple, Optional
import glob
from dataclasses import dataclass, asdict
from collections import defaultdict
import numpy as np

@dataclass
class PredictionRecord:
    """A single prediction record"""
    symbol: str
    date_issued: str
    action: str  # BUY, SELL, EXIT
    type: str   # LONG, SHORT, CLOSE
    confidence: float
    entry_price: float
    stop_loss: float
    take_profit: float
    position_size: int
    strategies: List[str]
    details: str
    
    # Performance tracking (filled later)
    outcome: Optional[str] = None  # 'success', 'stop_loss', 'target_hit', 'timeout'
    actual_exit_price: Optional[float] = None
    actual_exit_date: Optional[str] = None
    pnl: Optional[float] = None
    return_pct: Optional[float] = None
    days_held: Optional[int] = None

@dataclass
class StrategyPerformance:
    """Performance metrics for a strategy"""
    strategy_name: str
    total_predictions: int
    successful_predictions: int
    failed_predictions: int
    accuracy_rate: float
    avg_return: float
    avg_days_held: float
    win_rate: float
    profit_factor: float
    sharpe_ratio: float
    max_drawdown: float
    
@dataclass
class TradingTrigger:
    """A trading trigger based on prediction performance"""
    symbol: str
    action: str  # BUY, SELL, SHORT, EXIT
    confidence: float
    reasoning: str
    strategy_backing: List[str]
    entry_price: float
    stop_loss: float
    take_profit: float
    position_size: int
    risk_level: str  # LOW, MEDIUM, HIGH
    time_horizon: str  # SHORT, MEDIUM, LONG
    
class PredictionTracker:
    """Main prediction performance tracking system"""
    
    def __init__(self, db_path: str = "data/prediction_tracker.db"):
        self.db_path = db_path
        self.results_dir = "results"
        self.cache_dir = "cache"
        self.setup_database()
        
    def setup_database(self):
        """Initialize the prediction tracking database"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS predictions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    date_issued TEXT NOT NULL,
                    action TEXT NOT NULL,
                    type TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    entry_price REAL NOT NULL,
                    stop_loss REAL NOT NULL,
                    take_profit REAL NOT NULL,
                    position_size INTEGER NOT NULL,
                    strategies TEXT NOT NULL,
                    details TEXT NOT NULL,
                    outcome TEXT,
                    actual_exit_price REAL,
                    actual_exit_date TEXT,
                    pnl REAL,
                    return_pct REAL,
                    days_held INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS strategy_performance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy_name TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    date_calculated TEXT NOT NULL,
                    total_predictions INTEGER NOT NULL,
                    successful_predictions INTEGER NOT NULL,
                    failed_predictions INTEGER NOT NULL,
                    accuracy_rate REAL NOT NULL,
                    avg_return REAL NOT NULL,
                    avg_days_held REAL NOT NULL,
                    win_rate REAL NOT NULL,
                    profit_factor REAL NOT NULL,
                    sharpe_ratio REAL NOT NULL,
                    max_drawdown REAL NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trading_triggers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    action TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    reasoning TEXT NOT NULL,
                    strategy_backing TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    stop_loss REAL NOT NULL,
                    take_profit REAL NOT NULL,
                    position_size INTEGER NOT NULL,
                    risk_level TEXT NOT NULL,
                    time_horizon TEXT NOT NULL,
                    date_created TEXT NOT NULL,
                    is_active BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create indexes for better performance
            conn.execute("CREATE INDEX IF NOT EXISTS idx_predictions_symbol_date ON predictions(symbol, date_issued)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_strategy_performance_date ON strategy_performance(date_calculated)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_triggers_active ON trading_triggers(is_active, date_created)")
            
    def import_historical_predictions(self) -> int:
        """Import all existing recommendation files"""
        print("🔄 Importing historical predictions...")
        imported_count = 0
        
        # Find all recommendation files
        recommendation_files = glob.glob(f"{self.results_dir}/*_recommendations_*.json")
        
        for file_path in recommendation_files:
            try:
                with open(file_path, 'r') as f:
                    data = json.load(f)
                
                # Extract info from filename
                filename = os.path.basename(file_path)
                parts = filename.replace('.json', '').split('_')
                symbol = parts[0]
                date_str = parts[2]
                
                # Convert date format
                date_issued = datetime.strptime(date_str, '%Y%m%d').strftime('%Y-%m-%d')
                
                # Create prediction record
                rec = data.get('recommendations', {})
                if not rec:
                    continue
                    
                prediction = PredictionRecord(
                    symbol=symbol,
                    date_issued=date_issued,
                    action=rec.get('action', ''),
                    type=rec.get('type', ''),
                    confidence=rec.get('confidence', 0.0),
                    entry_price=rec.get('entry_price', 0.0),
                    stop_loss=rec.get('stop_loss', 0.0),
                    take_profit=rec.get('take_profit', 0.0),
                    position_size=rec.get('position_size', 0),
                    strategies=rec.get('supporting_strategies', []),
                    details=rec.get('details', '')
                )
                
                self.store_prediction(prediction)
                imported_count += 1
                
            except Exception as e:
                print(f"⚠️  Error importing {file_path}: {e}")
                continue
                
        print(f"✅ Imported {imported_count} historical predictions")
        return imported_count
        
    def store_prediction(self, prediction: PredictionRecord):
        """Store a prediction in the database"""
        with sqlite3.connect(self.db_path) as conn:
            # Check if already exists
            cursor = conn.execute("""
                SELECT id FROM predictions 
                WHERE symbol = ? AND date_issued = ? AND action = ?
            """, (prediction.symbol, prediction.date_issued, prediction.action))
            
            if cursor.fetchone():
                return  # Already exists
                
            conn.execute("""
                INSERT INTO predictions (
                    symbol, date_issued, action, type, confidence, entry_price,
                    stop_loss, take_profit, position_size, strategies, details,
                    outcome, actual_exit_price, actual_exit_date, pnl, return_pct, days_held
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                prediction.symbol, prediction.date_issued, prediction.action, prediction.type,
                prediction.confidence, prediction.entry_price, prediction.stop_loss,
                prediction.take_profit, prediction.position_size,
                json.dumps(prediction.strategies), prediction.details,
                prediction.outcome, prediction.actual_exit_price, prediction.actual_exit_date,
                prediction.pnl, prediction.return_pct, prediction.days_held
            ))
            
    def get_current_price(self, symbol: str) -> Optional[float]:
        """Get the current price for a symbol from historical data cache"""
        cache_file = f"{self.cache_dir}/{symbol}_historical.json"
        if not os.path.exists(cache_file):
            return None
            
        try:
            with open(cache_file, 'r') as f:
                data = json.load(f)
            
            if data and len(data) > 0:
                return float(data[-1].get('close', 0))
        except:
            pass
            
        return None
        
    def update_prediction_outcomes(self) -> int:
        """Update outcomes for predictions that can be evaluated"""
        print("🔄 Updating prediction outcomes...")
        updated_count = 0
        
        with sqlite3.connect(self.db_path) as conn:
            # Get predictions without outcomes
            cursor = conn.execute("""
                SELECT id, symbol, date_issued, action, type, entry_price, stop_loss, take_profit
                FROM predictions 
                WHERE outcome IS NULL AND date_issued <= date('now', '-1 day')
                ORDER BY date_issued
            """)
            
            predictions = cursor.fetchall()
            
            for pred in predictions:
                pred_id, symbol, date_issued, action, pred_type, entry_price, stop_loss, take_profit = pred
                
                # Get historical price data for evaluation
                outcome = self.evaluate_prediction_outcome(
                    symbol, date_issued, action, pred_type, entry_price, stop_loss, take_profit
                )
                
                if outcome:
                    conn.execute("""
                        UPDATE predictions 
                        SET outcome = ?, actual_exit_price = ?, actual_exit_date = ?, 
                            pnl = ?, return_pct = ?, days_held = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                    """, (
                        outcome['outcome'], outcome['exit_price'], outcome['exit_date'],
                        outcome['pnl'], outcome['return_pct'], outcome['days_held'], pred_id
                    ))
                    updated_count += 1
                    
        print(f"✅ Updated {updated_count} prediction outcomes")
        return updated_count
        
    def evaluate_prediction_outcome(self, symbol: str, date_issued: str, action: str, 
                                  pred_type: str, entry_price: float, stop_loss: float, 
                                  take_profit: float) -> Optional[Dict]:
        """Evaluate if a prediction was successful based on historical data"""
        cache_file = f"{self.cache_dir}/{symbol}_historical.json"
        if not os.path.exists(cache_file):
            return None
            
        try:
            with open(cache_file, 'r') as f:
                data = json.load(f)
                # Extract the data_points array from the nested structure
                if 'data_points' in data:
                    data_points = data['data_points']
                else:
                    # Fallback for direct array format
                    data_points = data
        except:
            return None
            
        # Find prices after the prediction date
        start_date = datetime.strptime(date_issued, '%Y-%m-%d')
        max_days = 30  # Maximum holding period
        
        for i, day_data in enumerate(data_points):
            day_date = datetime.strptime(day_data['date'], '%Y-%m-%d')
            
            if day_date <= start_date:
                continue
                
            days_held = (day_date - start_date).days
            if days_held > max_days:
                # Timeout - evaluate at current price
                exit_price = float(day_data['close'])
                return self.calculate_outcome(
                    action, pred_type, entry_price, exit_price, stop_loss, take_profit,
                    days_held, day_date.strftime('%Y-%m-%d'), 'timeout'
                )
                
            high = float(day_data['high'])
            low = float(day_data['low'])
            close = float(day_data['close'])
            
            # Check for stop loss or take profit hits
            if pred_type == "LONG":
                if low <= stop_loss:
                    # Stop loss hit
                    return self.calculate_outcome(
                        action, pred_type, entry_price, stop_loss, stop_loss, take_profit,
                        days_held, day_date.strftime('%Y-%m-%d'), 'stop_loss'
                    )
                elif high >= take_profit:
                    # Take profit hit
                    return self.calculate_outcome(
                        action, pred_type, entry_price, take_profit, stop_loss, take_profit,
                        days_held, day_date.strftime('%Y-%m-%d'), 'target_hit'
                    )
                    
            elif pred_type == "SHORT":
                if high >= stop_loss:
                    # Stop loss hit
                    return self.calculate_outcome(
                        action, pred_type, entry_price, stop_loss, stop_loss, take_profit,
                        days_held, day_date.strftime('%Y-%m-%d'), 'stop_loss'
                    )
                elif low <= take_profit:
                    # Take profit hit
                    return self.calculate_outcome(
                        action, pred_type, entry_price, take_profit, stop_loss, take_profit,
                        days_held, day_date.strftime('%Y-%m-%d'), 'target_hit'
                    )
                    
        return None
        
    def calculate_outcome(self, action: str, pred_type: str, entry_price: float, 
                         exit_price: float, stop_loss: float, take_profit: float,
                         days_held: int, exit_date: str, outcome_type: str) -> Dict:
        """Calculate the outcome metrics for a prediction"""
        if pred_type == "LONG":
            pnl = exit_price - entry_price
            return_pct = (exit_price - entry_price) / entry_price
        elif pred_type == "SHORT":
            pnl = entry_price - exit_price
            return_pct = (entry_price - exit_price) / entry_price
        else:
            pnl = 0
            return_pct = 0
            
        # Determine if successful
        if outcome_type == 'target_hit':
            outcome = 'success'
        elif outcome_type == 'stop_loss':
            outcome = 'failure'
        else:  # timeout
            outcome = 'success' if return_pct > 0 else 'failure'
            
        return {
            'outcome': outcome,
            'exit_price': exit_price,
            'exit_date': exit_date,
            'pnl': pnl,
            'return_pct': return_pct,
            'days_held': days_held
        }
        
    def calculate_strategy_performance(self) -> Dict[str, StrategyPerformance]:
        """Calculate performance metrics for each strategy"""
        print("📊 Calculating strategy performance...")
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT strategies, outcome, return_pct, days_held, pnl
                FROM predictions 
                WHERE outcome IS NOT NULL
            """)
            
            results = cursor.fetchall()
            
        # Group by strategy
        strategy_data = defaultdict(list)
        
        for strategies_json, outcome, return_pct, days_held, pnl in results:
            try:
                strategies = json.loads(strategies_json)
                for strategy in strategies:
                    strategy_data[strategy].append({
                        'outcome': outcome,
                        'return_pct': return_pct or 0,
                        'days_held': days_held or 0,
                        'pnl': pnl or 0
                    })
            except:
                continue
                
        # Calculate metrics for each strategy
        performance = {}
        
        for strategy_name, data in strategy_data.items():
            total = len(data)
            successful = len([d for d in data if d['outcome'] == 'success'])
            failed = total - successful
            
            returns = [d['return_pct'] for d in data]
            days = [d['days_held'] for d in data if d['days_held'] > 0]
            
            accuracy_rate = successful / total if total > 0 else 0
            avg_return = np.mean(returns) if returns else 0
            avg_days_held = np.mean(days) if days else 0
            
            # Calculate additional metrics
            win_rate = len([r for r in returns if r > 0]) / total if total > 0 else 0
            
            # Profit factor (gross profit / gross loss)
            profits = [r for r in returns if r > 0]
            losses = [abs(r) for r in returns if r < 0]
            profit_factor = sum(profits) / sum(losses) if losses else float('inf')
            
            # Simple Sharpe ratio approximation
            if len(returns) > 1:
                sharpe_ratio = np.mean(returns) / np.std(returns) if np.std(returns) > 0 else 0
            else:
                sharpe_ratio = 0
                
            # Max drawdown (simplified)
            cumulative_returns = np.cumsum(returns)
            max_drawdown = 0
            peak = 0
            for cum_return in cumulative_returns:
                if cum_return > peak:
                    peak = cum_return
                drawdown = peak - cum_return
                if drawdown > max_drawdown:
                    max_drawdown = drawdown
                    
            performance[strategy_name] = StrategyPerformance(
                strategy_name=strategy_name,
                total_predictions=total,
                successful_predictions=successful,
                failed_predictions=failed,
                accuracy_rate=accuracy_rate,
                avg_return=avg_return,
                avg_days_held=avg_days_held,
                win_rate=win_rate,
                profit_factor=profit_factor,
                sharpe_ratio=sharpe_ratio,
                max_drawdown=max_drawdown
            )
            
        return performance
        
    def generate_trading_triggers(self) -> List[TradingTrigger]:
        """Generate actionable trading triggers based on prediction performance"""
        print("🎯 Generating trading triggers...")
        
        # Get strategy performance
        strategy_performance = self.calculate_strategy_performance()
        
        # Get recent predictions for trend analysis
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT symbol, action, confidence, strategies, date_issued, entry_price, stop_loss, take_profit
                FROM predictions 
                WHERE date_issued >= date('now', '-30 days')
                ORDER BY symbol, date_issued DESC
            """)
            recent_predictions = cursor.fetchall()
            
        # Group by symbol for analysis
        symbol_data = defaultdict(list)
        for pred in recent_predictions:
            symbol_data[pred[0]].append(pred)
            
        triggers = []
        
        for symbol, predictions in symbol_data.items():
            if len(predictions) < 2:
                continue
                
            # Analyze prediction progression
            trigger = self.analyze_prediction_progression(symbol, predictions, strategy_performance)
            if trigger:
                triggers.append(trigger)
                
        # Store triggers in database
        self.store_triggers(triggers)
        
        return triggers
        
    def analyze_prediction_progression(self, symbol: str, predictions: List, 
                                     strategy_performance: Dict[str, StrategyPerformance]) -> Optional[TradingTrigger]:
        """Analyze how predictions for a symbol are progressing"""
        
        current_price = self.get_current_price(symbol)
        if not current_price:
            return None
            
        # Get the most recent prediction
        latest = predictions[0]
        latest_action = latest[1]
        latest_confidence = latest[2]
        latest_strategies = json.loads(latest[3])
        latest_entry = latest[5]
        latest_stop = latest[6]
        latest_profit = latest[7]
        
        # Calculate strategy backing strength
        backing_strength = 0
        reliable_strategies = []
        
        for strategy in latest_strategies:
            if strategy in strategy_performance:
                perf = strategy_performance[strategy]
                if perf.accuracy_rate > 0.6 and perf.total_predictions >= 5:
                    backing_strength += perf.accuracy_rate * perf.win_rate
                    reliable_strategies.append(strategy)
                    
        # Analyze consistency in recent predictions
        recent_actions = [p[1] for p in predictions[:5]]  # Last 5 predictions
        action_consistency = recent_actions.count(latest_action) / len(recent_actions)
        
        # Generate trigger if conditions are met
        trigger_confidence = (latest_confidence + backing_strength + action_consistency) / 3
        
        if trigger_confidence >= 0.7 and reliable_strategies:
            # Calculate position sizing based on confidence and risk
            base_position = 1000  # Base position in dollars
            risk_multiplier = min(trigger_confidence * 1.5, 2.0)
            position_value = base_position * risk_multiplier
            position_size = int(position_value / current_price)
            
            # Determine risk level
            if trigger_confidence >= 0.85:
                risk_level = "LOW"
            elif trigger_confidence >= 0.75:
                risk_level = "MEDIUM"
            else:
                risk_level = "HIGH"
                
            # Time horizon based on strategy performance
            avg_days = np.mean([strategy_performance[s].avg_days_held for s in reliable_strategies])
            if avg_days <= 5:
                time_horizon = "SHORT"
            elif avg_days <= 15:
                time_horizon = "MEDIUM"
            else:
                time_horizon = "LONG"
                
            reasoning = f"Consistent {latest_action} signal with {action_consistency:.1%} consistency. " \
                       f"Backed by {len(reliable_strategies)} reliable strategies with avg accuracy: " \
                       f"{np.mean([strategy_performance[s].accuracy_rate for s in reliable_strategies]):.1%}"
            
            return TradingTrigger(
                symbol=symbol,
                action=latest_action,
                confidence=trigger_confidence,
                reasoning=reasoning,
                strategy_backing=reliable_strategies,
                entry_price=current_price,
                stop_loss=latest_stop,
                take_profit=latest_profit,
                position_size=position_size,
                risk_level=risk_level,
                time_horizon=time_horizon
            )
            
        return None
        
    def store_triggers(self, triggers: List[TradingTrigger]):
        """Store trading triggers in the database"""
        today = datetime.now().strftime('%Y-%m-%d')
        
        with sqlite3.connect(self.db_path) as conn:
            # Deactivate old triggers
            conn.execute("UPDATE trading_triggers SET is_active = 0 WHERE date_created < ?", (today,))
            
            # Insert new triggers
            for trigger in triggers:
                conn.execute("""
                    INSERT INTO trading_triggers (
                        symbol, action, confidence, reasoning, strategy_backing,
                        entry_price, stop_loss, take_profit, position_size,
                        risk_level, time_horizon, date_created
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    trigger.symbol, trigger.action, trigger.confidence, trigger.reasoning,
                    json.dumps(trigger.strategy_backing), trigger.entry_price,
                    trigger.stop_loss, trigger.take_profit, trigger.position_size,
                    trigger.risk_level, trigger.time_horizon, today
                ))
                
    def generate_performance_report(self) -> str:
        """Generate a comprehensive performance report"""
        strategy_performance = self.calculate_strategy_performance()
        triggers = self.get_active_triggers()
        
        report = []
        report.append("# 📈 PREDICTION PERFORMANCE REPORT")
        report.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append("")
        
        # Strategy Performance Summary
        report.append("## 🎯 STRATEGY PERFORMANCE")
        report.append("")
        
        for strategy_name, perf in sorted(strategy_performance.items(), 
                                        key=lambda x: x[1].accuracy_rate, reverse=True):
            report.append(f"### {strategy_name}")
            report.append(f"- **Accuracy Rate:** {perf.accuracy_rate:.1%}")
            report.append(f"- **Win Rate:** {perf.win_rate:.1%}")
            report.append(f"- **Avg Return:** {perf.avg_return:.2%}")
            report.append(f"- **Total Predictions:** {perf.total_predictions}")
            report.append(f"- **Profit Factor:** {perf.profit_factor:.2f}")
            report.append(f"- **Sharpe Ratio:** {perf.sharpe_ratio:.2f}")
            report.append(f"- **Avg Days Held:** {perf.avg_days_held:.1f}")
            report.append("")
            
        # Active Trading Triggers
        report.append("## 🚨 ACTIVE TRADING TRIGGERS")
        report.append("")
        
        if triggers:
            for trigger in triggers:
                report.append(f"### {trigger.symbol} - {trigger.action}")
                report.append(f"- **Confidence:** {trigger.confidence:.1%}")
                report.append(f"- **Risk Level:** {trigger.risk_level}")
                report.append(f"- **Position Size:** {trigger.position_size} shares")
                report.append(f"- **Entry Price:** ${trigger.entry_price:.2f}")
                report.append(f"- **Stop Loss:** ${trigger.stop_loss:.2f}")
                report.append(f"- **Take Profit:** ${trigger.take_profit:.2f}")
                report.append(f"- **Time Horizon:** {trigger.time_horizon}")
                report.append(f"- **Reasoning:** {trigger.reasoning}")
                report.append("")
        else:
            report.append("*No active trading triggers at this time.*")
            report.append("")
            
        return "\n".join(report)
        
    def get_active_triggers(self) -> List[TradingTrigger]:
        """Get all active trading triggers"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT symbol, action, confidence, reasoning, strategy_backing,
                       entry_price, stop_loss, take_profit, position_size,
                       risk_level, time_horizon
                FROM trading_triggers 
                WHERE is_active = 1
                ORDER BY confidence DESC
            """)
            
            triggers = []
            for row in cursor.fetchall():
                triggers.append(TradingTrigger(
                    symbol=row[0],
                    action=row[1],
                    confidence=row[2],
                    reasoning=row[3],
                    strategy_backing=json.loads(row[4]),
                    entry_price=row[5],
                    stop_loss=row[6],
                    take_profit=row[7],
                    position_size=row[8],
                    risk_level=row[9],
                    time_horizon=row[10]
                ))
                
        return triggers
        
    def run_full_analysis(self) -> str:
        """Run the complete prediction tracking analysis"""
        print("🚀 Starting Prediction Performance Analysis...")
        
        # Import historical data
        self.import_historical_predictions()
        
        # Update prediction outcomes
        self.update_prediction_outcomes()
        
        # Generate trading triggers
        triggers = self.generate_trading_triggers()
        
        # Generate report
        report = self.generate_performance_report()
        
        print(f"✅ Analysis complete! Generated {len(triggers)} trading triggers")
        return report

def main():
    """Main function for standalone execution"""
    tracker = PredictionTracker()
    report = tracker.run_full_analysis()
    
    # Save report
    report_path = f"reports/prediction_performance_{datetime.now().strftime('%Y%m%d')}.md"
    os.makedirs("reports", exist_ok=True)
    
    with open(report_path, 'w') as f:
        f.write(report)
        
    print(f"📄 Report saved to: {report_path}")
    print("\n" + "="*50)
    print(report)

if __name__ == "__main__":
    main()
