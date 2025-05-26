#!/usr/bin/env python3
"""
Daily Operations Wrapper - Run daily market data collection and analysis for any date

This script provides a simple interface for operators to run daily operations
for specific dates, handle backfills, and recover from failed runs.

Usage:
    python run_daily.py                          # Run for today
    python run_daily.py --date 2025-05-23       # Run for specific date
    python run_daily.py --start 2025-05-20 --end 2025-05-23  # Backfill range
    python run_daily.py --dry-run --date 2025-05-23          # Preview only
"""

import argparse
import sys
import os
from datetime import datetime, timedelta
from typing import Optional, List
import logging

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from market_calendar.market_calendar import is_trading_day, MarketType
from config.config_manager import ConfigManager

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('logs/run_daily.log', mode='a')
    ]
)
logger = logging.getLogger(__name__)

def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description='Run daily market operations for any date',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_daily.py                          # Today
  python run_daily.py --date 2025-05-23       # Specific date  
  python run_daily.py --start 2025-05-20 --end 2025-05-23  # Date range
  python run_daily.py --dry-run --date 2025-05-23          # Preview only
  python run_daily.py --validate-only         # Check data integrity only
        """
    )
    
    # Date options
    date_group = parser.add_mutually_exclusive_group()
    date_group.add_argument('--date', type=str, 
                           help='Specific date to process (YYYY-MM-DD)')
    date_group.add_argument('--today', action='store_true',
                           help='Process today (default)')
    
    # Range options
    parser.add_argument('--start', type=str,
                       help='Start date for range processing (YYYY-MM-DD)')
    parser.add_argument('--end', type=str,
                       help='End date for range processing (YYYY-MM-DD)')
    
    # Operation modes
    parser.add_argument('--dry-run', action='store_true',
                       help='Preview operations without executing')
    parser.add_argument('--force', action='store_true',
                       help='Force processing even if data exists')
    parser.add_argument('--validate-only', action='store_true',
                       help='Only validate data integrity, no processing')
    
    # Options
    parser.add_argument('--skip-weekends', action='store_true', default=True,
                       help='Skip non-trading days (default: True)')
    parser.add_argument('--symbols', type=str, nargs='+',
                       help='Process specific symbols only')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Enable verbose logging')
    
    return parser.parse_args()

def validate_date(date_str: str) -> datetime:
    """Validate and parse date string"""
    try:
        date_obj = datetime.strptime(date_str, '%Y-%m-%d')
        
        # Check if date is not in the future
        today = datetime.now().date()
        if date_obj.date() > today:
            raise ValueError(f"Cannot process future date: {date_str}")
            
        return date_obj
    except ValueError as e:
        logger.error(f"Invalid date format '{date_str}': {e}")
        sys.exit(1)

def get_trading_dates(start_date: datetime, end_date: datetime, skip_weekends: bool = True) -> List[datetime]:
    """Get list of trading dates in range"""
    dates = []
    current = start_date
    
    while current <= end_date:
        if not skip_weekends or is_trading_day(current, MarketType.NYSE):
            dates.append(current)
        current += timedelta(days=1)
    
    return dates

def check_data_exists(date_obj: datetime, symbols: Optional[List[str]] = None) -> dict:
    """Check what data already exists for the given date"""
    date_str = date_obj.strftime('%Y-%m-%d')
    cache_dir = 'cache'
    
    if symbols is None:
        # Get symbols from config
        try:
            config_manager = ConfigManager()
            config = config_manager.get_config()
            symbols = [sym.symbol for sym in config.symbols]
        except:
            # Fallback to common symbols
            symbols = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA']
    
    results = {
        'exists': [],
        'missing': [],
        'errors': []
    }
    
    for symbol in symbols:
        cache_file = f"{cache_dir}/{symbol}_historical.json"
        try:
            if os.path.exists(cache_file):
                import json
                with open(cache_file, 'r') as f:
                    data = json.load(f)
                
                # Check if date exists in data
                if 'data_points' in data:
                    points = data['data_points']
                else:
                    points = data
                
                date_found = any(point['date'] == date_str for point in points)
                if date_found:
                    results['exists'].append(symbol)
                else:
                    results['missing'].append(symbol)
            else:
                results['missing'].append(symbol)
        except Exception as e:
            results['errors'].append(f"{symbol}: {e}")
    
    return results

def run_data_collection(date_obj: datetime, symbols: Optional[List[str]] = None, force: bool = False, dry_run: bool = False):
    """Run data collection for specific date"""
    date_str = date_obj.strftime('%Y-%m-%d')
    
    if dry_run:
        logger.info(f"DRY RUN: Would collect data for {date_str}")
        return True
    
    logger.info(f"Collecting market data for {date_str}")
    
    # Build command for main.py
    cmd_parts = [
        sys.executable, 'src/main.py',
        '--source', 'src/data/default_symbols.json',
        '--start', date_str,
        '--end', date_str
    ]
    
    if force:
        cmd_parts.append('--force')
    
    if symbols:
        cmd_parts.extend(['--symbol'] + symbols)
    
    # Execute the command
    import subprocess
    try:
        result = subprocess.run(cmd_parts, capture_output=True, text=True, cwd=os.getcwd())
        
        if result.returncode == 0:
            logger.info(f"✅ Successfully collected data for {date_str}")
            return True
        else:
            logger.error(f"❌ Failed to collect data for {date_str}")
            logger.error(f"Error: {result.stderr}")
            return False
    except Exception as e:
        logger.error(f"❌ Exception during data collection: {e}")
        return False

def main():
    # Ensure logs directory exists
    os.makedirs('logs', exist_ok=True)
    
    args = parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Determine dates to process
    dates_to_process = []
    
    if args.start and args.end:
        # Range processing
        start_date = validate_date(args.start)
        end_date = validate_date(args.end)
        dates_to_process = get_trading_dates(start_date, end_date, args.skip_weekends)
        logger.info(f"Processing date range: {args.start} to {args.end} ({len(dates_to_process)} trading days)")
    elif args.date:
        # Specific date
        date_obj = validate_date(args.date)
        if not args.skip_weekends or is_trading_day(date_obj, MarketType.NYSE):
            dates_to_process = [date_obj]
        else:
            logger.warning(f"Skipping non-trading day: {args.date}")
            return
    else:
        # Today (default)
        today = datetime.now()
        if not args.skip_weekends or is_trading_day(today, MarketType.NYSE):
            dates_to_process = [today]
        else:
            logger.warning("Today is not a trading day")
            return
    
    if not dates_to_process:
        logger.warning("No dates to process")
        return
    
    # Process each date
    success_count = 0
    total_count = len(dates_to_process)
    
    for date_obj in dates_to_process:
        date_str = date_obj.strftime('%Y-%m-%d')
        logger.info(f"\n{'='*50}")
        logger.info(f"Processing: {date_str} ({date_obj.strftime('%A')})")
        logger.info(f"{'='*50}")
        
        # Check existing data
        data_status = check_data_exists(date_obj, args.symbols)
        
        if data_status['exists'] and not args.force:
            logger.info(f"📁 Data already exists for {len(data_status['exists'])} symbols: {', '.join(data_status['exists'][:5])}{'...' if len(data_status['exists']) > 5 else ''}")
            if not data_status['missing']:
                logger.info(f"✅ All data present for {date_str}, skipping (use --force to override)")
                success_count += 1
                continue
        
        if data_status['missing']:
            logger.info(f"📊 Missing data for {len(data_status['missing'])} symbols: {', '.join(data_status['missing'][:5])}{'...' if len(data_status['missing']) > 5 else ''}")
        
        if data_status['errors']:
            logger.warning(f"⚠️  Errors checking {len(data_status['errors'])} symbols: {data_status['errors'][:3]}{'...' if len(data_status['errors']) > 3 else ''}")
        
        # Validate-only mode
        if args.validate_only:
            if data_status['missing'] or data_status['errors']:
                logger.warning(f"❌ Data validation failed for {date_str}")
            else:
                logger.info(f"✅ Data validation passed for {date_str}")
            continue
        
        # Run data collection
        if run_data_collection(date_obj, args.symbols, args.force, args.dry_run):
            success_count += 1
        else:
            logger.error(f"❌ Failed to process {date_str}")
    
    # Summary
    logger.info(f"\n{'='*50}")
    logger.info(f"PROCESSING COMPLETE")
    logger.info(f"{'='*50}")
    logger.info(f"✅ Successfully processed: {success_count}/{total_count} dates")
    
    if success_count < total_count:
        logger.error(f"❌ Failed: {total_count - success_count} dates")
        sys.exit(1)
    else:
        logger.info("🎉 All operations completed successfully!")

if __name__ == "__main__":
    main()
