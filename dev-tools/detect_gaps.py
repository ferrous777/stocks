#!/usr/bin/env python3
"""
Data Gap Detection and Analysis Tool

This script analyzes the cached historical data to identify:
- Missing dates in the data series
- Symbols with incomplete data coverage
- Data integrity issues
- Recommendations for backfill operations

Usage:
    python detect_gaps.py                        # Analyze all symbols
    python detect_gaps.py --symbols AAPL MSFT   # Analyze specific symbols
    python detect_gaps.py --start 2025-05-01    # Analyze from specific date
    python detect_gaps.py --fix                 # Generate fix commands
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Set, Tuple
import logging

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from market_calendar.market_calendar import is_trading_day, MarketType
from config.config_manager import ConfigManager

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(description='Detect data gaps in historical market data')
    
    parser.add_argument('--symbols', nargs='+', help='Specific symbols to analyze')
    parser.add_argument('--start', type=str, help='Start date for analysis (YYYY-MM-DD)')
    parser.add_argument('--end', type=str, help='End date for analysis (YYYY-MM-DD)', 
                       default=datetime.now().strftime('%Y-%m-%d'))
    parser.add_argument('--cache-dir', default='cache', help='Cache directory path')
    parser.add_argument('--fix', action='store_true', help='Generate commands to fix gaps')
    parser.add_argument('--min-gap-size', type=int, default=1, help='Minimum gap size to report')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    
    return parser.parse_args()

def get_configured_symbols() -> List[str]:
    """Get symbols from configuration"""
    try:
        config_manager = ConfigManager()
        config = config_manager.get_config()
        return [sym.symbol for sym in config.symbols]
    except Exception as e:
        logger.warning(f"Could not load symbols from config: {e}")
        # Fallback to finding cache files
        cache_files = [f for f in os.listdir('cache') if f.endswith('_historical.json')]
        return [f.replace('_historical.json', '') for f in cache_files]

def load_symbol_data(symbol: str, cache_dir: str) -> List[str]:
    """Load dates from symbol cache file"""
    cache_file = os.path.join(cache_dir, f"{symbol}_historical.json")
    
    if not os.path.exists(cache_file):
        return []
    
    try:
        with open(cache_file, 'r') as f:
            data = json.load(f)
        
        # Handle nested structure
        if 'data_points' in data:
            points = data['data_points']
        else:
            points = data
        
        # Extract and sort dates
        dates = [point['date'] for point in points if 'date' in point]
        return sorted(dates)
    
    except Exception as e:
        logger.error(f"Error loading data for {symbol}: {e}")
        return []

def get_trading_days(start_date: datetime, end_date: datetime) -> Set[str]:
    """Get set of trading days in date range"""
    trading_days = set()
    current = start_date
    
    while current <= end_date:
        if is_trading_day(current, MarketType.NYSE):
            trading_days.add(current.strftime('%Y-%m-%d'))
        current += timedelta(days=1)
    
    return trading_days

def find_date_gaps(available_dates: List[str], expected_dates: Set[str]) -> List[Tuple[str, str, int]]:
    """Find gaps in date series"""
    available_set = set(available_dates)
    missing_dates = sorted(expected_dates - available_set)
    
    if not missing_dates:
        return []
    
    # Group consecutive missing dates into gaps
    gaps = []
    gap_start = missing_dates[0]
    gap_end = missing_dates[0]
    
    for i in range(1, len(missing_dates)):
        current_date = datetime.strptime(missing_dates[i], '%Y-%m-%d')
        prev_date = datetime.strptime(missing_dates[i-1], '%Y-%m-%d')
        
        # Check if dates are consecutive trading days
        if (current_date - prev_date).days <= 3:  # Allow for weekends
            gap_end = missing_dates[i]
        else:
            # End current gap, start new one
            gap_size = len([d for d in missing_dates if gap_start <= d <= gap_end])
            gaps.append((gap_start, gap_end, gap_size))
            gap_start = missing_dates[i]
            gap_end = missing_dates[i]
    
    # Add final gap
    gap_size = len([d for d in missing_dates if gap_start <= d <= gap_end])
    gaps.append((gap_start, gap_end, gap_size))
    
    return gaps

def analyze_symbol(symbol: str, cache_dir: str, expected_dates: Set[str], min_gap_size: int = 1) -> Dict:
    """Analyze a single symbol for data gaps"""
    available_dates = load_symbol_data(symbol, cache_dir)
    
    if not available_dates:
        return {
            'symbol': symbol,
            'status': 'NO_DATA',
            'available_count': 0,
            'expected_count': len(expected_dates),
            'gaps': [],
            'first_date': None,
            'last_date': None
        }
    
    gaps = find_date_gaps(available_dates, expected_dates)
    significant_gaps = [gap for gap in gaps if gap[2] >= min_gap_size]
    
    return {
        'symbol': symbol,
        'status': 'COMPLETE' if not significant_gaps else 'GAPS_FOUND',
        'available_count': len(available_dates),
        'expected_count': len(expected_dates),
        'gaps': significant_gaps,
        'first_date': available_dates[0] if available_dates else None,
        'last_date': available_dates[-1] if available_dates else None
    }

def generate_fix_commands(analysis_results: List[Dict]) -> List[str]:
    """Generate commands to fix identified gaps"""
    commands = []
    
    for result in analysis_results:
        if result['status'] == 'NO_DATA':
            # Need full backfill
            commands.append(f"# Full backfill needed for {result['symbol']}")
            commands.append(f"python run_daily.py --symbol {result['symbol']} --start 2024-01-01 --force")
        elif result['gaps']:
            # Need specific gap fills
            for gap_start, gap_end, gap_size in result['gaps']:
                if gap_start == gap_end:
                    commands.append(f"python run_daily.py --symbol {result['symbol']} --date {gap_start} --force")
                else:
                    commands.append(f"python run_daily.py --symbol {result['symbol']} --start {gap_start} --end {gap_end} --force")
    
    return commands

def main():
    args = parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Determine symbols to analyze
    if args.symbols:
        symbols = args.symbols
    else:
        symbols = get_configured_symbols()
    
    logger.info(f"Analyzing {len(symbols)} symbols for data gaps")
    
    # Determine date range
    if args.start:
        start_date = datetime.strptime(args.start, '%Y-%m-%d')
    else:
        # Default to 1 year ago
        start_date = datetime.now() - timedelta(days=365)
    
    end_date = datetime.strptime(args.end, '%Y-%m-%d')
    expected_dates = get_trading_days(start_date, end_date)
    
    logger.info(f"Analyzing date range: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
    logger.info(f"Expected trading days: {len(expected_dates)}")
    
    # Analyze each symbol
    results = []
    complete_symbols = []
    gap_symbols = []
    missing_symbols = []
    
    print(f"\n{'='*80}")
    print(f"DATA GAP ANALYSIS REPORT")
    print(f"{'='*80}")
    print(f"Analysis Period: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
    print(f"Expected Trading Days: {len(expected_dates)}")
    print(f"Symbols Analyzed: {len(symbols)}")
    print(f"{'='*80}")
    
    for symbol in symbols:
        result = analyze_symbol(symbol, args.cache_dir, expected_dates, args.min_gap_size)
        results.append(result)
        
        if result['status'] == 'COMPLETE':
            complete_symbols.append(symbol)
        elif result['status'] == 'GAPS_FOUND':
            gap_symbols.append(symbol)
        else:
            missing_symbols.append(symbol)
        
        # Print symbol details
        if args.verbose or result['status'] != 'COMPLETE':
            print(f"\n📊 {symbol}:")
            print(f"   Status: {result['status']}")
            print(f"   Data Coverage: {result['available_count']}/{result['expected_count']} days ({result['available_count']/result['expected_count']*100:.1f}%)")
            
            if result['first_date'] and result['last_date']:
                print(f"   Date Range: {result['first_date']} to {result['last_date']}")
            
            if result['gaps']:
                print(f"   Gaps Found: {len(result['gaps'])}")
                for gap_start, gap_end, gap_size in result['gaps']:
                    if gap_start == gap_end:
                        print(f"     • {gap_start} (1 day)")
                    else:
                        print(f"     • {gap_start} to {gap_end} ({gap_size} days)")
    
    # Summary
    print(f"\n{'='*80}")
    print(f"SUMMARY")
    print(f"{'='*80}")
    print(f"✅ Complete Data: {len(complete_symbols)} symbols")
    if complete_symbols:
        print(f"   {', '.join(complete_symbols[:10])}{'...' if len(complete_symbols) > 10 else ''}")
    
    print(f"⚠️  Gaps Found: {len(gap_symbols)} symbols")
    if gap_symbols:
        print(f"   {', '.join(gap_symbols[:10])}{'...' if len(gap_symbols) > 10 else ''}")
    
    print(f"❌ Missing Data: {len(missing_symbols)} symbols")
    if missing_symbols:
        print(f"   {', '.join(missing_symbols[:10])}{'...' if len(missing_symbols) > 10 else ''}")
    
    # Generate fix commands if requested
    if args.fix and (gap_symbols or missing_symbols):
        print(f"\n{'='*80}")
        print(f"RECOMMENDED FIX COMMANDS")
        print(f"{'='*80}")
        
        problem_results = [r for r in results if r['status'] != 'COMPLETE']
        fix_commands = generate_fix_commands(problem_results)
        
        for cmd in fix_commands:
            print(cmd)
        
        # Save to file
        fix_file = f"fix_data_gaps_{datetime.now().strftime('%Y%m%d_%H%M')}.sh"
        with open(fix_file, 'w') as f:
            f.write("#!/bin/bash\n")
            f.write("# Data gap fix commands generated by detect_gaps.py\n")
            f.write(f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            for cmd in fix_commands:
                f.write(cmd + "\n")
        
        print(f"\n💾 Fix commands saved to: {fix_file}")
        print(f"   Run with: bash {fix_file}")
    
    print(f"\n{'='*80}")
    
    # Exit with error code if gaps found
    if gap_symbols or missing_symbols:
        logger.warning(f"Data gaps detected in {len(gap_symbols + missing_symbols)} symbols")
        sys.exit(1)
    else:
        logger.info("✅ No data gaps detected")

if __name__ == "__main__":
    main()
