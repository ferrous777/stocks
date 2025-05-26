#!/usr/bin/env python3
"""
Migration script to convert existing JSON cache files to new time-series database
"""
import os
import json
import sys
from datetime import datetime
from typing import Dict, List, Any
import argparse

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from storage.timeseries_db import TimeSeriesDB
from storage.models import DailySnapshot
from storage.adapter import DataAdapter
from market_data.data_types import HistoricalData, DataPoint

class DataMigrator:
    """Migrate existing JSON cache to new database format"""
    
    def __init__(self, cache_dir: str = "cache", db_path: str = "data/timeseries.db"):
        self.cache_dir = cache_dir
        self.db = TimeSeriesDB(db_path)
        self.migrated_count = 0
        self.error_count = 0
        
    def migrate_all(self, dry_run: bool = False):
        """Migrate all historical cache files"""
        print(f"Starting migration from {self.cache_dir}")
        print(f"Target database: {self.db.db_path}")
        
        if dry_run:
            print("DRY RUN - No data will be written to database")
        
        # Find all historical JSON files
        historical_files = []
        if os.path.exists(self.cache_dir):
            for filename in os.listdir(self.cache_dir):
                if filename.endswith('_historical.json'):
                    symbol = filename.replace('_historical.json', '')
                    file_path = os.path.join(self.cache_dir, filename)
                    historical_files.append((symbol, file_path))
        
        print(f"Found {len(historical_files)} historical cache files")
        
        for symbol, file_path in historical_files:
            print(f"\nMigrating {symbol}...")
            try:
                self._migrate_historical_file(symbol, file_path, dry_run)
            except Exception as e:
                print(f"Error migrating {symbol}: {e}")
                self.error_count += 1
        
        # Migration summary
        print("\n" + "="*50)
        print("MIGRATION SUMMARY")
        print("="*50)
        print(f"Files processed: {len(historical_files)}")
        print(f"Records migrated: {self.migrated_count}")
        print(f"Errors: {self.error_count}")
        
        if not dry_run:
            # Show database stats
            stats = self.db.get_database_stats()
            print(f"Database now contains:")
            print(f"  Total snapshots: {stats['total_snapshots']}")
            print(f"  Date range: {stats['date_range']}")
            print(f"  Symbols: {list(stats['snapshots_by_symbol'].keys())}")
    
    def _migrate_historical_file(self, symbol: str, file_path: str, dry_run: bool = False):
        """Migrate a single historical JSON file"""
        with open(file_path, 'r') as f:
            cache_data = json.load(f)
        
        # Parse the cached historical data
        historical_data = self._parse_cache_data(cache_data)
        
        if not historical_data:
            print(f"  No valid data found in {file_path}")
            return
        
        # Convert to snapshots
        snapshots = DataAdapter.historical_to_snapshots(historical_data, symbol)
        
        print(f"  Converting {len(snapshots)} data points...")
        
        if not dry_run:
            # Save to database
            for snapshot in snapshots:
                success = self.db.save_daily_snapshot(snapshot)
                if success:
                    self.migrated_count += 1
                else:
                    print(f"    Failed to save {snapshot.date}")
                    self.error_count += 1
        else:
            # Just count for dry run
            self.migrated_count += len(snapshots)
            print(f"  Would migrate {len(snapshots)} records")
    
    def _parse_cache_data(self, cache_data: Dict[str, Any]) -> HistoricalData:
        """Parse cached JSON data into HistoricalData object"""
        try:
            # Handle different cache formats
            if 'data_points' in cache_data:
                # New format
                data_points = []
                for point_data in cache_data['data_points']:
                    data_point = DataPoint(
                        date=point_data['date'],
                        open=point_data['open'],
                        high=point_data['high'],
                        low=point_data['low'],
                        close=point_data['close'],
                        volume=point_data['volume']
                    )
                    data_points.append(data_point)
                
                return HistoricalData(
                    symbol=cache_data.get('symbol', ''),
                    data_points=data_points
                )
            
            elif isinstance(cache_data, list):
                # Direct list of data points
                data_points = []
                for point_data in cache_data:
                    if isinstance(point_data, dict) and 'date' in point_data:
                        data_point = DataPoint(
                            date=point_data['date'],
                            open=point_data['open'],
                            high=point_data['high'],
                            low=point_data['low'],
                            close=point_data['close'],
                            volume=point_data['volume']
                        )
                        data_points.append(data_point)
                
                return HistoricalData(
                    symbol='',
                    data_points=data_points
                )
            
            else:
                print(f"  Unknown cache format: {type(cache_data)}")
                return None
                
        except Exception as e:
            print(f"  Error parsing cache data: {e}")
            return None
    
    def verify_migration(self):
        """Verify migration results"""
        print("\nVerifying migration...")
        
        stats = self.db.get_database_stats()
        print(f"Database contains {stats['total_snapshots']} snapshots")
        
        # Check a few samples
        for symbol in list(stats['snapshots_by_symbol'].keys())[:3]:
            latest_date = self.db.get_latest_date(symbol)
            date_range = self.db.get_date_range(symbol)
            
            print(f"  {symbol}: {stats['snapshots_by_symbol'][symbol]} records")
            print(f"    Date range: {date_range[0]} to {date_range[1]}")
            print(f"    Latest: {latest_date}")
            
            # Sample a record
            if latest_date:
                sample = self.db.get_daily_snapshot(symbol, latest_date)
                if sample:
                    print(f"    Sample: Close=${sample.close}, Volume={sample.volume:,}")

def main():
    parser = argparse.ArgumentParser(description='Migrate JSON cache to time-series database')
    parser.add_argument('--cache-dir', default='cache', help='Cache directory path')
    parser.add_argument('--db-path', default='data/timeseries.db', help='Database path')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be migrated without writing')
    parser.add_argument('--verify', action='store_true', help='Verify migration results')
    
    args = parser.parse_args()
    
    migrator = DataMigrator(args.cache_dir, args.db_path)
    
    if args.verify:
        migrator.verify_migration()
    else:
        migrator.migrate_all(args.dry_run)
        if not args.dry_run:
            migrator.verify_migration()

if __name__ == "__main__":
    main()
