#!/usr/bin/env python3
"""
PythonAnywhere Daily Scheduler Hook

This script is designed to run as a scheduled task on PythonAnywhere.
It handles the daily market data collection and analysis workflow.

PythonAnywhere Usage:
1. Upload this file to your PythonAnywhere account
2. Go to Tasks tab on your Dashboard
3. Set up a scheduled task to run this script daily
4. Command: /home/ferrous77/pythonanywhere_daily_hook.py
5. Time: Choose appropriate market close time (e.g., 6:00 PM EST)

The script handles:
- Working directory setup
- Market calendar integration
- Daily workflow execution
- Error handling and logging
- Email notifications (if configured)
"""

# Standard library imports
import os
import sys
import logging
import json
import glob
import tarfile
import shutil
from datetime import datetime, date, timedelta
from pathlib import Path

# Set up working directory and paths using relative paths
script_dir = Path(__file__).parent.absolute()
os.chdir(script_dir)
src_path = script_dir / 'src'
sys.path.insert(0, str(src_path))

# Import our modules after path setup
try:
    # Market and scheduling modules
    from market_calendar.market_calendar import MarketCalendar, MarketType, is_trading_day
    from scheduler.daily_scheduler import DailyScheduler
    from config.config_manager import ConfigManager
    
    # Performance tracking modules
    from performance.prediction_tracker import PredictionTracker
    from performance.config import (
        DATABASE_PATH, INTEGRATE_WITH_DAILY_WORKFLOW, 
        AUTO_GENERATE_TRIGGERS, REPORT_PATH
    )
    
    # Strategy modules
    from strategies.trend import TrendFollowingStrategy
    from strategies.momentum import MomentumStrategy
    from strategies.mean_reversion import MeanReversionStrategy
    
    # Storage modules
    from storage.timeseries_db import TimeSeriesDB
    from market_data.data_types import HistoricalData, DataPoint
    
except ImportError as e:
    print(f"ERROR: Failed to import required modules: {e}")
    print(f"Current working directory: {os.getcwd()}")
    print(f"Python path: {sys.path}")
    print(f"Script directory: {script_dir}")
    print(f"Source path: {src_path}")
    print(f"Source path exists: {src_path.exists()}")
    if src_path.exists():
        print(f"Contents of src: {list(src_path.iterdir())}")
    sys.exit(1)

# Setup logging with absolute path
log_dir = script_dir / 'logs'
log_dir.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_dir / 'pythonanywhere_daily.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class PythonAnywhereSchedulerHook:
    """Scheduler hook optimized for PythonAnywhere environment"""
    
    def __init__(self):
        self.market_calendar = MarketCalendar(MarketType.NYSE)
        self.scheduler = DailyScheduler()
        self.config_manager = ConfigManager()
        
    def should_run_today(self, target_date: date = None) -> tuple[bool, str]:
        """
        Check if we should run the scheduler today
        Returns (should_run, reason)
        """
        if target_date is None:
            target_date = date.today()
        
        # Check if it's a trading day
        if not self.market_calendar.is_trading_day(target_date):
            return False, f"{target_date} is not a trading day (weekend or holiday)"
        
        # Get trading day info for any special conditions
        trading_day_info = self.market_calendar.get_trading_day_info(target_date)
        
        reason = f"{target_date} is a trading day"
        if trading_day_info.early_close:
            reason += f" with early close at {trading_day_info.early_close}"
        if trading_day_info.note:
            reason += f" ({trading_day_info.note})"
            
        return True, reason
    
    def run_daily_workflow(self, force_run: bool = False) -> dict:
        """
        Execute the daily workflow with PythonAnywhere optimizations
        """
        today = date.today()
        current_time = datetime.now()
        
        logger.info(f"=== PythonAnywhere Daily Scheduler Hook Started ===")
        logger.info(f"Date: {today}")
        logger.info(f"Time: {current_time}")
        logger.info(f"Working Directory: {os.getcwd()}")
        
        # Check if we should run
        should_run, reason = self.should_run_today(today)
        logger.info(f"Trading day check: {reason}")
        
        if not should_run and not force_run:
            logger.info("Skipping execution - not a trading day")
            return {
                'status': 'skipped',
                'reason': reason,
                'date': str(today),
                'execution_time': str(current_time)
            }
        
        if force_run and not should_run:
            logger.warning(f"Force running despite: {reason}")
        
        # Run the daily workflow
        try:
            logger.info("Starting daily workflow execution...")
            results = self.scheduler.run_daily_workflow(current_time)
            
            logger.info("Daily workflow completed successfully")
            
            # Run comprehensive backtesting and recommendations
            try:
                logger.info("Running comprehensive backtesting and recommendations...")
                comprehensive_results = self.run_comprehensive_analysis()
                results['comprehensive_analysis'] = comprehensive_results
                logger.info("Comprehensive analysis completed")
            except Exception as e:
                logger.warning(f"Comprehensive analysis failed: {e}")
                results['comprehensive_analysis'] = {'status': 'error', 'error': str(e)}
            
            # Run prediction performance analysis
            try:
                logger.info("Running prediction performance analysis...")
                performance_results = self.run_prediction_analysis()
                results['prediction_performance'] = performance_results
                logger.info("Prediction performance analysis completed")
            except Exception as e:
                logger.warning(f"Prediction performance analysis failed: {e}")
                results['prediction_performance'] = {'status': 'error', 'error': str(e)}
            
            # Run daily maintenance tasks
            try:
                logger.info("Running daily maintenance tasks...")
                maintenance_results = self.run_daily_maintenance()
                results['maintenance'] = maintenance_results
                logger.info("Daily maintenance completed")
            except Exception as e:
                logger.warning(f"Daily maintenance failed: {e}")
                results['maintenance'] = {'status': 'error', 'error': str(e)}
            
            # Check for missing recommendations and generate if needed
            try:
                logger.info("Checking for missing recommendations...")
                missing_rec_results = self.run_missing_recommendations_check()
                results['missing_recommendations'] = missing_rec_results
                logger.info("Missing recommendations check completed")
            except Exception as e:
                logger.warning(f"Missing recommendations check failed: {e}")
                results['missing_recommendations'] = {'status': 'error', 'error': str(e)}
            
            # Run daily data backup
            try:
                logger.info("Creating daily data backup...")
                backup_results = self.run_data_backup()
                results['backup'] = backup_results
                logger.info("Daily data backup completed")
            except Exception as e:
                logger.warning(f"Daily data backup failed: {e}")
                results['backup'] = {'status': 'error', 'error': str(e)}
            
            # Add metadata
            results.update({
                'execution_date': str(today),
                'execution_time': str(current_time),
                'trading_day_info': reason,
                'environment': 'pythonanywhere',
                'status': 'completed'
            })
            
            return results
            
        except Exception as e:
            error_msg = f"Daily workflow failed: {str(e)}"
            logger.error(error_msg, exc_info=True)
            
            return {
                'status': 'error',
                'error': error_msg,
                'date': str(today),
                'execution_time': str(current_time),
                'environment': 'pythonanywhere'
            }
    
    def run_prediction_analysis(self) -> dict:
        """Run prediction performance analysis (integrated)"""
        try:
            logger.info("Running integrated prediction performance analysis...")
            
            if not INTEGRATE_WITH_DAILY_WORKFLOW:
                logger.info("Prediction performance analysis is disabled in config")
                return {'status': 'disabled', 'reason': 'Disabled in config'}
            
            # Initialize tracker
            tracker = PredictionTracker(DATABASE_PATH)
            
            # Import any new recommendations from today
            imported = tracker.import_historical_predictions()
            logger.info(f"Imported {imported} new predictions")
            
            # Update prediction outcomes
            updated = tracker.update_prediction_outcomes()
            logger.info(f"Updated {updated} prediction outcomes")
            
            # Generate trading triggers if enabled
            triggers = []
            if AUTO_GENERATE_TRIGGERS:
                triggers = tracker.generate_trading_triggers()
                logger.info(f"Generated {len(triggers)} trading triggers")
            
            # Generate performance report
            report = tracker.generate_performance_report()
            
            # Save report
            today = datetime.now().strftime('%Y%m%d')
            report_path = REPORT_PATH.format(date=today)
            
            # Ensure reports directory exists
            report_dir = Path(report_path).parent
            report_dir.mkdir(parents=True, exist_ok=True)
            
            with open(report_path, 'w') as f:
                f.write(report)
            
            logger.info(f"Performance report saved to: {report_path}")
            
            return {
                'status': 'success',
                'imported_predictions': imported,
                'updated_outcomes': updated,
                'active_triggers': len(triggers),
                'report_path': report_path
            }
            
        except ImportError as e:
            logger.warning(f"Prediction performance modules not available: {e}")
            return {'status': 'skipped', 'reason': f'Modules not available: {e}'}
        except Exception as e:
            logger.error(f"Prediction performance analysis failed: {e}", exc_info=True)
            return {'status': 'error', 'error': str(e)}
    
    def run_comprehensive_analysis(self) -> dict:
        """Run comprehensive backtesting and recommendation generation"""
        try:
            logger.info("Running comprehensive backtesting and recommendation analysis...")
            
            db = TimeSeriesDB()
            config = self.config_manager.get_config()
            symbols = [s.symbol for s in config.symbols if s.enabled]
            
            # Set up date ranges for backtests
            end_date = datetime.now()
            start_date_30d = end_date - timedelta(days=30)
            start_date_90d = end_date - timedelta(days=90)
            start_date_1y = end_date - timedelta(days=365)
            
            comprehensive_results = {
                'backtests': {},
                'recommendations': {},
                'strategy_performance': {},
                'errors': []
            }
            
            # Run backtests for different time periods
            backtest_periods = {
                '30d': start_date_30d,
                '90d': start_date_90d,
                '1y': start_date_1y
            }
            
            strategies = {
                'trend_following': TrendFollowingStrategy,
                'momentum': MomentumStrategy,
                'mean_reversion': MeanReversionStrategy
            }
            
            for period_name, start_date in backtest_periods.items():
                logger.info(f"Running {period_name} backtests...")
                comprehensive_results['backtests'][period_name] = {}
                
                for strategy_name, strategy_class in strategies.items():
                    try:
                        # Get historical data for all symbols
                        historical_data = {}
                        for symbol in symbols:
                            symbol_data = db.get_symbol_data(
                                symbol, 
                                start_date.strftime('%Y-%m-%d'), 
                                end_date.strftime('%Y-%m-%d')
                            )
                            if symbol_data and len(symbol_data) > 10:
                                # Convert to the format expected by strategies
                                data_points = [
                                    DataPoint(
                                        date=d.date,
                                        open=d.open,
                                        high=d.high,
                                        low=d.low,
                                        close=d.close,
                                        volume=d.volume
                                    ) for d in symbol_data
                                ]
                                historical_data[symbol] = HistoricalData(
                                    symbol=symbol,
                                    data_points=data_points
                                )
                        
                        if historical_data:
                            # Initialize strategy with data
                            strategy = strategy_class(list(historical_data.keys()), historical_data)
                            
                            # Run backtest
                            backtest_results = strategy.backtest(start_date, end_date)
                            comprehensive_results['backtests'][period_name][strategy_name] = backtest_results
                            
                            logger.info(f"Completed {strategy_name} backtest for {period_name}: {len(backtest_results)} symbols")
                        
                    except Exception as e:
                        error_msg = f"Backtest failed for {strategy_name} {period_name}: {str(e)}"
                        logger.error(error_msg)
                        comprehensive_results['errors'].append(error_msg)
            
            # Generate current recommendations based on latest data
            logger.info("Generating current trading recommendations...")
            for symbol in symbols:
                try:
                    # Get recent data for recommendations
                    recent_data = db.get_symbol_data(
                        symbol,
                        (end_date - timedelta(days=60)).strftime('%Y-%m-%d'),
                        end_date.strftime('%Y-%m-%d')
                    )
                    
                    if recent_data and len(recent_data) > 20:
                        symbol_recommendations = {}
                        
                        for strategy_name, strategy_class in strategies.items():
                            try:
                                # Convert data format
                                data_points = [
                                    DataPoint(
                                        date=d.date,
                                        open=d.open,
                                        high=d.high,
                                        low=d.low,
                                        close=d.close,
                                        volume=d.volume
                                    ) for d in recent_data
                                ]
                                historical_data = {symbol: HistoricalData(symbol=symbol, data_points=data_points)}
                                
                                # Initialize strategy
                                strategy = strategy_class([symbol], historical_data)
                                
                                # Generate signal
                                signal = strategy.generate_signal(symbol, end_date)
                                symbol_recommendations[strategy_name] = signal
                                
                            except Exception as e:
                                error_msg = f"Recommendation failed for {symbol} {strategy_name}: {str(e)}"
                                logger.warning(error_msg)
                                comprehensive_results['errors'].append(error_msg)
                        
                        if symbol_recommendations:
                            comprehensive_results['recommendations'][symbol] = symbol_recommendations
                
                except Exception as e:
                    error_msg = f"Failed to generate recommendations for {symbol}: {str(e)}"
                    logger.error(error_msg)
                    comprehensive_results['errors'].append(error_msg)
            
            # Save comprehensive results
            results_dir = script_dir / 'results'
            results_dir.mkdir(exist_ok=True)
            
            date_str = end_date.strftime('%Y%m%d')
            
            # Save backtests
            for period_name, period_results in comprehensive_results['backtests'].items():
                for strategy_name, strategy_results in period_results.items():
                    for symbol, result in strategy_results.items():
                        backtest_file = results_dir / f"{symbol}_backtest_{strategy_name}_{period_name}_{date_str}.json"
                        with open(backtest_file, 'w') as f:
                            json.dump(result.__dict__ if hasattr(result, '__dict__') else result, f, indent=2, default=str)
            
            # Save recommendations
            recommendations_file = results_dir / f"recommendations_{date_str}.json"
            with open(recommendations_file, 'w') as f:
                json.dump(comprehensive_results['recommendations'], f, indent=2, default=str)
            
            logger.info(f"Comprehensive analysis completed. Results saved to {results_dir}")
            
            return {
                'status': 'success',
                'backtests_generated': sum(len(period_results) for period_results in comprehensive_results['backtests'].values()),
                'recommendations_generated': len(comprehensive_results['recommendations']),
                'errors_count': len(comprehensive_results['errors']),
                'results_dir': str(results_dir)
            }
            
        except ImportError as e:
            logger.warning(f"Comprehensive analysis modules not available: {e}")
            return {'status': 'skipped', 'reason': f'Strategy modules not available: {e}'}
        except Exception as e:
            logger.error(f"Comprehensive analysis failed: {e}", exc_info=True)
            return {'status': 'error', 'error': str(e)}
    
    def generate_summary_report(self, results: dict) -> str:
        """Generate a summary report for the daily execution"""
        
        report_lines = [
            f"=== Daily Market Analysis Report ===",
            f"Date: {results.get('execution_date', 'N/A')}",
            f"Time: {results.get('execution_time', 'N/A')}",
            f"Status: {results.get('status', 'unknown').upper()}",
            f"Environment: PythonAnywhere",
            ""
        ]
        
        if results.get('status') == 'skipped':
            report_lines.extend([
                f"Execution skipped: {results.get('reason', 'Unknown reason')}",
                ""
            ])
        elif results.get('status') == 'error':
            report_lines.extend([
                f"❌ Execution failed with error:",
                f"{results.get('error', 'Unknown error')}",
                ""
            ])
        elif results.get('status') == 'completed':
            # Data collection summary
            data_results = results.get('data', {})
            successful_fetches = sum(1 for result in data_results.values() if result is not None)
            total_symbols = len(data_results)
            
            report_lines.extend([
                f"✅ Execution completed successfully",
                f"",
                f"📊 Data Collection:",
                f"- Symbols processed: {total_symbols}",
                f"- Successful fetches: {successful_fetches}",
                f"- Success rate: {successful_fetches/total_symbols*100:.1f}%" if total_symbols > 0 else "- Success rate: N/A",
                ""
            ])
            
            # Strategy signals summary
            strategies = results.get('strategies', {})
            if strategies:
                signal_counts = {'BUY': 0, 'SELL': 0, 'HOLD': 0}
                
                for symbol_strategies in strategies.values():
                    for strategy_result in symbol_strategies.values():
                        signal = strategy_result.get('signal', 'HOLD')
                        if signal in signal_counts:
                            signal_counts[signal] += 1
                
                report_lines.extend([
                    f"📈 Strategy Signals:",
                    f"- BUY signals: {signal_counts['BUY']}",
                    f"- SELL signals: {signal_counts['SELL']}",
                    f"- HOLD signals: {signal_counts['HOLD']}",
                    ""
                ])
            
            # Performance metrics summary
            performance = results.get('performance', {})
            if performance:
                symbols_with_metrics = len(performance)
                report_lines.extend([
                    f"📊 Performance Metrics:",
                    f"- Symbols analyzed: {symbols_with_metrics}",
                    ""
                ])
            
            # Comprehensive analysis summary
            comp_analysis = results.get('comprehensive_analysis', {})
            if comp_analysis and comp_analysis.get('status') == 'success':
                report_lines.extend([
                    f"🔬 Comprehensive Analysis:",
                    f"- Backtests generated: {comp_analysis.get('backtests_generated', 0)}",
                    f"- Recommendations generated: {comp_analysis.get('recommendations_generated', 0)}",
                    f"- Analysis errors: {comp_analysis.get('errors_count', 0)}",
                    ""
                ])
            elif comp_analysis and comp_analysis.get('status') == 'error':
                report_lines.extend([
                    f"⚠️  Comprehensive analysis failed: {comp_analysis.get('error', 'Unknown error')}",
                    ""
                ])
            
            # Prediction performance analysis summary
            pred_performance = results.get('prediction_performance', {})
            if pred_performance and pred_performance.get('status') == 'success':
                report_lines.extend([
                    f"🎯 Prediction Performance Analysis:",
                    f"- Imported predictions: {pred_performance.get('imported_predictions', 0)}",
                    f"- Updated outcomes: {pred_performance.get('updated_outcomes', 0)}",
                    f"- Active trading triggers: {pred_performance.get('active_triggers', 0)}",
                    ""
                ])
            elif pred_performance and pred_performance.get('status') == 'error':
                report_lines.extend([
                    f"⚠️  Prediction analysis failed: {pred_performance.get('error', 'Unknown error')}",
                    ""
                ])
            
            # Daily maintenance summary
            maintenance = results.get('maintenance', {})
            if maintenance and maintenance.get('status') == 'success':
                tasks_completed = len(maintenance.get('tasks_completed', []))
                tasks_failed = len(maintenance.get('tasks_failed', []))
                cleanup_stats = maintenance.get('cleanup_stats', {})
                health_checks = maintenance.get('health_checks', {})
                
                report_lines.extend([
                    f"🔧 Daily Maintenance:",
                    f"- Tasks completed: {tasks_completed}",
                    f"- Tasks failed: {tasks_failed}",
                ])
                
                if cleanup_stats:
                    if cleanup_stats.get('old_logs_cleaned', 0) > 0:
                        report_lines.append(f"- Old logs cleaned: {cleanup_stats['old_logs_cleaned']}")
                    if cleanup_stats.get('old_results_cleaned', 0) > 0:
                        report_lines.append(f"- Old results cleaned: {cleanup_stats['old_results_cleaned']}")
                
                if health_checks:
                    if 'free_disk_gb' in health_checks:
                        report_lines.append(f"- Free disk space: {health_checks['free_disk_gb']}GB")
                    if 'data_gaps_detected' in health_checks:
                        gaps = health_checks['data_gaps_detected']
                        if gaps > 0:
                            report_lines.append(f"- ⚠️  Data gaps detected: {gaps}")
                        else:
                            report_lines.append(f"- Data integrity: ✅ No gaps")
                
                report_lines.append("")
                
            elif maintenance and maintenance.get('status') == 'error':
                report_lines.extend([
                    f"⚠️  Daily maintenance failed: {maintenance.get('error', 'Unknown error')}",
                    ""
                ])
            
            # Missing recommendations summary  
            missing_rec = results.get('missing_recommendations', {})
            if missing_rec and missing_rec.get('status') == 'success':
                missing_count = len(missing_rec.get('missing_symbols', []))
                generated_count = missing_rec.get('generated_count', 0)
                
                if missing_count > 0:
                    report_lines.extend([
                        f"📝 Missing Recommendations:",
                        f"- Symbols missing recommendations: {missing_count}",
                        f"- Placeholder recommendations generated: {generated_count}",
                        ""
                    ])
                else:
                    report_lines.extend([
                        f"📝 Recommendations: ✅ All complete",
                        ""
                    ])
                    
            elif missing_rec and missing_rec.get('status') == 'error':
                report_lines.extend([
                    f"⚠️  Missing recommendations check failed: {missing_rec.get('error', 'Unknown error')}",
                    ""
                ])
            
            # Daily backup summary
            backup = results.get('backup', {})
            if backup and backup.get('status') == 'success':
                backup_size = backup.get('backup_size_mb', 0)
                files_count = backup.get('files_backed_up', 0)
                backup_name = backup.get('backup_filename', 'Unknown')
                
                report_lines.extend([
                    f"💾 Daily Backup:",
                    f"- Backup created: {backup_name}",
                    f"- Size: {backup_size}MB ({files_count} files)",
                    ""
                ])
                
            elif backup and backup.get('status') == 'skipped':
                report_lines.extend([
                    f"💾 Daily Backup: Skipped ({backup.get('reason', 'No reason')})",
                    ""
                ])
                
            elif backup and backup.get('status') == 'error':
                report_lines.extend([
                    f"⚠️  Daily backup failed: {backup.get('error', 'Unknown error')}",
                    ""
                ])
            
            # Errors summary
            errors = results.get('errors', [])
            if errors:
                report_lines.extend([
                    f"⚠️  Errors encountered: {len(errors)}",
                    ""
                ])
                for error in errors[:5]:  # Show first 5 errors
                    report_lines.append(f"- {error}")
                if len(errors) > 5:
                    report_lines.append(f"- ... and {len(errors) - 5} more")
                report_lines.append("")
        
        report_lines.extend([
            f"Trading day info: {results.get('trading_day_info', 'N/A')}",
            "",
            f"--- End of Report ---"
        ])
        
        return "\n".join(report_lines)
    
    def save_execution_log(self, results: dict, report: str):
        """Save execution results and report to files"""
        
        execution_date = results.get('execution_date', datetime.now().strftime('%Y-%m-%d'))
        
        # Save JSON results
        results_dir = script_dir / 'logs' / 'daily_executions'
        results_dir.mkdir(parents=True, exist_ok=True)
        
        results_file = results_dir / f"execution_{execution_date}.json"
        with open(results_file, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        
        # Save text report
        reports_dir = script_dir / 'logs' / 'daily_reports'
        reports_dir.mkdir(parents=True, exist_ok=True)
        
        report_file = reports_dir / f"report_{execution_date}.txt"
        with open(report_file, 'w') as f:
            f.write(report)
        
        logger.info(f"Execution results saved to: {results_file}")
        logger.info(f"Report saved to: {report_file}")

    def run_daily_maintenance(self) -> dict:
        """Run daily maintenance tasks"""
        try:
            logger.info("Running daily maintenance tasks...")
            
            maintenance_results = {
                'status': 'success',
                'tasks_completed': [],
                'tasks_failed': [],
                'cleanup_stats': {},
                'health_checks': {}
            }
            
            # 1. Clean old log files (keep 30 days)
            try:
                log_dir = script_dir / 'logs'
                if log_dir.exists():
                    cutoff_date = datetime.now() - timedelta(days=30)
                    log_files = glob.glob(str(log_dir / '*.log'))
                    cleaned_files = 0
                    
                    for log_file in log_files:
                        file_path = Path(log_file)
                        if file_path.stat().st_mtime < cutoff_date.timestamp():
                            file_path.unlink()
                            cleaned_files += 1
                    
                    maintenance_results['cleanup_stats']['old_logs_cleaned'] = cleaned_files
                    maintenance_results['tasks_completed'].append('log_cleanup')
                    logger.info(f"Cleaned {cleaned_files} old log files")
                    
            except Exception as e:
                logger.warning(f"Log cleanup failed: {e}")
                maintenance_results['tasks_failed'].append(f'log_cleanup: {e}')
            
            # 2. Clean old execution results (keep 90 days)
            try:
                results_dir = script_dir / 'results'
                if results_dir.exists():
                    cutoff_date = datetime.now() - timedelta(days=90)
                    result_files = list(results_dir.glob('*.json'))
                    cleaned_files = 0
                    
                    for result_file in result_files:
                        if result_file.stat().st_mtime < cutoff_date.timestamp():
                            result_file.unlink()
                            cleaned_files += 1
                    
                    maintenance_results['cleanup_stats']['old_results_cleaned'] = cleaned_files
                    maintenance_results['tasks_completed'].append('results_cleanup')
                    logger.info(f"Cleaned {cleaned_files} old result files")
                    
            except Exception as e:
                logger.warning(f"Results cleanup failed: {e}")
                maintenance_results['tasks_failed'].append(f'results_cleanup: {e}')
            
            # 3. Database maintenance (cleanup old data)
            try:
                db = TimeSeriesDB()
                cleanup_success = db.cleanup_old_data(days_to_keep=365)
                
                if cleanup_success:
                    maintenance_results['tasks_completed'].append('database_cleanup')
                    logger.info("Database cleanup completed")
                else:
                    maintenance_results['tasks_failed'].append('database_cleanup: cleanup returned false')
                    
            except Exception as e:
                logger.warning(f"Database cleanup failed: {e}")
                maintenance_results['tasks_failed'].append(f'database_cleanup: {e}')
            
            # 4. Health checks
            try:
                # Check disk space
                free_space = shutil.disk_usage(script_dir).free / (1024**3)  # GB
                maintenance_results['health_checks']['free_disk_gb'] = round(free_space, 2)
                
                # Check data freshness
                latest_file = None
                latest_time = 0
                
                cache_dir = script_dir / 'cache'
                if cache_dir.exists():
                    for cache_file in cache_dir.glob('*.json'):
                        if cache_file.stat().st_mtime > latest_time:
                            latest_time = cache_file.stat().st_mtime
                            latest_file = cache_file.name
                
                if latest_file:
                    hours_old = (datetime.now().timestamp() - latest_time) / 3600
                    maintenance_results['health_checks']['latest_data_hours_old'] = round(hours_old, 2)
                    maintenance_results['health_checks']['latest_data_file'] = latest_file
                
                maintenance_results['tasks_completed'].append('health_checks')
                logger.info(f"Health checks completed - Free disk: {free_space:.2f}GB")
                
            except Exception as e:
                logger.warning(f"Health checks failed: {e}")
                maintenance_results['tasks_failed'].append(f'health_checks: {e}')
            
            # 5. Data gap detection (quick check)
            try:
                # Simple gap detection - check if we have data for the last 5 trading days
                market_cal = MarketCalendar(MarketType.NYSE)
                today = date.today()
                gap_count = 0
                
                # Check last 5 trading days
                for i in range(1, 8):  # Check more days to find 5 trading days
                    check_date = today - timedelta(days=i)
                    if market_cal.is_trading_day(check_date):
                        date_str = check_date.strftime('%Y%m%d')
                        
                        # Check if we have any result files for this date
                        results_pattern = script_dir / 'results' / f'*_{date_str}.json'
                        if not list(script_dir.glob(str(results_pattern))):
                            gap_count += 1
                        
                        if gap_count == 0 and i >= 5:  # Found 5 trading days with data
                            break
                
                maintenance_results['health_checks']['data_gaps_detected'] = gap_count
                maintenance_results['tasks_completed'].append('gap_detection')
                
                if gap_count > 0:
                    logger.warning(f"Detected {gap_count} potential data gaps in recent trading days")
                else:
                    logger.info("No data gaps detected in recent trading days")
                    
            except Exception as e:
                logger.warning(f"Gap detection failed: {e}")
                maintenance_results['tasks_failed'].append(f'gap_detection: {e}')
            
            logger.info(f"Daily maintenance completed - {len(maintenance_results['tasks_completed'])} tasks successful, {len(maintenance_results['tasks_failed'])} failed")
            
            return maintenance_results
            
        except Exception as e:
            logger.error(f"Daily maintenance failed: {e}", exc_info=True)
            return {'status': 'error', 'error': str(e)}

    def run_missing_recommendations_check(self) -> dict:
        """Check for and generate missing recommendation files"""
        try:
            logger.info("Checking for missing recommendations...")
            
            # Get all backtest files
            results_dir = script_dir / 'results'
            backtest_files = glob.glob(str(results_dir / '*_backtest_*.json'))
            backtest_symbols = set()
            
            for file in backtest_files:
                symbol = Path(file).name.split('_')[0]
                backtest_symbols.add(symbol)
            
            # Get all recommendation files  
            recommendation_files = glob.glob(str(results_dir / '*_recommendations_*.json'))
            recommendation_symbols = set()
            
            for file in recommendation_files:
                symbol = Path(file).name.split('_')[0]
                recommendation_symbols.add(symbol)
            
            # Find symbols with backtest but no recommendations
            missing_symbols = backtest_symbols - recommendation_symbols
            
            if missing_symbols:
                logger.info(f"Found {len(missing_symbols)} symbols with missing recommendations: {sorted(missing_symbols)}")
                
                # Generate placeholder recommendations for missing symbols
                date_str = datetime.now().strftime('%Y%m%d')
                generated_count = 0
                
                for symbol in missing_symbols:
                    try:
                        placeholder_data = {
                            'symbol': symbol,
                            'date': date_str,
                            'recommendations': {
                                'trend_following': {
                                    'signal': 'HOLD',
                                    'confidence': 0.5,
                                    'reason': 'Generated placeholder - needs actual analysis'
                                },
                                'momentum': {
                                    'signal': 'HOLD', 
                                    'confidence': 0.5,
                                    'reason': 'Generated placeholder - needs actual analysis'
                                },
                                'mean_reversion': {
                                    'signal': 'HOLD',
                                    'confidence': 0.5,
                                    'reason': 'Generated placeholder - needs actual analysis'
                                }
                            },
                            'generated': True,
                            'timestamp': datetime.now().isoformat()
                        }
                        
                        rec_file = results_dir / f"{symbol}_recommendations_{date_str}.json"
                        with open(rec_file, 'w') as f:
                            json.dump(placeholder_data, f, indent=2)
                        
                        generated_count += 1
                        
                    except Exception as e:
                        logger.warning(f"Failed to generate placeholder for {symbol}: {e}")
                
                return {
                    'status': 'success',
                    'missing_symbols': list(missing_symbols),
                    'generated_count': generated_count
                }
            else:
                logger.info("All symbols with backtests have corresponding recommendations")
                return {
                    'status': 'success', 
                    'missing_symbols': [],
                    'generated_count': 0
                }
                
        except Exception as e:
            logger.error(f"Missing recommendations check failed: {e}", exc_info=True)
            return {'status': 'error', 'error': str(e)}

    def run_data_backup(self) -> dict:
        """Create a backup of critical data files"""
        try:
            logger.info("Creating daily data backup...")
            
            # Create backup directory
            backup_dir = script_dir / 'backups'
            backup_dir.mkdir(exist_ok=True)
            
            # Generate backup filename with timestamp
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_filename = f"daily_backup_{timestamp}.tar.gz"
            backup_path = backup_dir / backup_filename
            
            # Directories to backup
            backup_dirs = []
            
            # Add cache directory if it exists and has recent files
            cache_dir = script_dir / 'cache'
            if cache_dir.exists():
                recent_cache_files = [f for f in cache_dir.iterdir() 
                                    if f.is_file() and 
                                    (datetime.now().timestamp() - f.stat().st_mtime) < 86400*7]  # 7 days
                if recent_cache_files:
                    backup_dirs.append(('cache', cache_dir))
            
            # Add recent results (last 30 days)
            results_dir = script_dir / 'results'
            if results_dir.exists():
                recent_result_files = [f for f in results_dir.iterdir() 
                                     if f.is_file() and 
                                     (datetime.now().timestamp() - f.stat().st_mtime) < 86400*30]  # 30 days
                if recent_result_files:
                    backup_dirs.append(('results', results_dir))
            
            # Add configuration files
            config_dirs = [
                ('src/config', script_dir / 'src' / 'config'),
                ('config', script_dir / 'config')
            ]
            
            for name, path in config_dirs:
                if path.exists():
                    backup_dirs.append((name, path))
            
            if not backup_dirs:
                return {
                    'status': 'skipped',
                    'reason': 'No data to backup',
                    'backup_size_mb': 0
                }
            
            # Create tar.gz backup
            files_backed_up = 0
            with tarfile.open(backup_path, 'w:gz') as tar:
                for dir_name, dir_path in backup_dirs:
                    try:
                        if dir_path.is_file():
                            tar.add(dir_path, arcname=f"{dir_name}/{dir_path.name}")
                            files_backed_up += 1
                        else:
                            for file_path in dir_path.rglob('*'):
                                if file_path.is_file():
                                    # Create relative path for archive
                                    rel_path = file_path.relative_to(script_dir)
                                    tar.add(file_path, arcname=str(rel_path))
                                    files_backed_up += 1
                    except Exception as e:
                        logger.warning(f"Failed to backup {dir_name}: {e}")
            
            # Get backup size
            backup_size_mb = backup_path.stat().st_size / (1024 * 1024)
            
            # Clean old backups (keep only last 7 days)
            try:
                cutoff_time = datetime.now().timestamp() - (7 * 24 * 3600)
                old_backups = [f for f in backup_dir.glob('daily_backup_*.tar.gz') 
                             if f.stat().st_mtime < cutoff_time]
                
                for old_backup in old_backups:
                    old_backup.unlink()
                    
                logger.info(f"Cleaned {len(old_backups)} old backup files")
                    
            except Exception as e:
                logger.warning(f"Failed to clean old backups: {e}")
            
            logger.info(f"Backup created: {backup_filename} ({backup_size_mb:.2f}MB, {files_backed_up} files)")
            
            return {
                'status': 'success',
                'backup_filename': backup_filename,
                'backup_size_mb': round(backup_size_mb, 2),
                'files_backed_up': files_backed_up,
                'backup_path': str(backup_path)
            }
            
        except Exception as e:
            logger.error(f"Data backup failed: {e}", exc_info=True)
            return {'status': 'error', 'error': str(e)}


def main():
    """Main entry point for PythonAnywhere scheduled task"""
    
    # Check for command line arguments
    force_run = '--force' in sys.argv
    
    # Initialize and run
    hook = PythonAnywhereSchedulerHook()
    results = hook.run_daily_workflow(force_run=force_run)
    
    # Generate and save report
    report = hook.generate_summary_report(results)
    hook.save_execution_log(results, report)
    
    # Print summary to console (visible in PythonAnywhere task logs)
    print("\n" + "="*60)
    print(report)
    print("="*60)
    
    # Exit with appropriate code
    if results.get('status') == 'error':
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
