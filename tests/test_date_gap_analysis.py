#!/usr/bin/env python3
"""
Comprehensive Tests for Date Gap Analysis Functionality

Tests the code that determines what dates are missing from cache and need to be loaded from Yahoo Finance.
These tests define how the gap analysis functions SHOULD work, then we can fix the implementation to pass.
"""

import unittest
import tempfile
import os
import json
import shutil
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
import sys

# Add root directory to path for imports (root directory contains the active files)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from scheduler.daily_scheduler import MarketDataCollector


class TestDateGapAnalysis(unittest.TestCase):
    """Test suite for date gap analysis functionality"""
    
    def setUp(self):
        """Set up test environment with temporary cache directory"""
        self.temp_dir = tempfile.mkdtemp()
        self.cache_dir = os.path.join(self.temp_dir, 'cache')
        os.makedirs(self.cache_dir)
        self.collector = MarketDataCollector()
        self.collector.cache_dir = self.cache_dir
        
        # Common test dates
        self.today = datetime(2025, 6, 8)  # Current date
        self.five_years_ago = self.today - timedelta(days=5*365)  # 5 years ago
        self.two_years_ago = self.today - timedelta(days=2*365)  # 2 years ago
        self.one_year_ago = self.today - timedelta(days=365)  # 1 year ago
        self.one_month_ago = self.today - timedelta(days=30)  # 1 month ago
        self.one_week_ago = self.today - timedelta(days=7)  # 1 week ago
        
    def tearDown(self):
        """Clean up temporary files"""
        shutil.rmtree(self.temp_dir)
    
    def create_cache_file(self, symbol, data_points):
        """Helper to create a cache file with test data"""
        cache_file = os.path.join(self.cache_dir, f"{symbol}_historical.json")
        data = {
            "symbol": symbol,
            "data_points": data_points
        }
        with open(cache_file, 'w') as f:
            json.dump(data, f)
        return cache_file
    
    def create_data_points(self, start_date, end_date, skip_dates=None):
        """Helper to create data points for a date range"""
        skip_dates = skip_dates or []
        skip_dates_str = [d.strftime('%Y-%m-%d') if isinstance(d, datetime) else d for d in skip_dates]
        
        data_points = []
        current = start_date
        while current <= end_date:
            if current.strftime('%Y-%m-%d') not in skip_dates_str:
                # Skip weekends for more realistic test data
                if current.weekday() < 5:  # Monday = 0, Friday = 4
                    data_points.append({
                        "date": current.strftime('%Y-%m-%d'),
                        "open": 100.0,
                        "high": 105.0,
                        "low": 95.0,
                        "close": 102.0,
                        "volume": 1000000
                    })
            current += timedelta(days=1)
        return data_points


class TestIsNewSymbol(TestDateGapAnalysis):
    """Test the is_new_symbol function"""
    
    def test_no_cache_file_is_new_symbol(self):
        """Should return True when no cache file exists"""
        result = self.collector.is_new_symbol("NONEXISTENT")
        self.assertTrue(result, "Symbol with no cache file should be considered new")
    
    def test_empty_cache_file_is_new_symbol(self):
        """Should return True when cache file exists but is empty"""
        self.create_cache_file("EMPTY", [])
        result = self.collector.is_new_symbol("EMPTY")
        self.assertTrue(result, "Symbol with empty cache should be considered new")
    
    def test_insufficient_data_points_is_new_symbol(self):
        """Should return True when cache has too few data points"""
        # Create only 50 data points (less than default 250 minimum)
        data_points = self.create_data_points(
            self.one_year_ago, 
            self.one_year_ago + timedelta(days=70)  # ~50 weekdays
        )
        self.create_cache_file("INSUFFICIENT", data_points)
        
        result = self.collector.is_new_symbol("INSUFFICIENT")
        self.assertTrue(result, "Symbol with insufficient data points should be considered new")
    
    def test_stale_data_is_new_symbol(self):
        """Should return True when latest data is too old"""
        # Create data ending 3 weeks ago (too stale)
        old_end_date = self.today - timedelta(days=21)
        data_points = self.create_data_points(self.two_years_ago, old_end_date)
        self.create_cache_file("STALE", data_points)
        
        with patch('scheduler.daily_scheduler.datetime.now') as mock_now:
            mock_now.return_value = self.today
            result = self.collector.is_new_symbol("STALE")
        
        self.assertTrue(result, "Symbol with stale data should be considered new")
    
    def test_insufficient_time_span_is_new_symbol(self):
        """Should return True when data doesn't span enough years"""
        # Create only 1 year of data (less than required 2.5 years)
        data_points = self.create_data_points(self.one_year_ago, self.today - timedelta(days=1))
        self.create_cache_file("SHORT_SPAN", data_points)
        
        with patch('scheduler.daily_scheduler.datetime.now') as mock_now:
            mock_now.return_value = self.today
            result = self.collector.is_new_symbol("SHORT_SPAN")
        
        self.assertTrue(result, "Symbol with insufficient time span should be considered new")
    
    def test_fragmented_data_is_new_symbol(self):
        """Should return True when data has too many large gaps"""
        # Create data with large gaps (fragmented)
        data_points = []
        
        # Add some data from 3 years ago
        data_points.extend(self.create_data_points(
            self.today - timedelta(days=3*365),
            self.today - timedelta(days=3*365) + timedelta(days=30)
        ))
        
        # Add some data from 2 years ago (gap of ~1 year)
        data_points.extend(self.create_data_points(
            self.today - timedelta(days=2*365),
            self.today - timedelta(days=2*365) + timedelta(days=30)
        ))
        
        # Add some data from 1 year ago (gap of ~1 year)
        data_points.extend(self.create_data_points(
            self.today - timedelta(days=365),
            self.today - timedelta(days=365) + timedelta(days=30)
        ))
        
        # Add recent data (gap of ~11 months)
        data_points.extend(self.create_data_points(
            self.today - timedelta(days=30),
            self.today - timedelta(days=1)
        ))
        
        self.create_cache_file("FRAGMENTED", data_points)
        
        with patch('scheduler.daily_scheduler.datetime.now') as mock_now:
            mock_now.return_value = self.today
            result = self.collector.is_new_symbol("FRAGMENTED")
        
        self.assertTrue(result, "Symbol with fragmented data should be considered new")
    
    def test_sufficient_data_is_not_new_symbol(self):
        """Should return False when symbol has sufficient data coverage"""
        # Create 3 years of complete data ending recently
        data_points = self.create_data_points(
            self.today - timedelta(days=3*365),
            self.today - timedelta(days=1)
        )
        self.create_cache_file("SUFFICIENT", data_points)
        
        # Use a more targeted patch that works with datetime
        with patch('scheduler.daily_scheduler.datetime.now') as mock_now:
            mock_now.return_value = self.today
            result = self.collector.is_new_symbol("SUFFICIENT")
        
        self.assertFalse(result, "Symbol with sufficient data should not be considered new")


class TestGetMissingDateRange(TestDateGapAnalysis):
    """Test the get_missing_date_range function"""
    
    def test_no_cache_file_returns_full_range(self):
        """Should return full target range when no cache file exists"""
        target_start = self.five_years_ago
        
        with patch('scheduler.daily_scheduler.datetime.now') as mock_now:
            mock_now.return_value = self.today
            start, end = self.collector.get_missing_date_range("NONEXISTENT", target_start)
        
        self.assertEqual(start, target_start, "Should start from target start date")
        self.assertEqual(end, self.today, "Should end at current date")
    
    def test_empty_cache_returns_full_range(self):
        """Should return full target range when cache is empty"""
        self.create_cache_file("EMPTY", [])
        target_start = self.five_years_ago
        
        with patch('scheduler.daily_scheduler.datetime.now') as mock_now:
            mock_now.return_value = self.today
            start, end = self.collector.get_missing_date_range("EMPTY", target_start)
        
        self.assertEqual(start, target_start, "Should start from target start date")
        self.assertEqual(end, self.today, "Should end at current date")
    
    def test_missing_recent_data_returns_gap_to_now(self):
        """Should identify gap from last data point to current date"""
        # Create data ending 2 weeks ago
        last_data_date = self.today - timedelta(days=14)
        data_points = self.create_data_points(self.two_years_ago, last_data_date)
        self.create_cache_file("MISSING_RECENT", data_points)
        
        with patch('scheduler.daily_scheduler.datetime.now') as mock_now:
            mock_now.return_value = self.today
            start, end = self.collector.get_missing_date_range("MISSING_RECENT", self.five_years_ago)
        
        self.assertEqual(start, last_data_date, "Should start from last data point")
        self.assertEqual(end, self.today, "Should end at current date")
    
    def test_missing_historical_data_returns_gap_to_first_point(self):
        """Should identify gap from target start to first data point"""
        # Create data starting only 1 year ago
        first_data_date = self.one_year_ago
        data_points = self.create_data_points(first_data_date, self.today - timedelta(days=1))
        self.create_cache_file("MISSING_HISTORICAL", data_points)
        
        with patch('scheduler.daily_scheduler.datetime.now') as mock_now:
            mock_now.return_value = self.today
            start, end = self.collector.get_missing_date_range("MISSING_HISTORICAL", self.five_years_ago)
        
        self.assertEqual(start, self.five_years_ago, "Should start from target start")
        self.assertEqual(end, first_data_date, "Should end at first data point")
    
    def test_internal_gap_returns_largest_gap(self):
        """Should identify the largest internal gap in data"""
        data_points = []
        
        # First chunk: 2 years ago to 23 months ago (1 month of data)
        chunk1_start = self.today - timedelta(days=2*365)
        chunk1_end = self.today - timedelta(days=23*30)
        data_points.extend(self.create_data_points(chunk1_start, chunk1_end))
        
        # Large gap here (22 months)
        
        # Second chunk: 1 month ago to now (1 month of data)
        chunk2_start = self.one_month_ago
        chunk2_end = self.today - timedelta(days=1)
        data_points.extend(self.create_data_points(chunk2_start, chunk2_end))
        
        self.create_cache_file("INTERNAL_GAP", data_points)
        
        with patch('scheduler.daily_scheduler.datetime.now') as mock_now:
            mock_now.return_value = self.today
            start, end = self.collector.get_missing_date_range("INTERNAL_GAP", self.five_years_ago)
        
        # Should return the large gap in the middle
        expected_gap_start = chunk1_end
        expected_gap_end = chunk2_start
        
        self.assertEqual(start, expected_gap_start, "Should identify start of largest gap")
        self.assertEqual(end, expected_gap_end, "Should identify end of largest gap")
    
    def test_multiple_small_gaps_consolidates_range(self):
        """Should consolidate multiple small gaps into one range"""
        data_points = []
        
        # Create data with several small gaps (each < 30 days)
        base_date = self.two_years_ago
        
        # Week 1
        data_points.extend(self.create_data_points(
            base_date, 
            base_date + timedelta(days=7)
        ))
        
        # Gap 1: 10 days
        
        # Week 2
        week2_start = base_date + timedelta(days=17)
        data_points.extend(self.create_data_points(
            week2_start,
            week2_start + timedelta(days=7)
        ))
        
        # Gap 2: 15 days
        
        # Week 3
        week3_start = base_date + timedelta(days=39)
        data_points.extend(self.create_data_points(
            week3_start,
            week3_start + timedelta(days=7)
        ))
        
        # Continue with regular data to present
        data_points.extend(self.create_data_points(
            week3_start + timedelta(days=7),
            self.today - timedelta(days=1)
        ))
        
        self.create_cache_file("SMALL_GAPS", data_points)
        
        with patch('scheduler.daily_scheduler.datetime.now') as mock_now:
            mock_now.return_value = self.today
            start, end = self.collector.get_missing_date_range("SMALL_GAPS", self.five_years_ago)
        
        # Should consolidate to fill all gaps from first missing to last missing
        expected_start = base_date + timedelta(days=7)  # End of first chunk
        expected_end = week3_start + timedelta(days=7)  # Start of final continuous data
        
        self.assertEqual(start, expected_start, "Should consolidate from first gap start")
        self.assertEqual(end, expected_end, "Should consolidate to last gap end")
    
    def test_complete_coverage_returns_none(self):
        """Should return None, None when data coverage is complete"""
        # Create complete data coverage
        data_points = self.create_data_points(
            self.five_years_ago - timedelta(days=30),  # Start before target
            self.today - timedelta(days=1)  # End recently
        )
        self.create_cache_file("COMPLETE", data_points)
        
        with patch('scheduler.daily_scheduler.datetime.now') as mock_now:
            mock_now.return_value = self.today
            start, end = self.collector.get_missing_date_range("COMPLETE", self.five_years_ago)
        
        self.assertIsNone(start, "Should return None for start when coverage is complete")
        self.assertIsNone(end, "Should return None for end when coverage is complete")


class TestAnalyzeDataCoverage(TestDateGapAnalysis):
    """Test the _analyze_data_coverage function"""
    
    def test_empty_data_points_needs_pull(self):
        """Should require historical pull for empty data"""
        result = self.collector._analyze_data_coverage("TEST", [], self.five_years_ago, self.today)
        
        self.assertTrue(result['needs_historical_pull'])
        self.assertIn('no data points', result['reason'])
        self.assertEqual(result['summary'], 'empty cache')
    
    def test_invalid_data_points_needs_pull(self):
        """Should require historical pull for corrupt data"""
        invalid_data = [{"invalid": "data"}, {"no_date": "field"}]
        result = self.collector._analyze_data_coverage("TEST", invalid_data, self.five_years_ago, self.today)
        
        self.assertTrue(result['needs_historical_pull'])
        self.assertIn('no valid date entries', result['reason'])
        self.assertEqual(result['summary'], 'corrupt cache')
    
    def test_stale_data_needs_pull(self):
        """Should require historical pull when data is too old"""
        # Create data ending 3 weeks ago
        old_end = self.today - timedelta(days=21)
        data_points = self.create_data_points(self.two_years_ago, old_end)
        
        result = self.collector._analyze_data_coverage("TEST", data_points, self.five_years_ago, self.today)
        
        self.assertTrue(result['needs_historical_pull'])
        self.assertIn('days old', result['reason'])
        self.assertIn('stale', result['summary'])
    
    def test_data_outside_target_window_needs_pull(self):
        """Should require historical pull when no data in target window"""
        # Create data from 6-7 years ago (outside 5-year window)
        very_old_start = self.today - timedelta(days=7*365)
        very_old_end = self.today - timedelta(days=6*365)
        data_points = self.create_data_points(very_old_start, very_old_end)
        
        result = self.collector._analyze_data_coverage("TEST", data_points, self.five_years_ago, self.today)
        
        self.assertTrue(result['needs_historical_pull'])
        self.assertIn('no data within the 5-year target window', result['reason'])
        self.assertIn('outside target range', result['summary'])
    
    def test_insufficient_data_density_needs_pull(self):
        """Should require historical pull when not enough data points"""
        # Create only 50 data points over 3 years (insufficient density)
        sparse_dates = []
        for i in range(50):
            date = self.today - timedelta(days=i*20)  # Every 20 days
            sparse_dates.append(date)
        
        data_points = []
        for date in sparse_dates:
            if date >= self.five_years_ago:
                data_points.append({
                    "date": date.strftime('%Y-%m-%d'),
                    "open": 100.0, "high": 105.0, "low": 95.0, "close": 102.0, "volume": 1000000
                })
        
        result = self.collector._analyze_data_coverage("TEST", data_points, self.five_years_ago, self.today)
        
        self.assertTrue(result['needs_historical_pull'])
        self.assertIn('data points in 5-year window', result['reason'])
        self.assertIn('insufficient data density', result['summary'])
    
    def test_too_many_large_gaps_needs_pull(self):
        """Should require historical pull when data is too fragmented"""
        data_points = []
        
        # Create 4 large gaps (more than the 3 gap threshold)
        base_date = self.today - timedelta(days=4*365)
        
        for chunk in range(5):  # 5 chunks = 4 gaps between them
            chunk_start = base_date + timedelta(days=chunk * 300)  # 300 days = ~10 months apart
            chunk_end = chunk_start + timedelta(days=30)  # 30 days of data each
            
            if chunk_end <= self.today:
                data_points.extend(self.create_data_points(chunk_start, chunk_end))
        
        result = self.collector._analyze_data_coverage("TEST", data_points, self.five_years_ago, self.today)
        
        self.assertTrue(result['needs_historical_pull'])
        self.assertIn('gaps larger than 60 days', result['reason'])
        self.assertIn('fragmented', result['summary'])
    
    def test_insufficient_time_span_needs_pull(self):
        """Should require historical pull when coverage span is too short"""
        # Create only 2 years of data (less than 2.5 year requirement)
        data_points = self.create_data_points(
            self.two_years_ago,
            self.today - timedelta(days=1)
        )
        
        result = self.collector._analyze_data_coverage("TEST", data_points, self.five_years_ago, self.today)
        
        self.assertTrue(result['needs_historical_pull'])
        self.assertIn('years of coverage', result['reason'])
        self.assertIn('insufficient time span', result['summary'])
    
    def test_sufficient_coverage_no_pull_needed(self):
        """Should not require pull when coverage is sufficient"""
        # Create 4 years of good data with minimal gaps
        data_points = self.create_data_points(
            self.today - timedelta(days=4*365),
            self.today - timedelta(days=1)
        )
        
        result = self.collector._analyze_data_coverage("TEST", data_points, self.five_years_ago, self.today)
        
        self.assertFalse(result['needs_historical_pull'])
        self.assertEqual(result['reason'], 'sufficient coverage')
        self.assertIn('points over', result['summary'])
        self.assertIn('years', result['summary'])


class TestIdentifyMissingDateRanges(TestDateGapAnalysis):
    """Test the _identify_missing_date_ranges function"""
    
    def test_empty_data_returns_full_range(self):
        """Should return full range when no data points exist"""
        ranges = self.collector._identify_missing_date_ranges(
            "TEST", [], self.five_years_ago, self.today
        )
        
        self.assertEqual(len(ranges), 1, "Should return one range for full coverage")
        self.assertEqual(ranges[0][0], self.five_years_ago, "Should start from target start")
        self.assertEqual(ranges[0][1], self.today, "Should end at target end")
    
    def test_missing_before_first_point(self):
        """Should identify gap before first data point"""
        # Create data starting 1 year ago
        data_points = self.create_data_points(
            self.one_year_ago,
            self.today - timedelta(days=1)
        )
        
        ranges = self.collector._identify_missing_date_ranges(
            "TEST", data_points, self.five_years_ago, self.today
        )
        
        # Should find gap from target start to first data point
        gap_before = [r for r in ranges if r[0] == self.five_years_ago]
        self.assertTrue(len(gap_before) > 0, "Should identify gap before first data point")
        self.assertEqual(gap_before[0][1], self.one_year_ago, "Gap should end at first data point")
    
    def test_missing_after_last_point(self):
        """Should identify gap after last data point"""
        # Create data ending 2 weeks ago
        last_data_date = self.today - timedelta(days=14)
        data_points = self.create_data_points(
            self.two_years_ago,
            last_data_date
        )
        
        ranges = self.collector._identify_missing_date_ranges(
            "TEST", data_points, self.five_years_ago, self.today
        )
        
        # Should find gap from last data point to today
        gap_after = [r for r in ranges if r[1] == self.today]
        self.assertTrue(len(gap_after) > 0, "Should identify gap after last data point")
        self.assertEqual(gap_after[0][0], last_data_date, "Gap should start from last data point")
    
    def test_internal_gaps_larger_than_week(self):
        """Should identify internal gaps larger than 7 days"""
        data_points = []
        
        # First chunk
        chunk1_end = self.today - timedelta(days=50)
        data_points.extend(self.create_data_points(
            self.two_years_ago,
            chunk1_end
        ))
        
        # Large gap: 30 days
        
        # Second chunk  
        chunk2_start = self.today - timedelta(days=20)
        data_points.extend(self.create_data_points(
            chunk2_start,
            self.today - timedelta(days=1)
        ))
        
        ranges = self.collector._identify_missing_date_ranges(
            "TEST", data_points, self.five_years_ago, self.today
        )
        
        # Should find the internal gap
        internal_gaps = [r for r in ranges if r[0] == chunk1_end and r[1] == chunk2_start]
        self.assertTrue(len(internal_gaps) > 0, "Should identify internal gap larger than 7 days")
    
    def test_small_gaps_ignored(self):
        """Should ignore gaps of 7 days or less (weekends, holidays)"""
        data_points = []
        
        # Create data with a 5-day gap (should be ignored)
        base_date = self.one_year_ago
        
        # First chunk: 10 days
        chunk1_end = base_date + timedelta(days=10)
        data_points.extend(self.create_data_points(base_date, chunk1_end))
        
        # Small gap: 5 days (should be ignored)
        
        # Second chunk: rest of the year
        chunk2_start = chunk1_end + timedelta(days=5)
        data_points.extend(self.create_data_points(
            chunk2_start,
            self.today - timedelta(days=1)
        ))
        
        ranges = self.collector._identify_missing_date_ranges(
            "TEST", data_points, self.five_years_ago, self.today
        )
        
        # Should not find the small gap, only the gap before data starts
        small_gaps = [r for r in ranges if r[0] == chunk1_end and r[1] == chunk2_start]
        self.assertEqual(len(small_gaps), 0, "Should ignore gaps of 7 days or less")
    
    def test_multiple_gaps_all_identified(self):
        """Should identify all significant gaps in data"""
        data_points = []
        
        # Create data with multiple gaps
        dates = [
            (self.today - timedelta(days=200), self.today - timedelta(days=190)),  # Chunk 1
            (self.today - timedelta(days=170), self.today - timedelta(days=160)),  # Chunk 2 (20-day gap)
            (self.today - timedelta(days=140), self.today - timedelta(days=130)),  # Chunk 3 (20-day gap) 
            (self.today - timedelta(days=20), self.today - timedelta(days=1))      # Chunk 4 (110-day gap)
        ]
        
        for start, end in dates:
            data_points.extend(self.create_data_points(start, end))
        
        ranges = self.collector._identify_missing_date_ranges(
            "TEST", data_points, self.five_years_ago, self.today
        )
        
        # Should find:
        # 1. Gap before first chunk (from 5 years ago to chunk 1 start)
        # 2. Gap between chunk 1 and 2 (20 days)
        # 3. Gap between chunk 2 and 3 (20 days)  
        # 4. Gap between chunk 3 and 4 (110 days)
        
        self.assertGreaterEqual(len(ranges), 4, "Should identify all significant gaps")
    
    def test_continuous_data_no_gaps(self):
        """Should return empty list when data is continuous"""
        # Create continuous data covering full range
        data_points = self.create_data_points(
            self.five_years_ago - timedelta(days=10),  # Start before target
            self.today + timedelta(days=1)  # End after target
        )
        
        ranges = self.collector._identify_missing_date_ranges(
            "TEST", data_points, self.five_years_ago, self.today
        )
        
        self.assertEqual(len(ranges), 0, "Should return no gaps for continuous data")


class TestIntegrationScenarios(TestDateGapAnalysis):
    """Integration tests for realistic scenarios"""
    
    def test_new_symbol_workflow(self):
        """Test complete workflow for a new symbol"""
        # New symbol - no cache file
        is_new = self.collector.is_new_symbol("NEWSYMBOL")
        self.assertTrue(is_new, "New symbol should be identified as new")
        
        # Get missing range for new symbol
        with patch('scheduler.daily_scheduler.datetime.now') as mock_now:
            mock_now.return_value = self.today
            start, end = self.collector.get_missing_date_range("NEWSYMBOL", self.five_years_ago)
        
        self.assertEqual(start, self.five_years_ago, "Should request full 5-year range")
        self.assertEqual(end, self.today, "Should request up to current date")
    
    def test_existing_symbol_with_recent_gap(self):
        """Test workflow for existing symbol missing recent data"""
        # Create symbol with data ending 2 weeks ago
        last_date = self.today - timedelta(days=14)
        data_points = self.create_data_points(self.today - timedelta(days=3*365), last_date)
        self.create_cache_file("RECENT_GAP", data_points)
        
        # Should identify as needing update (stale data)
        with patch('scheduler.daily_scheduler.datetime.now') as mock_now:
            mock_now.return_value = self.today
            is_new = self.collector.is_new_symbol("RECENT_GAP")
        
        self.assertTrue(is_new, "Symbol with stale data should need historical pull")
        
        # Should request range to fill recent gap
        with patch('scheduler.daily_scheduler.datetime.now') as mock_now:
            mock_now.return_value = self.today
            start, end = self.collector.get_missing_date_range("RECENT_GAP", self.five_years_ago)
        
        self.assertEqual(start, last_date, "Should start from last data point")
        self.assertEqual(end, self.today, "Should end at current date")
    
    def test_existing_symbol_sufficient_coverage(self):
        """Test workflow for symbol with sufficient coverage"""
        # Create symbol with good 4-year coverage ending yesterday
        data_points = self.create_data_points(
            self.today - timedelta(days=4*365),
            self.today - timedelta(days=1)
        )
        self.create_cache_file("SUFFICIENT", data_points)
        
        # Should not be identified as new
        with patch('scheduler.daily_scheduler.datetime.now') as mock_now:
            mock_now.return_value = self.today
            is_new = self.collector.is_new_symbol("SUFFICIENT")
        
        self.assertFalse(is_new, "Symbol with sufficient coverage should not need historical pull")
        
        # Should return None for missing range
        with patch('scheduler.daily_scheduler.datetime.now') as mock_now:
            mock_now.return_value = self.today
            start, end = self.collector.get_missing_date_range("SUFFICIENT", self.five_years_ago)
        
        self.assertIsNone(start, "Should return None for sufficient coverage")
        self.assertIsNone(end, "Should return None for sufficient coverage")
    
    def test_symbol_with_historical_gap(self):
        """Test workflow for symbol missing historical data"""
        # Create symbol with only recent data (missing historical)
        data_points = self.create_data_points(
            self.one_year_ago,
            self.today - timedelta(days=1)
        )
        self.create_cache_file("HISTORICAL_GAP", data_points)
        
        # Should be identified as needing historical data
        with patch('scheduler.daily_scheduler.datetime.now') as mock_now:
            mock_now.return_value = self.today
            is_new = self.collector.is_new_symbol("HISTORICAL_GAP")
        
        self.assertTrue(is_new, "Symbol missing historical data should need historical pull")
        
        # Should request historical range
        with patch('scheduler.daily_scheduler.datetime.now') as mock_now:
            mock_now.return_value = self.today
            start, end = self.collector.get_missing_date_range("HISTORICAL_GAP", self.five_years_ago)
        
        self.assertEqual(start, self.five_years_ago, "Should start from target start date")
        self.assertEqual(end, self.one_year_ago, "Should end at first data point")


if __name__ == '__main__':
    # Run the tests
    unittest.main(verbosity=2)
