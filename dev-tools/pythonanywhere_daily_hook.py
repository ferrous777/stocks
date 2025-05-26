#!/usr/bin/env python3
"""
PythonAnywhere Daily Scheduler Hook

This script is designed to run as a scheduled task on PythonAnywhere.
It handles the daily market data collection and analysis workflow.

PythonAnywhere Usage:
1. Upload this file to your PythonAnywhere account
2. Go to Tasks tab on your Dashboard
3. Set up a scheduled task to run this script daily
4. Command: /home/yourusername/stocks/pythonanywhere_daily_hook.py
5. Time: Choose appropriate market close time (e.g., 6:00 PM EST)

The script handles:
- Working directory setup
- Market calendar integration
- Daily workflow execution
- Error handling and logging
- Email notifications (if configured)
"""

import os
import sys
import logging
from datetime import datetime, date
from pathlib import Path

# Ensure we're in the correct working directory
script_dir = Path(__file__).parent.absolute()
os.chdir(script_dir)

# Add src to Python path
src_path = script_dir / 'src'
sys.path.insert(0, str(src_path))

# Import our modules after path setup
try:
    from market_calendar.market_calendar import MarketCalendar, MarketType, is_trading_day
    from scheduler.daily_scheduler import DailyScheduler
    from config.config_manager import ConfigManager
except ImportError as e:
    print(f"ERROR: Failed to import required modules: {e}")
    print(f"Current working directory: {os.getcwd()}")
    print(f"Python path: {sys.path}")
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
            
            # Run prediction performance analysis
            try:
                logger.info("Running prediction performance analysis...")
                performance_results = self.run_prediction_analysis()
                results['prediction_performance'] = performance_results
                logger.info("Prediction performance analysis completed")
            except Exception as e:
                logger.warning(f"Prediction performance analysis failed: {e}")
                results['prediction_performance'] = {'status': 'error', 'error': str(e)}
            
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
        """Run prediction performance analysis"""
        try:
            import subprocess
            import json
            
            # Run the performance analysis script
            analysis_script = script_dir / 'run_performance_analysis.py'
            
            if not analysis_script.exists():
                return {'status': 'skipped', 'reason': 'Analysis script not found'}
            
            # Execute the performance analysis
            result = subprocess.run(
                [sys.executable, str(analysis_script)],
                cwd=script_dir,
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )
            
            if result.returncode == 0:
                # Extract key information from the output
                output_lines = result.stdout.split('\n')
                
                # Look for specific patterns in the output
                imported_predictions = 0
                updated_outcomes = 0
                active_triggers = 0
                
                for line in output_lines:
                    if 'Imported' in line and 'predictions' in line:
                        try:
                            imported_predictions = int(line.split()[1])
                        except:
                            pass
                    elif 'Updated' in line and 'prediction outcomes' in line:
                        try:
                            updated_outcomes = int(line.split()[1])
                        except:
                            pass
                    elif 'Generated' in line and 'trading triggers' in line:
                        try:
                            active_triggers = int(line.split()[1])
                        except:
                            pass
                
                return {
                    'status': 'success',
                    'imported_predictions': imported_predictions,
                    'updated_outcomes': updated_outcomes,
                    'active_triggers': active_triggers,
                    'output': result.stdout[-500:] if result.stdout else ''  # Last 500 chars
                }
            else:
                return {
                    'status': 'error',
                    'error': result.stderr or 'Unknown error',
                    'return_code': result.returncode
                }
                
        except subprocess.TimeoutExpired:
            return {'status': 'error', 'error': 'Analysis timed out after 5 minutes'}
        except Exception as e:
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
        
        import json
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
