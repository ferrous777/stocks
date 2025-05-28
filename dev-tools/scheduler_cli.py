#!/usr/bin/env python3
"""
CLI wrapper for the daily scheduler system
"""
import sys
import os
import argparse
from datetime import datetime, timedelta

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from scheduler.daily_scheduler import DailyScheduler


def cmd_run(args):
    """Run daily workflow for a specific date"""
    scheduler = DailyScheduler()
    
    date = datetime.strptime(args.date, '%Y-%m-%d') if args.date else datetime.now()
    
    print(f"Running daily workflow for {date.date()}")
    print("=" * 50)
    
    try:
        results = scheduler.run_daily_workflow(date)
        
        print("✅ Daily workflow completed successfully!")
        print(f"📊 Processed {len(results.get('data', {}))} symbols")
        print(f"🎯 Generated {len(results.get('strategies', {}))} strategy results")
        print(f"📈 Calculated {len(results.get('performance', {}))} performance metrics")
        
        if results.get('errors'):
            print(f"⚠️  Encountered {len(results['errors'])} errors:")
            for error in results['errors']:
                print(f"   - {error}")
        
        # Show sample strategy signals
        if results.get('strategies'):
            print("\n🎯 Sample Strategy Signals:")
            count = 0
            for symbol, strategies in results['strategies'].items():
                for strategy_name, strategy_result in strategies.items():
                    signal = strategy_result.get('signal', 'HOLD')
                    confidence = strategy_result.get('confidence', 0)
                    if signal in ['BUY', 'SELL'] and count < 5:
                        print(f"   {symbol} ({strategy_name}): {signal} (Confidence: {confidence:.2f})")
                        count += 1
        
        if 'report' in results:
            print(f"\n📄 Daily report generated and saved to reports/")
    
    except Exception as e:
        print(f"❌ Workflow failed: {e}")
        sys.exit(1)


def cmd_backfill(args):
    """Run backfill for a date range"""
    scheduler = DailyScheduler()
    
    start_date = datetime.strptime(args.start_date, '%Y-%m-%d')
    end_date = datetime.strptime(args.end_date, '%Y-%m-%d')
    
    print(f"Running backfill from {start_date.date()} to {end_date.date()}")
    print("=" * 50)
    
    try:
        scheduler.run_backfill(start_date, end_date)
        print("✅ Backfill completed successfully!")
    
    except Exception as e:
        print(f"❌ Backfill failed: {e}")
        sys.exit(1)


def cmd_status(args):
    """Show scheduler status and recent activity"""
    print("📊 Daily Scheduler Status")
    print("=" * 30)
    
    # Check if logs directory exists
    if os.path.exists('logs'):
        log_files = [f for f in os.listdir('logs') if f.endswith('.log')]
        print(f"Log files: {len(log_files)}")
        
        # Check for recent log activity
        if 'daily_scheduler.log' in log_files:
            log_path = 'logs/daily_scheduler.log'
            stat = os.stat(log_path)
            last_modified = datetime.fromtimestamp(stat.st_mtime)
            print(f"Last scheduler activity: {last_modified.strftime('%Y-%m-%d %H:%M:%S')}")
    else:
        print("No logs directory found")
    
    # Check if reports directory exists
    if os.path.exists('reports'):
        report_files = [f for f in os.listdir('reports') if f.startswith('daily_report_')]
        print(f"Generated reports: {len(report_files)}")
        
        if report_files:
            # Show recent reports
            report_files.sort(reverse=True)
            print("\nRecent reports:")
            for report in report_files[:5]:
                print(f"  - {report}")
    else:
        print("No reports directory found")


def cmd_test(args):
    """Test scheduler components"""
    print("🧪 Testing scheduler components")
    print("=" * 35)
    
    try:
        # Test configuration loading
        from config.config_manager import ConfigManager
        config_manager = ConfigManager()
        config = config_manager.get_config()
        enabled_symbols = [s.symbol for s in config.symbols if s.enabled]
        print(f"✅ Configuration loaded: {len(enabled_symbols)} enabled symbols")
        
        # Test database connection
        from storage.timeseries_db import TimeSeriesDB
        db = TimeSeriesDB()
        stats = db.get_database_stats()
        print(f"✅ Database connected: {stats['total_records']} records")
        
        # Test data aggregator
        from analysis.aggregation import DataAggregator
        aggregator = DataAggregator()
        print(f"✅ Data aggregator initialized")
        
        # Test strategy runner with sample data
        from scheduler.daily_scheduler import StrategyRunner
        strategy_runner = StrategyRunner()
        print(f"✅ Strategy runner initialized")
        
        print("\n🎉 All components tested successfully!")
    
    except Exception as e:
        print(f"❌ Component test failed: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Daily scheduler CLI")
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Run command
    run_parser = subparsers.add_parser('run', help='Run daily workflow')
    run_parser.add_argument('--date', help='Specific date to process (YYYY-MM-DD)')
    run_parser.set_defaults(func=cmd_run)
    
    # Backfill command
    backfill_parser = subparsers.add_parser('backfill', help='Backfill data for date range')
    backfill_parser.add_argument('start_date', help='Start date (YYYY-MM-DD)')
    backfill_parser.add_argument('end_date', help='End date (YYYY-MM-DD)')
    backfill_parser.set_defaults(func=cmd_backfill)
    
    # Status command
    status_parser = subparsers.add_parser('status', help='Show scheduler status')
    status_parser.set_defaults(func=cmd_status)
    
    # Test command
    test_parser = subparsers.add_parser('test', help='Test scheduler components')
    test_parser.set_defaults(func=cmd_test)
    
    args = parser.parse_args()
    
    if args.command is None:
        parser.print_help()
        return
    
    args.func(args)


if __name__ == "__main__":
    main()
