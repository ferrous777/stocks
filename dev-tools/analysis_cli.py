#!/usr/bin/env python3
"""
CLI tool for data aggregation and analysis
"""
import sys
import os
import argparse
from datetime import datetime, timedelta

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from analysis.aggregation import DataAggregator


def format_metrics_table(metrics_list, period_type):
    """Format aggregated metrics as a table"""
    if not metrics_list:
        print(f"  No {period_type} data available")
        return
    
    print(f"\n📊 {period_type.upper()} METRICS")
    print("=" * 80)
    
    # Header
    if period_type == 'weekly':
        print(f"{'Week Start':<12} {'Week End':<12} {'Open':<8} {'Close':<8} {'Change':<8} {'Volume':<12}")
    else:
        print(f"{'Month':<8} {'Open':<8} {'Close':<8} {'High':<8} {'Low':<8} {'Change':<8} {'Volume':<12}")
    
    print("-" * 80)
    
    # Data rows
    for metric in metrics_list:
        if period_type == 'weekly':
            print(f"{metric.start_date.strftime('%Y-%m-%d'):<12} "
                  f"{metric.end_date.strftime('%Y-%m-%d'):<12} "
                  f"${metric.open_price:<7.2f} "
                  f"${metric.close_price:<7.2f} "
                  f"{metric.price_change_pct:>6.2%} "
                  f"{metric.volume:>11,}")
        else:
            print(f"{metric.start_date.strftime('%Y-%m'):<8} "
                  f"${metric.open_price:<7.2f} "
                  f"${metric.close_price:<7.2f} "
                  f"${metric.high_price:<7.2f} "
                  f"${metric.low_price:<7.2f} "
                  f"{metric.price_change_pct:>6.2%} "
                  f"{metric.volume:>11,}")


def format_rolling_metrics(rolling_metrics):
    """Format rolling metrics display"""
    if not rolling_metrics:
        print("  No rolling metrics data available")
        return
    
    print(f"\n🔄 {rolling_metrics.window_days}-DAY ROLLING METRICS")
    print("-" * 50)
    print(f"  Symbol: {rolling_metrics.symbol}")
    print(f"  Date: {rolling_metrics.date.strftime('%Y-%m-%d')}")
    print(f"  Total Return: {rolling_metrics.total_return:.2%}")
    print(f"  Annualized Return: {rolling_metrics.annualized_return:.2%}")
    print(f"  Volatility: {rolling_metrics.volatility:.2%}")
    if rolling_metrics.sharpe_ratio:
        print(f"  Sharpe Ratio: {rolling_metrics.sharpe_ratio:.2f}")
    print(f"  Max Drawdown: {rolling_metrics.max_drawdown:.2%}")
    print(f"  Price Trend: {rolling_metrics.price_trend}")
    print(f"  Momentum Score: {rolling_metrics.momentum_score:.2%}")
    print(f"  Average Price: ${rolling_metrics.avg_price:.2f}")


def cmd_weekly(args):
    """Generate weekly aggregation report"""
    aggregator = DataAggregator()
    
    # Parse dates
    end_date = datetime.strptime(args.end_date, '%Y-%m-%d') if args.end_date else datetime.now()
    start_date = datetime.strptime(args.start_date, '%Y-%m-%d') if args.start_date else end_date - timedelta(days=90)
    
    print(f"Weekly Aggregation Report for {args.symbol}")
    print(f"Period: {start_date.date()} to {end_date.date()}")
    
    weekly_data = aggregator.aggregate_daily_to_weekly(args.symbol, start_date, end_date)
    format_metrics_table(weekly_data, 'weekly')


def cmd_monthly(args):
    """Generate monthly aggregation report"""
    aggregator = DataAggregator()
    
    # Parse dates
    end_date = datetime.strptime(args.end_date, '%Y-%m-%d') if args.end_date else datetime.now()
    start_date = datetime.strptime(args.start_date, '%Y-%m-%d') if args.start_date else end_date - timedelta(days=365)
    
    print(f"Monthly Aggregation Report for {args.symbol}")
    print(f"Period: {start_date.date()} to {end_date.date()}")
    
    monthly_data = aggregator.aggregate_daily_to_monthly(args.symbol, start_date, end_date)
    format_metrics_table(monthly_data, 'monthly')


def cmd_rolling(args):
    """Generate rolling metrics report"""
    aggregator = DataAggregator()
    
    # Parse date
    date = datetime.strptime(args.date, '%Y-%m-%d') if args.date else datetime.now()
    
    print(f"Rolling Metrics Report for {args.symbol}")
    
    for window in args.windows:
        rolling_metrics = aggregator.calculate_rolling_metrics(args.symbol, date, window)
        if rolling_metrics:
            format_rolling_metrics(rolling_metrics)
        else:
            print(f"\n🔄 {window}-DAY ROLLING METRICS")
            print("-" * 50)
            print(f"  No data available for {args.symbol}")


def cmd_compare(args):
    """Compare multiple symbols"""
    aggregator = DataAggregator()
    
    # Parse date
    date = datetime.strptime(args.date, '%Y-%m-%d') if args.date else datetime.now()
    window = args.window
    
    print(f"Symbol Comparison Report")
    print(f"Date: {date.date()}, Window: {window} days")
    print("=" * 80)
    
    # Header
    print(f"{'Symbol':<8} {'Return':<8} {'Ann. Return':<12} {'Volatility':<12} {'Sharpe':<8} {'Trend':<10}")
    print("-" * 80)
    
    for symbol in args.symbols:
        rolling_metrics = aggregator.calculate_rolling_metrics(symbol, date, window)
        if rolling_metrics:
            sharpe_str = f"{rolling_metrics.sharpe_ratio:.2f}" if rolling_metrics.sharpe_ratio else "N/A"
            print(f"{symbol:<8} "
                  f"{rolling_metrics.total_return:>6.2%} "
                  f"{rolling_metrics.annualized_return:>10.2%} "
                  f"{rolling_metrics.volatility:>10.2%} "
                  f"{sharpe_str:>6} "
                  f"{rolling_metrics.price_trend:<10}")
        else:
            print(f"{symbol:<8} {'No data':<55}")


def cmd_baselines(args):
    """Show market baselines"""
    aggregator = DataAggregator()
    
    # Parse date
    date = datetime.strptime(args.date, '%Y-%m-%d') if args.date else datetime.now()
    
    print(f"Market Baselines Report")
    print(f"Date: {date.date()}")
    print("=" * 40)
    
    baselines = aggregator.get_comparison_baselines(date)
    if baselines:
        for name, return_val in baselines.items():
            print(f"  {name}: {return_val:.2%}")
    else:
        print("  No baseline data available")


def main():
    parser = argparse.ArgumentParser(description="Data aggregation and analysis CLI")
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Weekly command
    weekly_parser = subparsers.add_parser('weekly', help='Generate weekly aggregation report')
    weekly_parser.add_argument('symbol', help='Stock symbol (e.g., AAPL)')
    weekly_parser.add_argument('--start-date', help='Start date (YYYY-MM-DD)')
    weekly_parser.add_argument('--end-date', help='End date (YYYY-MM-DD)')
    weekly_parser.set_defaults(func=cmd_weekly)
    
    # Monthly command
    monthly_parser = subparsers.add_parser('monthly', help='Generate monthly aggregation report')
    monthly_parser.add_argument('symbol', help='Stock symbol (e.g., AAPL)')
    monthly_parser.add_argument('--start-date', help='Start date (YYYY-MM-DD)')
    monthly_parser.add_argument('--end-date', help='End date (YYYY-MM-DD)')
    monthly_parser.set_defaults(func=cmd_monthly)
    
    # Rolling command
    rolling_parser = subparsers.add_parser('rolling', help='Generate rolling metrics report')
    rolling_parser.add_argument('symbol', help='Stock symbol (e.g., AAPL)')
    rolling_parser.add_argument('--date', help='Analysis date (YYYY-MM-DD)')
    rolling_parser.add_argument('--windows', nargs='+', type=int, default=[30, 60, 90],
                               help='Rolling window sizes in days (default: 30 60 90)')
    rolling_parser.set_defaults(func=cmd_rolling)
    
    # Compare command
    compare_parser = subparsers.add_parser('compare', help='Compare multiple symbols')
    compare_parser.add_argument('symbols', nargs='+', help='Stock symbols to compare')
    compare_parser.add_argument('--date', help='Analysis date (YYYY-MM-DD)')
    compare_parser.add_argument('--window', type=int, default=30, help='Rolling window size (default: 30)')
    compare_parser.set_defaults(func=cmd_compare)
    
    # Baselines command
    baselines_parser = subparsers.add_parser('baselines', help='Show market baselines')
    baselines_parser.add_argument('--date', help='Analysis date (YYYY-MM-DD)')
    baselines_parser.set_defaults(func=cmd_baselines)
    
    args = parser.parse_args()
    
    if args.command is None:
        parser.print_help()
        return
    
    try:
        args.func(args)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
