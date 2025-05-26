#!/usr/bin/env python3
"""
Test script for data aggregation functionality
"""
import sys
import os
from datetime import datetime, timedelta

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from analysis.aggregation import DataAggregator


def test_aggregation():
    """Test data aggregation functions"""
    aggregator = DataAggregator()
    
    # Test with AAPL data
    symbol = "AAPL"
    end_date = datetime(2024, 12, 31)  
    start_date = end_date - timedelta(days=90)  # Last 3 months of 2024
    
    print(f"Testing data aggregation for {symbol}")
    print(f"Period: {start_date.date()} to {end_date.date()}")
    print("=" * 60)
    
    # Test weekly aggregation
    print("\n📊 WEEKLY AGGREGATION")
    print("-" * 30)
    weekly_data = aggregator.aggregate_daily_to_weekly(symbol, start_date, end_date)
    
    if weekly_data:
        print(f"Generated {len(weekly_data)} weekly periods:")
        for week in weekly_data[-3:]:  # Show last 3 weeks
            print(f"  Week {week.start_date.date()} to {week.end_date.date()}:")
            print(f"    Open: ${week.open_price:.2f}, Close: ${week.close_price:.2f}")
            print(f"    Change: {week.price_change_pct:.2%}, Volatility: {week.volatility:.4f}")
            print(f"    Volume: {week.volume:,}, Avg Volume: {week.avg_volume:,.0f}")
            if week.avg_rsi:
                print(f"    Avg RSI: {week.avg_rsi:.1f}")
            print()
    else:
        print("  No weekly data generated")
    
    # Test monthly aggregation
    print("\n📈 MONTHLY AGGREGATION")
    print("-" * 30)
    monthly_data = aggregator.aggregate_daily_to_monthly(symbol, start_date, end_date)
    
    if monthly_data:
        print(f"Generated {len(monthly_data)} monthly periods:")
        for month in monthly_data:
            print(f"  Month {month.start_date.strftime('%Y-%m')}:")
            print(f"    Open: ${month.open_price:.2f}, Close: ${month.close_price:.2f}")
            print(f"    High: ${month.high_price:.2f}, Low: ${month.low_price:.2f}")
            print(f"    Change: {month.price_change_pct:.2%}, Volatility: {month.volatility:.4f}")
            print(f"    Volume: {month.volume:,}")
            if month.avg_rsi:
                print(f"    Avg RSI: {month.avg_rsi:.1f}")
            print()
    else:
        print("  No monthly data generated")
    
    # Test rolling metrics
    print("\n🔄 ROLLING METRICS")
    print("-" * 30)
    test_date = datetime(2024, 12, 15)
    
    for window in [30, 60, 90]:
        rolling = aggregator.calculate_rolling_metrics(symbol, test_date, window)
        if rolling:
            print(f"  {window}-day rolling metrics (as of {test_date.date()}):")
            print(f"    Total Return: {rolling.total_return:.2%}")
            print(f"    Annualized Return: {rolling.annualized_return:.2%}")
            print(f"    Volatility: {rolling.volatility:.2%}")
            if rolling.sharpe_ratio:
                print(f"    Sharpe Ratio: {rolling.sharpe_ratio:.2f}")
            print(f"    Max Drawdown: {rolling.max_drawdown:.2%}")
            print(f"    Trend: {rolling.price_trend}")
            print(f"    Momentum Score: {rolling.momentum_score:.2%}")
            print()
        else:
            print(f"  No data for {window}-day rolling metrics")
    
    # Test comparison baselines
    print("\n📊 COMPARISON BASELINES")
    print("-" * 30)
    baselines = aggregator.get_comparison_baselines(test_date)
    if baselines:
        print(f"  Market benchmarks (as of {test_date.date()}):")
        for name, return_val in baselines.items():
            print(f"    {name}: {return_val:.2%}")
    else:
        print("  No baseline data available")


if __name__ == "__main__":
    test_aggregation()
