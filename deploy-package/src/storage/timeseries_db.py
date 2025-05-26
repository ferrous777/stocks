import sqlite3
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Union
from contextlib import contextmanager
import logging

from .models import DailySnapshot, StrategyTimeSeries, ComparisonMetrics, ProjectionData

logger = logging.getLogger(__name__)

class TimeSeriesDB:
    """
    Time-series database wrapper for market data storage.
    Uses SQLite with JSON columns for flexibility and easy migration path.
    Structure: Ticker -> Date -> Data
    """
    
    def __init__(self, db_path: str = "data/timeseries.db"):
        self.db_path = db_path
        self.ensure_db_dir()
        self.init_database()
    
    def ensure_db_dir(self):
        """Ensure database directory exists"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
    
    def init_database(self):
        """Initialize database tables"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Daily snapshots table - main time series data
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS daily_snapshots (
                    symbol TEXT NOT NULL,
                    date TEXT NOT NULL,
                    data TEXT NOT NULL,  -- JSON blob
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (symbol, date)
                )
            """)
            
            # Strategy performance table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS strategy_performance (
                    strategy_name TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    data TEXT NOT NULL,  -- JSON blob
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (strategy_name, symbol, start_date, end_date)
                )
            """)
            
            # Comparison metrics table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS comparison_metrics (
                    symbol TEXT NOT NULL,
                    date TEXT NOT NULL,
                    data TEXT NOT NULL,  -- JSON blob
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (symbol, date)
                )
            """)
            
            # Projections table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS projections (
                    symbol TEXT NOT NULL,
                    projection_date TEXT NOT NULL,
                    target_date TEXT NOT NULL,
                    model_name TEXT NOT NULL,
                    data TEXT NOT NULL,  -- JSON blob
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (symbol, projection_date, target_date, model_name)
                )
            """)
            
            # Create indexes for better query performance
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_date ON daily_snapshots(date)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_symbol ON daily_snapshots(symbol)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_strategy_perf_symbol ON strategy_performance(symbol)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_comparison_date ON comparison_metrics(date)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_projections_target ON projections(target_date)")
            
            conn.commit()
            logger.info("Database initialized successfully")
    
    @contextmanager
    def get_connection(self):
        """Get database connection with proper cleanup"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Enable column access by name
        try:
            yield conn
        finally:
            conn.close()
    
    # Daily Snapshot Operations
    def save_daily_snapshot(self, snapshot: DailySnapshot) -> bool:
        """Save or update a daily snapshot"""
        try:
            snapshot.updated_at = datetime.now().isoformat()
            
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO daily_snapshots 
                    (symbol, date, data, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    snapshot.symbol,
                    snapshot.date,
                    snapshot.to_json(),
                    snapshot.created_at,
                    snapshot.updated_at
                ))
                conn.commit()
                logger.debug(f"Saved snapshot for {snapshot.symbol} on {snapshot.date}")
                return True
                
        except Exception as e:
            logger.error(f"Error saving snapshot for {snapshot.symbol} on {snapshot.date}: {e}")
            return False
    
    def get_daily_snapshot(self, symbol: str, date: str) -> Optional[DailySnapshot]:
        """Get daily snapshot for a specific symbol and date"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT data FROM daily_snapshots 
                    WHERE symbol = ? AND date = ?
                """, (symbol, date))
                
                row = cursor.fetchone()
                if row:
                    return DailySnapshot.from_json(row['data'])
                return None
                
        except Exception as e:
            logger.error(f"Error getting snapshot for {symbol} on {date}: {e}")
            return None
    
    def get_symbol_data(self, symbol: str, start_date: Optional[str] = None, 
                       end_date: Optional[str] = None) -> List[DailySnapshot]:
        """Get all data for a symbol within date range"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                query = "SELECT data FROM daily_snapshots WHERE symbol = ?"
                params = [symbol]
                
                if start_date:
                    query += " AND date >= ?"
                    params.append(start_date)
                
                if end_date:
                    query += " AND date <= ?"
                    params.append(end_date)
                
                query += " ORDER BY date ASC"
                
                cursor.execute(query, params)
                rows = cursor.fetchall()
                
                return [DailySnapshot.from_json(row['data']) for row in rows]
                
        except Exception as e:
            logger.error(f"Error getting symbol data for {symbol}: {e}")
            return []
    
    def get_date_data(self, date: str, symbols: Optional[List[str]] = None) -> List[DailySnapshot]:
        """Get all symbols data for a specific date"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                if symbols:
                    placeholders = ','.join(['?' for _ in symbols])
                    query = f"""
                        SELECT data FROM daily_snapshots 
                        WHERE date = ? AND symbol IN ({placeholders})
                        ORDER BY symbol
                    """
                    params = [date] + symbols
                else:
                    query = "SELECT data FROM daily_snapshots WHERE date = ? ORDER BY symbol"
                    params = [date]
                
                cursor.execute(query, params)
                rows = cursor.fetchall()
                
                return [DailySnapshot.from_json(row['data']) for row in rows]
                
        except Exception as e:
            logger.error(f"Error getting date data for {date}: {e}")
            return []
    
    def get_latest_date(self, symbol: str) -> Optional[str]:
        """Get the latest date for which we have data for a symbol"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT MAX(date) as latest_date FROM daily_snapshots 
                    WHERE symbol = ?
                """, (symbol,))
                
                row = cursor.fetchone()
                return row['latest_date'] if row else None
                
        except Exception as e:
            logger.error(f"Error getting latest date for {symbol}: {e}")
            return None
    
    def get_available_symbols(self) -> List[str]:
        """Get list of all symbols in database"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT DISTINCT symbol FROM daily_snapshots ORDER BY symbol")
                return [row['symbol'] for row in cursor.fetchall()]
                
        except Exception as e:
            logger.error(f"Error getting available symbols: {e}")
            return []
    
    def get_date_range(self, symbol: str) -> Optional[tuple]:
        """Get the date range (min, max) for a symbol"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT MIN(date) as min_date, MAX(date) as max_date 
                    FROM daily_snapshots WHERE symbol = ?
                """, (symbol,))
                
                row = cursor.fetchone()
                if row and row['min_date']:
                    return (row['min_date'], row['max_date'])
                return None
                
        except Exception as e:
            logger.error(f"Error getting date range for {symbol}: {e}")
            return None
    
    # Strategy Performance Operations
    def save_strategy_performance(self, performance: StrategyTimeSeries) -> bool:
        """Save strategy performance data"""
        try:
            now = datetime.now().isoformat()
            
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO strategy_performance 
                    (strategy_name, symbol, start_date, end_date, data, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    performance.strategy_name,
                    performance.symbol,
                    performance.start_date,
                    performance.end_date,
                    json.dumps(performance.__dict__),
                    now,
                    now
                ))
                conn.commit()
                return True
                
        except Exception as e:
            logger.error(f"Error saving strategy performance: {e}")
            return False
    
    # Comparison Metrics Operations
    def save_comparison_metrics(self, metrics: ComparisonMetrics) -> bool:
        """Save comparison metrics"""
        try:
            now = datetime.now().isoformat()
            
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO comparison_metrics 
                    (symbol, date, data, created_at)
                    VALUES (?, ?, ?, ?)
                """, (
                    metrics.base_symbol,
                    metrics.date,
                    json.dumps(metrics.__dict__),
                    now
                ))
                conn.commit()
                return True
                
        except Exception as e:
            logger.error(f"Error saving comparison metrics: {e}")
            return False
    
    # Projection Operations
    def save_projection(self, projection: ProjectionData) -> bool:
        """Save projection data"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO projections 
                    (symbol, projection_date, target_date, model_name, data, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    projection.symbol,
                    projection.projection_date,
                    projection.target_date,
                    projection.model_name,
                    json.dumps(projection.__dict__),
                    projection.created_at
                ))
                conn.commit()
                return True
                
        except Exception as e:
            logger.error(f"Error saving projection: {e}")
            return False
    
    # Utility Operations
    def cleanup_old_data(self, days_to_keep: int = 365) -> bool:
        """Remove data older than specified days"""
        try:
            cutoff_date = (datetime.now() - timedelta(days=days_to_keep)).strftime('%Y-%m-%d')
            
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Clean old snapshots
                cursor.execute("DELETE FROM daily_snapshots WHERE date < ?", (cutoff_date,))
                
                # Clean old comparisons
                cursor.execute("DELETE FROM comparison_metrics WHERE date < ?", (cutoff_date,))
                
                # Clean old projections
                cursor.execute("DELETE FROM projections WHERE target_date < ?", (cutoff_date,))
                
                conn.commit()
                logger.info(f"Cleaned data older than {cutoff_date}")
                return True
                
        except Exception as e:
            logger.error(f"Error cleaning old data: {e}")
            return False
    
    def get_database_stats(self) -> Dict[str, Any]:
        """Get database statistics"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                stats = {}
                
                # Count of snapshots by symbol
                cursor.execute("""
                    SELECT symbol, COUNT(*) as count 
                    FROM daily_snapshots 
                    GROUP BY symbol 
                    ORDER BY count DESC
                """)
                stats['snapshots_by_symbol'] = dict(cursor.fetchall())
                
                # Date range
                cursor.execute("SELECT MIN(date) as min_date, MAX(date) as max_date FROM daily_snapshots")
                row = cursor.fetchone()
                stats['date_range'] = (row['min_date'], row['max_date']) if row else None
                
                # Total counts
                cursor.execute("SELECT COUNT(*) as count FROM daily_snapshots")
                stats['total_snapshots'] = cursor.fetchone()['count']
                
                cursor.execute("SELECT COUNT(*) as count FROM strategy_performance")
                stats['total_strategy_records'] = cursor.fetchone()['count']
                
                cursor.execute("SELECT COUNT(*) as count FROM comparison_metrics")
                stats['total_comparison_records'] = cursor.fetchone()['count']
                
                cursor.execute("SELECT COUNT(*) as count FROM projections")
                stats['total_projections'] = cursor.fetchone()['count']
                
                return stats
                
        except Exception as e:
            logger.error(f"Error getting database stats: {e}")
            return {}
