"""
Daily Scheduler for automated market data collection and analysis

This module provides a comprehensive daily scheduling system that:
1. Fetches latest market data for configured symbols
2. Runs all strategies and generates signals
3. Calculates performance metrics
4. Stores results in the database
5. Generates daily summary reports
"""
import sys
import os
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import json

# Add src to path
sys.path.append(os.path.dirname(__file__))

from config.config_manager import ConfigManager
from storage.timeseries_db import TimeSeriesDB
from storage.models import DailySnapshot
from analysis.aggregation import DataAggregator
from market_calendar.market_calendar import MarketCalendar, MarketType, is_trading_day
from market_data.market_data import MarketData

# Ensure logs directory exists
os.makedirs('logs', exist_ok=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/daily_scheduler.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class MarketDataCollector:
    """Handles market data collection from external APIs"""
    
    def __init__(self):
        self.db = TimeSeriesDB()
        self.market_data = MarketData()
    
    def fetch_latest_data(self, symbol: str, date: Optional[datetime] = None) -> Optional[DailySnapshot]:
        """
        Fetch latest market data for a symbol using Yahoo Finance API
        """
        if date is None:
            date = datetime.now()
        
        logger.info(f"Fetching data for {symbol} on {date.date()}")
        
        # Check if we already have data for this date
        date_str = date.strftime('%Y-%m-%d')
        existing_data = self.db.get_daily_snapshot(symbol, date_str)
        if existing_data:
            logger.info(f"Data already exists for {symbol} on {date.date()}")
            return existing_data
        
        try:
            # Use the real market data API
            # Fetch data for a 5-day window to ensure we get the latest trading day
            end_date = date
            start_date = date - timedelta(days=5)
            
            historical_data = self.market_data.get_batch_data([symbol], start_date, end_date, force_refresh=True)
            
            if symbol in historical_data and historical_data[symbol] and historical_data[symbol].data_points:
                # Get the most recent data point
                latest_point = historical_data[symbol].data_points[-1]
                
                # Convert to DailySnapshot
                daily_snapshot = DailySnapshot(
                    symbol=symbol,
                    date=latest_point.date,
                    open=latest_point.open,
                    high=latest_point.high,
                    low=latest_point.low,
                    close=latest_point.close,
                    volume=latest_point.volume,
                    adjusted_close=latest_point.close,  # Using close as adjusted_close for now
                    strategy_signals={}
                )
                
                # Store in database
                self.db.save_daily_snapshot(daily_snapshot)
                logger.info(f"Successfully fetched and stored data for {symbol}")
                return daily_snapshot
            else:
                logger.warning(f"No data returned for {symbol}")
                return None
                
        except Exception as e:
            logger.error(f"Failed to fetch data for {symbol}: {e}")
            return None
    
    def fetch_all_symbols(self, symbols: List[str], date: Optional[datetime] = None) -> Dict[str, Optional[DailySnapshot]]:
        """Fetch data for all symbols"""
        results = {}
        
        for symbol in symbols:
            try:
                data = self.fetch_latest_data(symbol, date)
                results[symbol] = data
            except Exception as e:
                logger.error(f"Failed to fetch data for {symbol}: {e}")
                results[symbol] = None
        
        return results


class StrategyRunner:
    """Runs trading strategies and generates signals"""
    
    def __init__(self):
        self.db = TimeSeriesDB()
    
    def run_all_strategies(self, symbol: str, date: datetime) -> Dict[str, any]:
        """
        Run all configured strategies for a symbol
        Returns strategy signals and confidence scores
        """
        logger.info(f"Running strategies for {symbol} on {date.date()}")
        
        # Get recent historical data for strategy calculations
        end_date = date.strftime('%Y-%m-%d')
        start_date = (date - timedelta(days=100)).strftime('%Y-%m-%d')
        historical_data = self.db.get_symbol_data(symbol, start_date, end_date)
        
        if not historical_data or len(historical_data) < 20:
            logger.warning(f"Insufficient historical data for {symbol}")
            return {}
        
        # Sort by date
        historical_data.sort(key=lambda x: x.date)
        
        strategies_results = {}
        
        # Example strategies - replace with real implementations
        strategies_results.update(self._run_momentum_strategy(historical_data))
        strategies_results.update(self._run_mean_reversion_strategy(historical_data))
        strategies_results.update(self._run_breakout_strategy(historical_data))
        
        return strategies_results
    
    def _run_momentum_strategy(self, data: List[DailySnapshot]) -> Dict[str, any]:
        """Momentum-based strategy"""
        if len(data) < 20:
            return {}
        
        # Simple momentum: compare recent price to 20-day average
        recent_prices = [d.close for d in data[-20:]]
        avg_price = sum(recent_prices) / len(recent_prices)
        current_price = data[-1].close
        
        momentum_score = (current_price - avg_price) / avg_price
        
        signal = 'BUY' if momentum_score > 0.02 else 'SELL' if momentum_score < -0.02 else 'HOLD'
        confidence = min(abs(momentum_score) * 10, 1.0)  # Scale to 0-1
        
        return {
            'momentum_strategy': {
                'signal': signal,
                'confidence': confidence,
                'momentum_score': momentum_score,
                'avg_price': avg_price
            }
        }
    
    def _run_mean_reversion_strategy(self, data: List[DailySnapshot]) -> Dict[str, any]:
        """Mean reversion strategy"""
        if len(data) < 50:
            return {}
        
        # Calculate RSI-like indicator
        recent_data = data[-20:]
        price_changes = []
        
        for i in range(1, len(recent_data)):
            change = recent_data[i].close - recent_data[i-1].close
            price_changes.append(change)
        
        if not price_changes:
            return {}
        
        avg_change = sum(price_changes) / len(price_changes)
        
        # Simple mean reversion signal
        if avg_change > 0.01:  # Overbought
            signal = 'SELL'
            confidence = min(avg_change * 100, 1.0)
        elif avg_change < -0.01:  # Oversold
            signal = 'BUY'  
            confidence = min(abs(avg_change) * 100, 1.0)
        else:
            signal = 'HOLD'
            confidence = 0.1
        
        return {
            'mean_reversion_strategy': {
                'signal': signal,
                'confidence': confidence,
                'avg_change': avg_change
            }
        }
    
    def _run_breakout_strategy(self, data: List[DailySnapshot]) -> Dict[str, any]:
        """Breakout strategy based on recent highs/lows"""
        if len(data) < 20:
            return {}
        
        recent_data = data[-20:]
        current_price = data[-1].close
        
        recent_high = max(d.high for d in recent_data[:-1])  # Exclude today
        recent_low = min(d.low for d in recent_data[:-1])
        
        # Breakout signals
        if current_price > recent_high * 1.01:  # Break above resistance
            signal = 'BUY'
            confidence = 0.8
        elif current_price < recent_low * 0.99:  # Break below support
            signal = 'SELL'
            confidence = 0.8
        else:
            signal = 'HOLD'
            confidence = 0.1
        
        return {
            'breakout_strategy': {
                'signal': signal,
                'confidence': confidence,
                'recent_high': recent_high,
                'recent_low': recent_low
            }
        }


class PerformanceCalculator:
    """Calculates performance metrics and updates database"""
    
    def __init__(self):
        self.aggregator = DataAggregator()
    
    def calculate_daily_metrics(self, symbol: str, date: datetime) -> Dict[str, any]:
        """Calculate performance metrics for a symbol on a given date"""
        logger.info(f"Calculating performance metrics for {symbol} on {date.date()}")
        
        metrics = {}
        
        # Calculate rolling metrics for different windows
        for window in [7, 30, 90]:
            rolling_metrics = self.aggregator.calculate_rolling_metrics(symbol, date, window)
            if rolling_metrics:
                metrics[f'{window}d_return'] = rolling_metrics.total_return
                metrics[f'{window}d_volatility'] = rolling_metrics.volatility
                metrics[f'{window}d_sharpe'] = rolling_metrics.sharpe_ratio
                metrics[f'{window}d_trend'] = rolling_metrics.price_trend
        
        # Get market baselines for comparison
        baselines = self.aggregator.get_comparison_baselines(date)
        metrics['market_baselines'] = baselines
        
        return metrics


class DailyReportGenerator:
    """Generates daily summary reports"""
    
    def __init__(self):
        self.config_manager = ConfigManager()
        self.db = TimeSeriesDB()
    
    def generate_daily_summary(self, date: datetime, results: Dict) -> str:
        """Generate a daily summary report"""
        logger.info(f"Generating daily summary report for {date.date()}")
        
        config = self.config_manager.get_config()
        symbols = [s.symbol for s in config.symbols if s.enabled]
        
        report_lines = []
        report_lines.append(f"# Daily Market Analysis Report")
        report_lines.append(f"**Date:** {date.strftime('%Y-%m-%d')}")
        report_lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report_lines.append("")
        
        # Summary statistics
        successful_fetches = sum(1 for symbol in symbols if results.get('data', {}).get(symbol) is not None)
        report_lines.append(f"## Summary")
        report_lines.append(f"- **Symbols Processed:** {len(symbols)}")
        report_lines.append(f"- **Successful Data Fetches:** {successful_fetches}")
        report_lines.append(f"- **Data Success Rate:** {successful_fetches/len(symbols)*100:.1f}%")
        report_lines.append("")
        
        # Strategy signals summary
        if 'strategies' in results:
            report_lines.append(f"## Strategy Signals")
            
            signal_counts = {'BUY': 0, 'SELL': 0, 'HOLD': 0}
            
            for symbol, strategies in results['strategies'].items():
                for strategy_name, strategy_result in strategies.items():
                    signal = strategy_result.get('signal', 'HOLD')
                    signal_counts[signal] += 1
            
            report_lines.append(f"- **BUY Signals:** {signal_counts['BUY']}")
            report_lines.append(f"- **SELL Signals:** {signal_counts['SELL']}")
            report_lines.append(f"- **HOLD Signals:** {signal_counts['HOLD']}")
            report_lines.append("")
            
            # Top signals by confidence
            all_signals = []
            for symbol, strategies in results['strategies'].items():
                for strategy_name, strategy_result in strategies.items():
                    if strategy_result.get('signal') in ['BUY', 'SELL']:
                        all_signals.append({
                            'symbol': symbol,
                            'strategy': strategy_name,
                            'signal': strategy_result.get('signal'),
                            'confidence': strategy_result.get('confidence', 0)
                        })
            
            # Sort by confidence
            all_signals.sort(key=lambda x: x['confidence'], reverse=True)
            
            if all_signals:
                report_lines.append(f"### Top Signals by Confidence")
                for signal in all_signals[:10]:  # Top 10
                    report_lines.append(f"- **{signal['symbol']}** ({signal['strategy']}): "
                                      f"{signal['signal']} (Confidence: {signal['confidence']:.2f})")
                report_lines.append("")
        
        # Performance summary
        if 'performance' in results:
            report_lines.append(f"## Performance Overview")
            
            # Best/worst performers
            returns_30d = {}
            for symbol, metrics in results['performance'].items():
                if '30d_return' in metrics:
                    returns_30d[symbol] = metrics['30d_return']
            
            if returns_30d:
                sorted_returns = sorted(returns_30d.items(), key=lambda x: x[1], reverse=True)
                
                report_lines.append(f"### 30-Day Returns")
                report_lines.append(f"**Best Performers:**")
                for symbol, return_val in sorted_returns[:5]:
                    report_lines.append(f"- {symbol}: {return_val:.2%}")
                
                report_lines.append(f"**Worst Performers:**")
                for symbol, return_val in sorted_returns[-5:]:
                    report_lines.append(f"- {symbol}: {return_val:.2%}")
                report_lines.append("")
        
        report_content = "\n".join(report_lines)
        
        # Save report to file
        os.makedirs('reports', exist_ok=True)
        report_filename = f"reports/daily_report_{date.strftime('%Y%m%d')}.md"
        
        with open(report_filename, 'w') as f:
            f.write(report_content)
        
        logger.info(f"Daily report saved to {report_filename}")
        return report_content


class DailyScheduler:
    """Main scheduler class that orchestrates daily data collection and analysis"""
    
    def __init__(self):
        self.config_manager = ConfigManager()
        self.data_collector = MarketDataCollector()
        self.strategy_runner = StrategyRunner()
        self.performance_calculator = PerformanceCalculator()
        self.report_generator = DailyReportGenerator()
        
        # Ensure logs directory exists
        os.makedirs('logs', exist_ok=True)
    
    def run_daily_workflow(self, date: Optional[datetime] = None) -> Dict:
        """Run the complete daily workflow"""
        if date is None:
            date = datetime.now()
        
        logger.info(f"Starting daily workflow for {date.date()}")
        
        # Get enabled symbols from configuration
        config = self.config_manager.get_config()
        symbols = [s.symbol for s in config.symbols if s.enabled]
        
        logger.info(f"Processing {len(symbols)} symbols: {', '.join(symbols)}")
        
        results = {
            'date': date,
            'data': {},
            'strategies': {},
            'performance': {},
            'errors': []
        }
        
        try:
            # Step 1: Fetch latest market data
            logger.info("Step 1: Fetching market data")
            data_results = self.data_collector.fetch_all_symbols(symbols, date)
            results['data'] = data_results
            
            # Step 2: Run strategies for symbols with data
            logger.info("Step 2: Running trading strategies")
            for symbol in symbols:
                if data_results.get(symbol) is not None:
                    try:
                        strategy_results = self.strategy_runner.run_all_strategies(symbol, date)
                        results['strategies'][symbol] = strategy_results
                    except Exception as e:
                        logger.error(f"Strategy execution failed for {symbol}: {e}")
                        results['errors'].append(f"Strategy execution failed for {symbol}: {e}")
            
            # Step 3: Calculate performance metrics
            logger.info("Step 3: Calculating performance metrics")
            for symbol in symbols:
                try:
                    performance_metrics = self.performance_calculator.calculate_daily_metrics(symbol, date)
                    results['performance'][symbol] = performance_metrics
                except Exception as e:
                    logger.error(f"Performance calculation failed for {symbol}: {e}")
                    results['errors'].append(f"Performance calculation failed for {symbol}: {e}")
            
            # Step 4: Generate daily report
            logger.info("Step 4: Generating daily report")
            report_content = self.report_generator.generate_daily_summary(date, results)
            results['report'] = report_content
            
            logger.info("Daily workflow completed successfully")
            
        except Exception as e:
            logger.error(f"Daily workflow failed: {e}")
            results['errors'].append(f"Daily workflow failed: {e}")
            raise
        
        return results
    
    def run_backfill(self, start_date: datetime, end_date: datetime):
        """Run the daily workflow for a range of dates (backfill missing data)"""
        logger.info(f"Starting backfill from {start_date.date()} to {end_date.date()}")
        
        current_date = start_date
        while current_date <= end_date:
            # Skip weekends (assuming market is closed)
            if current_date.weekday() < 5:  # Monday = 0, Friday = 4
                try:
                    logger.info(f"Processing backfill for {current_date.date()}")
                    self.run_daily_workflow(current_date)
                except Exception as e:
                    logger.error(f"Backfill failed for {current_date.date()}: {e}")
            
            current_date += timedelta(days=1)
        
        logger.info("Backfill completed")


def main():
    """Main entry point for daily scheduler"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Daily market data scheduler")
    parser.add_argument('--date', help='Specific date to process (YYYY-MM-DD)')
    parser.add_argument('--backfill-start', help='Start date for backfill (YYYY-MM-DD)')
    parser.add_argument('--backfill-end', help='End date for backfill (YYYY-MM-DD)')
    parser.add_argument('--dry-run', action='store_true', help='Dry run mode (no data changes)')
    
    args = parser.parse_args()
    
    scheduler = DailyScheduler()
    
    try:
        if args.backfill_start and args.backfill_end:
            # Backfill mode
            start_date = datetime.strptime(args.backfill_start, '%Y-%m-%d')
            end_date = datetime.strptime(args.backfill_end, '%Y-%m-%d')
            scheduler.run_backfill(start_date, end_date)
        else:
            # Single day mode
            date = datetime.strptime(args.date, '%Y-%m-%d') if args.date else datetime.now()
            results = scheduler.run_daily_workflow(date)
            
            print("Daily workflow completed!")
            print(f"Processed {len(results.get('data', {}))} symbols")
            print(f"Generated {len(results.get('strategies', {}))} strategy results")
            print(f"Calculated {len(results.get('performance', {}))} performance metrics")
            
            if results.get('errors'):
                print(f"Encountered {len(results['errors'])} errors:")
                for error in results['errors']:
                    print(f"  - {error}")
    
    except Exception as e:
        logger.error(f"Scheduler execution failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
