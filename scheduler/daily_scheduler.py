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

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

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
        self.cache_dir = "cache"
    
    def is_new_symbol(self, symbol: str, min_data_points: int = 250, deployment_mode: bool = False) -> bool:
        """
        Check if a symbol needs historical data (new or insufficient data)
        Returns True if symbol needs historical data pull
        
        Args:
            symbol: Stock symbol to check
            min_data_points: Minimum data points required (deprecated, using coverage analysis)
            deployment_mode: If True, skip freshness checks to avoid massive pulls during deployment
        """
        cache_file = os.path.join(self.cache_dir, f"{symbol}_historical.json")
        
        if not os.path.exists(cache_file):
            logger.info(f"🆕 NEW SYMBOL: {symbol} - no cache file exists")
            return True

        try:
            with open(cache_file, 'r') as f:
                data = json.load(f)
                data_points = data.get('data_points', [])
                
                if not data_points:
                    logger.info(f"� EMPTY CACHE: {symbol} cache is empty")
                    return True
                
                # Use robust coverage analysis for the last 5 years
                target_start_date = datetime.now() - timedelta(days=365 * 5)
                today = datetime.now()
                
                # Pass deployment_mode to skip freshness checks during deployment
                coverage_result = self._analyze_data_coverage(
                    symbol, data_points, target_start_date, today, 
                    skip_freshness_check=deployment_mode
                )
                
                if coverage_result['needs_historical_pull']:
                    logger.info(f"� COVERAGE ANALYSIS: {symbol} {coverage_result['reason']}")
                    return True
                else:
                    logger.info(f"✅ SUFFICIENT COVERAGE: {symbol} {coverage_result['summary']}")
                    return False
                
        except Exception as e:
            logger.warning(f"❌ CACHE ERROR: Error reading cache file for {symbol}: {e}")
            return True
    
    def get_missing_date_range(self, symbol: str, target_start_date: datetime) -> tuple[datetime, datetime]:
        """
        Determine what date range is missing for a symbol using intelligent gap analysis
        Returns (start_date, end_date) for the missing data range
        """
        cache_file = os.path.join(self.cache_dir, f"{symbol}_historical.json")
        
        logger.info(f"🔍 GAP ANALYSIS: Analyzing {symbol} for missing date ranges")
        
        if not os.path.exists(cache_file):
            logger.info(f"❌ NO CACHE: {symbol} cache file does not exist, need full range {target_start_date.date()} to {datetime.now().date()}")
            return target_start_date, datetime.now()

        try:
            with open(cache_file, 'r') as f:
                data = json.load(f)
                data_points = data.get('data_points', [])
                
                if not data_points:
                    logger.info(f"📭 EMPTY CACHE: {symbol} cache is empty, need full range")
                    return target_start_date, datetime.now()
                
                # Use intelligent gap identification
                today = datetime.now()
                missing_ranges = self._identify_missing_date_ranges(symbol, data_points, target_start_date, today)
                
                if not missing_ranges:
                    logger.info(f"✅ NO GAPS: {symbol} has complete coverage")
                    return None, None
                
                # Find the largest gap that needs filling
                largest_gap = max(missing_ranges, key=lambda r: (r[1] - r[0]).days)
                gap_days = (largest_gap[1] - largest_gap[0]).days
                
                logger.info(f"🎯 LARGEST GAP: {symbol} missing {gap_days} days from {largest_gap[0].date()} to {largest_gap[1].date()}")
                
                # If the largest gap is small (< 30 days), fill all gaps by extending range
                if gap_days < 30 and len(missing_ranges) > 1:
                    overall_start = min(r[0] for r in missing_ranges)
                    overall_end = max(r[1] for r in missing_ranges)
                    logger.info(f"� CONSOLIDATING: Filling all gaps from {overall_start.date()} to {overall_end.date()}")
                    return overall_start, overall_end
                
                return largest_gap
                
        except Exception as e:
            logger.warning(f"Error reading cache file for {symbol}: {e}")
            return target_start_date, datetime.now()

    def fetch_initial_historical_data(self, symbol: str) -> bool:
        """
        Fetch 5 years of historical data for a new symbol, only requesting missing data
        Returns True if successful, False otherwise
        """
        logger.info(f"📈 HISTORICAL DATA FETCH: Starting for {symbol}")
        
        try:
            # Target is 5 years of data
            target_start_date = datetime.now() - timedelta(days=365 * 5)  # 5 years
            
            # Check what data range is actually missing
            start_date, end_date = self.get_missing_date_range(symbol, target_start_date)
            
            if start_date is None or end_date is None:
                logger.info(f"✅ SUFFICIENT DATA: {symbol} already has enough historical data")
                return True

            days_to_fetch = (end_date - start_date).days
            logger.info(f"🎯 HISTORICAL FETCH RANGE: {symbol} needs {days_to_fetch} days from {start_date.date()} to {end_date.date()}")
            
            historical_data = self.market_data.get_batch_data([symbol], start_date, end_date, force_refresh=True)
            
            if symbol in historical_data and historical_data[symbol] and historical_data[symbol].data_points:
                data_points = historical_data[symbol].data_points
                logger.info(f"Successfully fetched {len(data_points)} data points for {symbol}")
                
                # Store all data points in database
                for data_point in data_points:
                    daily_snapshot = DailySnapshot(
                        symbol=symbol,
                        date=data_point.date,
                        open=data_point.open,
                        high=data_point.high,
                        low=data_point.low,
                        close=data_point.close,
                        volume=data_point.volume,
                        adjusted_close=data_point.close,
                        strategy_signals={}
                    )
                    self.db.save_daily_snapshot(daily_snapshot)
                
                return True
            else:
                logger.error(f"No historical data returned for {symbol}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to fetch initial historical data for {symbol}: {e}")
            return False
    
    def fetch_latest_data(self, symbol: str, date: Optional[datetime] = None, prioritize_refresh: bool = False) -> Optional[DailySnapshot]:
        """
        Fetch latest market data for a symbol using Yahoo Finance API.
        Only fetches data that is actually missing to minimize API calls.
        
        Args:
            symbol: Stock symbol to fetch
            date: Target date
            prioritize_refresh: If True, focus on filling gaps and refreshing stale data
        """
        if date is None:
            date = datetime.now()
        
        logger.info(f"📊 FETCH REQUEST: {symbol} for date {date.date()}")
        if prioritize_refresh:
            logger.info(f"🔄 REFRESH MODE: Prioritizing data gap detection and fills")
        
        # Check if this is a new symbol that needs initial historical data
        if self.is_new_symbol(symbol):
            logger.info(f"🆕 HISTORICAL PULL TRIGGERED: {symbol} needs initial historical data")
            if not self.fetch_initial_historical_data(symbol):
                logger.error(f"❌ HISTORICAL PULL FAILED: {symbol}")
                return None
        else:
            logger.info(f"✅ EXISTING SYMBOL: {symbol} has sufficient historical data")
        
        # On non-trading days with refresh priority, check for data gaps
        if prioritize_refresh:
            self._check_and_fill_data_gaps(symbol, date)
        
        # Check if we already have data for this date
        date_str = date.strftime('%Y-%m-%d')
        existing_data = self.db.get_daily_snapshot(symbol, date_str)
        if existing_data and not prioritize_refresh:
            logger.info(f"💾 CACHE HIT: Data already exists for {symbol} on {date.date()}")
            return existing_data

        try:
            # Get the latest date we have in the database for this symbol
            latest_db_date = self.db.get_latest_date(symbol)
            
            if latest_db_date:
                # Only fetch from the day after our latest data
                last_date = datetime.strptime(latest_db_date, '%Y-%m-%d')
                start_date = last_date + timedelta(days=1)
                
                # Skip if we're already up to date
                if start_date > date:
                    logger.info(f"✅ UP TO DATE: {symbol} already has data through {latest_db_date}")
                    # Return the most recent data we have
                    return self.db.get_daily_snapshot(symbol, latest_db_date)
                
                logger.info(f"🎯 INCREMENTAL UPDATE: {symbol} fetching from {start_date.date()} to {date.date()} (last data: {latest_db_date})")
            else:
                # No data in DB, fetch last 5 days as fallback
                start_date = date - timedelta(days=5)
                logger.info(f"📭 NO DB DATA: {symbol} fetching last 5 days")
            
            end_date = date
            
            # Use incremental update - this will only fetch missing dates
            historical_data = self.market_data.get_batch_data_with_incremental_update(
                [symbol], start_date, end_date, force_refresh=False, is_daily_update=True
            )
            
            if symbol in historical_data and historical_data[symbol] and historical_data[symbol].data_points:
                # Store all new data points in the database
                new_points_count = 0
                latest_snapshot = None
                
                for data_point in historical_data[symbol].data_points:
                    # Only save points we don't already have
                    if not self.db.get_daily_snapshot(symbol, data_point.date):
                        daily_snapshot = DailySnapshot(
                            symbol=symbol,
                            date=data_point.date,
                            open=data_point.open,
                            high=data_point.high,
                            low=data_point.low,
                            close=data_point.close,
                            volume=data_point.volume,
                            adjusted_close=data_point.close,
                            strategy_signals={}
                        )
                        self.db.save_daily_snapshot(daily_snapshot)
                        new_points_count += 1
                        latest_snapshot = daily_snapshot
                
                if new_points_count > 0:
                    logger.info(f"✅ STORED: {new_points_count} new data points for {symbol}")
                else:
                    logger.info(f"✅ NO NEW DATA: {symbol} - all fetched data already in database")
                
                # Return the most recent snapshot
                if latest_snapshot:
                    return latest_snapshot
                else:
                    # Return existing data if no new points
                    return self.db.get_daily_snapshot(symbol, historical_data[symbol].data_points[-1].date)
            else:
                logger.warning(f"No data returned for {symbol}")
                return None
                
        except Exception as e:
            logger.error(f"Failed to fetch data for {symbol}: {e}")
            return None
    
    def fetch_all_symbols(self, symbols: List[str], date: Optional[datetime] = None, prioritize_refresh: bool = False) -> Dict[str, Optional[DailySnapshot]]:
        """
        Fetch data for all symbols.
        
        Args:
            symbols: List of symbols to fetch
            date: Target date
            prioritize_refresh: If True (non-trading days), focus on refreshing stale data
        """
        results = {}
        
        if prioritize_refresh:
            logger.info("Prioritizing data refresh and gap filling (non-trading day)")
        
        for symbol in symbols:
            try:
                data = self.fetch_latest_data(symbol, date, prioritize_refresh=prioritize_refresh)
                results[symbol] = data
            except Exception as e:
                logger.error(f"Failed to fetch data for {symbol}: {e}")
                results[symbol] = None
        
        return results

    def _analyze_data_coverage(self, symbol: str, data_points: list, target_start_date: datetime, end_date: datetime, skip_freshness_check: bool = False) -> dict:
        """
        Analyze data coverage within the target date range to identify gaps
        Returns detailed analysis of what data is missing
        
        Args:
            symbol: Stock symbol
            data_points: List of historical data points
            target_start_date: Start of target window (usually 5 years ago)
            end_date: End of target window (usually today)
            skip_freshness_check: If True, skip the "stale data" check (useful for deployments)
        """
        if not data_points:
            return {
                'needs_historical_pull': True,
                'reason': 'has no data points',
                'summary': 'empty cache'
            }
        
        # Convert data points to datetime objects and sort
        dates = []
        for dp in data_points:
            try:
                dates.append(datetime.strptime(dp['date'], '%Y-%m-%d'))
            except:
                continue
        
        if not dates:
            return {
                'needs_historical_pull': True,
                'reason': 'has no valid date entries',
                'summary': 'corrupt cache'
            }
        
        dates.sort()
        earliest_data = dates[0]
        latest_data = dates[-1]
        
        # Check 1: Is data recent enough (within last 10 business days)?
        # Skip this check during deployments to avoid massive data pulls due to stale cache
        if not skip_freshness_check:
            days_since_latest = (end_date - latest_data).days
            if days_since_latest > 14:  # More than 2 weeks old
                return {
                    'needs_historical_pull': True,
                    'reason': f'latest data is {days_since_latest} days old (need recent data)',
                    'summary': f'{len(dates)} points but stale'
                }
        else:
            logger.info(f"🚀 DEPLOYMENT MODE: Skipping freshness check for {symbol} (latest data: {latest_data.date()})")
        
        # Check 2: Do we have data coverage within the 5-year window?
        window_start = max(target_start_date, earliest_data)  # Don't go before our earliest data
        window_end = min(end_date, latest_data)  # Don't go beyond our latest data
        
        # Check if we have reasonable coverage in the 5-year window
        dates_in_window = [d for d in dates if window_start <= d <= window_end]
        
        if not dates_in_window:
            return {
                'needs_historical_pull': True,
                'reason': 'has no data within the 5-year target window',
                'summary': f'{len(dates)} points but outside target range'
            }
        
        # Check 3: Coverage density - do we have reasonable data density?
        window_days = (window_end - window_start).days
        coverage_ratio = len(dates_in_window) / max(window_days / 7, 1)  # Assume ~1 data point per week
        
        if len(dates_in_window) < 100:  # Need at least 100 data points for analysis
            return {
                'needs_historical_pull': True,
                'reason': f'only {len(dates_in_window)} data points in 5-year window (need at least 100)',
                'summary': f'insufficient data density'
            }
        
        # Check 4: Look for significant gaps within the window
        dates_in_window.sort()
        large_gaps = []
        
        for i in range(1, len(dates_in_window)):
            gap_days = (dates_in_window[i] - dates_in_window[i-1]).days
            if gap_days > 60:  # Gap larger than 2 months
                large_gaps.append(gap_days)
        
        if len(large_gaps) > 3:  # More than 3 large gaps
            return {
                'needs_historical_pull': True,
                'reason': f'has {len(large_gaps)} gaps larger than 60 days in data coverage',
                'summary': f'{len(dates_in_window)} points but fragmented'
            }
        
        # Check 5: Does our window extend back far enough?
        window_span_years = window_days / 365.25
        if window_span_years < 2.5:  # Less than 2.5 years of coverage
            return {
                'needs_historical_pull': True,
                'reason': f'only {window_span_years:.1f} years of coverage in target window (need at least 2.5)',
                'summary': f'insufficient time span'
            }
        
        # All checks passed - we have sufficient coverage
        return {
            'needs_historical_pull': False,
            'reason': 'sufficient coverage',
            'summary': f'{len(dates_in_window)} points over {window_span_years:.1f} years with {len(large_gaps)} gaps'
        }

    def _identify_missing_date_ranges(self, symbol: str, data_points: list, target_start_date: datetime, end_date: datetime) -> list:
        """
        Identify specific date ranges that are missing within the target window
        Returns list of (start_date, end_date) tuples for missing ranges
        """
        if not data_points:
            return [(target_start_date, end_date)]
        
        # Convert and sort dates
        dates = []
        for dp in data_points:
            try:
                dates.append(datetime.strptime(dp['date'], '%Y-%m-%d'))
            except:
                continue
        
        if not dates:
            return [(target_start_date, end_date)]
        
        dates.sort()
        missing_ranges = []
        
        # Check if we need data before our earliest point
        if dates[0] > target_start_date:
            missing_ranges.append((target_start_date, dates[0]))
        
        # Check for gaps within our data
        for i in range(1, len(dates)):
            gap_days = (dates[i] - dates[i-1]).days
            if gap_days > 7:  # Gap larger than a week
                missing_ranges.append((dates[i-1], dates[i]))
        
        # Check if we need data after our latest point
        if dates[-1] < end_date:
            missing_ranges.append((dates[-1], end_date))
        
        return missing_ranges
    
    def _check_and_fill_data_gaps(self, symbol: str, date: datetime) -> bool:
        """
        Check for data gaps and fill them if needed (useful on non-trading days)
        Returns True if gaps were found and filled
        """
        logger.info(f"🔍 GAP CHECK: Analyzing {symbol} for data gaps")
        
        try:
            # Get the missing date range for this symbol
            target_start_date = date - timedelta(days=365 * 5)  # 5 years back
            start_date, end_date = self.get_missing_date_range(symbol, target_start_date)
            
            if start_date is None or end_date is None:
                logger.info(f"✅ NO GAPS: {symbol} has complete data coverage")
                return False
            
            # Fill the identified gap
            gap_days = (end_date - start_date).days
            logger.info(f"🔄 FILLING GAP: {symbol} missing {gap_days} days from {start_date.date()} to {end_date.date()}")
            
            # Use the market data API to fill the gap
            historical_data = self.market_data.get_batch_data_with_incremental_update(
                [symbol], start_date, end_date, force_refresh=True, is_daily_update=False
            )
            
            if symbol in historical_data and historical_data[symbol]:
                points_filled = len(historical_data[symbol].data_points)
                logger.info(f"✅ GAP FILLED: Added {points_filled} data points for {symbol}")
                return True
            else:
                logger.warning(f"❌ GAP FILL FAILED: No data returned for {symbol}")
                return False
                
        except Exception as e:
            logger.error(f"❌ GAP FILL ERROR: Failed to check/fill gaps for {symbol}: {e}")
            return False
    
    def sync_cache_with_database(self, symbol: str) -> bool:
        """
        Synchronize file cache with database for a symbol.
        Rebuilds the cache file from database data if they're out of sync.
        Returns True if sync was successful.
        """
        logger.info(f"🔄 CACHE SYNC: Synchronizing cache for {symbol}")
        
        try:
            from market_data.data_types import DataPoint, HistoricalData
            
            # Get all data from database
            db_data = self.db.get_symbol_data(symbol)
            
            if not db_data:
                logger.warning(f"📭 NO DB DATA: {symbol} has no data in database")
                return False
            
            # Convert database snapshots to DataPoints
            data_points = []
            for snapshot in db_data:
                data_points.append(DataPoint(
                    date=snapshot.date,
                    open=snapshot.open,
                    high=snapshot.high,
                    low=snapshot.low,
                    close=snapshot.close,
                    volume=snapshot.volume
                ))
            
            # Sort by date
            data_points.sort(key=lambda x: x.date)
            
            # Create HistoricalData object
            historical_data = HistoricalData(symbol=symbol, data_points=data_points)
            
            # Write to cache file
            cache_file = os.path.join(self.cache_dir, f"{symbol}_historical.json")
            with open(cache_file, 'w') as f:
                json.dump(historical_data.to_dict(), f)
            
            logger.info(f"✅ CACHE SYNCED: {symbol} - wrote {len(data_points)} points to cache")
            return True
            
        except Exception as e:
            logger.error(f"❌ CACHE SYNC ERROR: Failed to sync cache for {symbol}: {e}")
            return False
    
    def sync_all_caches(self, symbols: List[str] = None) -> Dict[str, bool]:
        """
        Synchronize cache files with database for all symbols.
        Returns dict of {symbol: success_status}
        """
        if symbols is None:
            # Get all symbols from config
            from config.config_manager import ConfigManager
            config_manager = ConfigManager()
            config = config_manager.get_config()
            symbols = [s.symbol for s in config.symbols if s.enabled]
        
        logger.info(f"🔄 SYNC ALL: Synchronizing cache for {len(symbols)} symbols")
        
        results = {}
        for symbol in symbols:
            results[symbol] = self.sync_cache_with_database(symbol)
        
        success_count = sum(1 for v in results.values() if v)
        logger.info(f"✅ SYNC COMPLETE: {success_count}/{len(symbols)} symbols synced successfully")
        
        return results
    
    def rebuild_cache_from_api(self, symbol: str, years: int = 5) -> bool:
        """
        Rebuild cache by fetching fresh data from API.
        Useful when cache is corrupted or needs full refresh.
        """
        logger.info(f"🔄 REBUILD: Fetching fresh data for {symbol} ({years} years)")
        
        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=365 * years)
            
            # Force refresh from API
            historical_data = self.market_data.get_batch_data(
                [symbol], start_date, end_date, force_refresh=True
            )
            
            if symbol in historical_data and historical_data[symbol]:
                data_points = historical_data[symbol].data_points
                
                # Store all points in database
                for dp in data_points:
                    snapshot = DailySnapshot(
                        symbol=symbol,
                        date=dp.date,
                        open=dp.open,
                        high=dp.high,
                        low=dp.low,
                        close=dp.close,
                        volume=dp.volume,
                        adjusted_close=dp.close,
                        strategy_signals={}
                    )
                    self.db.save_daily_snapshot(snapshot)
                
                logger.info(f"✅ REBUILT: {symbol} - fetched and stored {len(data_points)} points")
                return True
            else:
                logger.warning(f"❌ REBUILD FAILED: No data returned for {symbol}")
                return False
                
        except Exception as e:
            logger.error(f"❌ REBUILD ERROR: Failed to rebuild cache for {symbol}: {e}")
            return False

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
    
    def run_daily_workflow(self, date: Optional[datetime] = None, is_trading_day: bool = True) -> Dict:
        """
        Run the complete daily workflow.
        
        Args:
            date: Target date for analysis
            is_trading_day: Whether today is a trading day (affects data fetching strategy)
        """
        if date is None:
            date = datetime.now()
        
        logger.info(f"Starting daily workflow for {date.date()}")
        if not is_trading_day:
            logger.info("Note: Running on non-trading day - will focus on analysis and maintenance")
        
        # Get enabled symbols from configuration
        config = self.config_manager.get_config()
        symbols = [s.symbol for s in config.symbols if s.enabled]
        
        logger.info(f"Processing {len(symbols)} symbols: {', '.join(symbols)}")
        
        results = {
            'date': date,
            'data': {},
            'strategies': {},
            'performance': {},
            'errors': [],
            'is_trading_day': is_trading_day
        }
        
        try:
            # Step 1: Fetch latest market data (adjusted for trading day status)
            if is_trading_day:
                logger.info("Step 1: Fetching market data (trading day)")
            else:
                logger.info("Step 1: Checking and refreshing market data (non-trading day)")
            
            data_results = self.data_collector.fetch_all_symbols(symbols, date, prioritize_refresh=not is_trading_day)
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
