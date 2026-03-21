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
            
            # ──── Portfolio / Plaid tables ────────────────────────────────────
            # One row per connected Plaid Item (brokerage account link)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS plaid_items (
                    item_id TEXT PRIMARY KEY,
                    access_token_encrypted TEXT NOT NULL,
                    institution_id TEXT,
                    institution_name TEXT,
                    created_at TEXT NOT NULL,
                    last_synced_at TEXT
                )
            """)

            # One row per account within a Plaid Item
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS plaid_accounts (
                    account_id TEXT PRIMARY KEY,
                    item_id TEXT NOT NULL,
                    name TEXT,
                    type TEXT,
                    subtype TEXT,
                    balance_current REAL,
                    balance_available REAL,
                    synced_at TEXT NOT NULL,
                    FOREIGN KEY (item_id) REFERENCES plaid_items(item_id)
                )
            """)

            # Current equity holdings (one row per account+symbol)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS portfolio_positions (
                    account_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    quantity REAL NOT NULL DEFAULT 0,
                    cost_basis REAL,
                    institution_price REAL,
                    institution_value REAL,
                    unrealized_pnl REAL,
                    unrealized_pnl_pct REAL,
                    -- JSON snapshot of the Recommendation active when position was first detected
                    entry_rec_snapshot TEXT,
                    first_detected_at TEXT NOT NULL,
                    last_synced_at TEXT NOT NULL,
                    PRIMARY KEY (account_id, symbol)
                )
            """)

            # Every investment transaction (buy/sell/dividend/etc.)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS investment_transactions (
                    transaction_id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    symbol TEXT,
                    date TEXT NOT NULL,
                    type TEXT,
                    quantity REAL,
                    price REAL,
                    amount REAL,
                    fees REAL DEFAULT 0,
                    synced_at TEXT NOT NULL
                )
            """)

            # Create indexes for better query performance
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_date ON daily_snapshots(date)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_symbol ON daily_snapshots(symbol)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_strategy_perf_symbol ON strategy_performance(symbol)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_comparison_date ON comparison_metrics(date)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_projections_target ON projections(target_date)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_positions_symbol ON portfolio_positions(symbol)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_inv_tx_symbol ON investment_transactions(symbol)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_inv_tx_date ON investment_transactions(date)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_plaid_accounts_item ON plaid_accounts(item_id)")
            
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

                cursor.execute("SELECT COUNT(*) as count FROM portfolio_positions")
                stats['total_positions'] = cursor.fetchone()['count']

                cursor.execute("SELECT COUNT(*) as count FROM investment_transactions")
                stats['total_transactions'] = cursor.fetchone()['count']
                
                return stats
                
        except Exception as e:
            logger.error(f"Error getting database stats: {e}")
            return {}

    # ──── Portfolio / Plaid Operations ────────────────────────────────────────

    def upsert_plaid_item(self, item_id: str, access_token_encrypted: str,
                          institution_id: str = None, institution_name: str = None) -> bool:
        """Store or update a Plaid Item (access token encrypted via Fernet)."""
        try:
            now = datetime.now().isoformat()
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO plaid_items (item_id, access_token_encrypted, institution_id, institution_name, created_at, last_synced_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(item_id) DO UPDATE SET
                        access_token_encrypted = excluded.access_token_encrypted,
                        institution_id = excluded.institution_id,
                        institution_name = excluded.institution_name,
                        last_synced_at = excluded.last_synced_at
                """, (item_id, access_token_encrypted, institution_id, institution_name, now, now))
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error upserting plaid item {item_id}: {e}")
            return False

    def get_plaid_items(self) -> List[Dict[str, Any]]:
        """Return all stored Plaid items."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM plaid_items ORDER BY created_at")
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting plaid items: {e}")
            return []

    def upsert_plaid_account(self, account_id: str, item_id: str, name: str = None,
                              type_: str = None, subtype: str = None,
                              balance_current: float = None, balance_available: float = None) -> bool:
        """Store or update a Plaid account."""
        try:
            now = datetime.now().isoformat()
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO plaid_accounts (account_id, item_id, name, type, subtype, balance_current, balance_available, synced_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(account_id) DO UPDATE SET
                        name = excluded.name,
                        type = excluded.type,
                        subtype = excluded.subtype,
                        balance_current = excluded.balance_current,
                        balance_available = excluded.balance_available,
                        synced_at = excluded.synced_at
                """, (account_id, item_id, name, type_, subtype, balance_current, balance_available, now))
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error upserting plaid account {account_id}: {e}")
            return False

    def get_plaid_accounts(self) -> List[Dict[str, Any]]:
        """Return all synced Plaid accounts."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM plaid_accounts ORDER BY account_id")
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting plaid accounts: {e}")
            return []

    def upsert_portfolio_position(self, account_id: str, symbol: str, quantity: float,
                                   cost_basis: float = None, institution_price: float = None,
                                   institution_value: float = None, entry_rec_snapshot: dict = None) -> bool:
        """Insert or update a portfolio holding. Preserves entry_rec_snapshot on subsequent updates."""
        try:
            now = datetime.now().isoformat()
            snap_json = json.dumps(entry_rec_snapshot) if entry_rec_snapshot else None
            unrealized_pnl = None
            unrealized_pnl_pct = None
            if institution_value is not None and cost_basis is not None and cost_basis > 0:
                unrealized_pnl = institution_value - cost_basis
                unrealized_pnl_pct = unrealized_pnl / cost_basis

            with self.get_connection() as conn:
                cursor = conn.cursor()
                # On conflict: update market values but never overwrite entry_rec_snapshot
                # (it anchors drift detection back to the original trade context)
                cursor.execute("""
                    INSERT INTO portfolio_positions
                        (account_id, symbol, quantity, cost_basis, institution_price, institution_value,
                         unrealized_pnl, unrealized_pnl_pct, entry_rec_snapshot, first_detected_at, last_synced_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(account_id, symbol) DO UPDATE SET
                        quantity = excluded.quantity,
                        cost_basis = excluded.cost_basis,
                        institution_price = excluded.institution_price,
                        institution_value = excluded.institution_value,
                        unrealized_pnl = excluded.unrealized_pnl,
                        unrealized_pnl_pct = excluded.unrealized_pnl_pct,
                        last_synced_at = excluded.last_synced_at
                """, (account_id, symbol, quantity, cost_basis, institution_price, institution_value,
                      unrealized_pnl, unrealized_pnl_pct, snap_json, now, now))
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error upserting portfolio position {symbol}: {e}")
            return False

    def get_portfolio_positions(self, account_id: str = None) -> List[Dict[str, Any]]:
        """Return current portfolio positions, optionally filtered by account."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                if account_id:
                    cursor.execute("SELECT * FROM portfolio_positions WHERE account_id = ? ORDER BY symbol", (account_id,))
                else:
                    cursor.execute("SELECT * FROM portfolio_positions ORDER BY symbol")
                rows = []
                for row in cursor.fetchall():
                    d = dict(row)
                    if d.get('entry_rec_snapshot'):
                        try:
                            d['entry_rec_snapshot'] = json.loads(d['entry_rec_snapshot'])
                        except Exception:
                            pass
                    rows.append(d)
                return rows
        except Exception as e:
            logger.error(f"Error getting portfolio positions: {e}")
            return []

    def upsert_investment_transaction(self, transaction_id: str, account_id: str, symbol: str,
                                       date: str, type_: str, quantity: float = None,
                                       price: float = None, amount: float = None, fees: float = 0) -> bool:
        """Store an investment transaction (idempotent)."""
        try:
            now = datetime.now().isoformat()
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR IGNORE INTO investment_transactions
                        (transaction_id, account_id, symbol, date, type, quantity, price, amount, fees, synced_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (transaction_id, account_id, symbol, date, type_, quantity, price, amount, fees, now))
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error upserting investment transaction {transaction_id}: {e}")
            return False

    def get_investment_transactions(self, symbol: str = None, account_id: str = None,
                                     start_date: str = None, end_date: str = None) -> List[Dict[str, Any]]:
        """Return investment transactions with optional filters."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                query = "SELECT * FROM investment_transactions WHERE 1=1"
                params: List[Any] = []
                if symbol:
                    query += " AND symbol = ?"
                    params.append(symbol)
                if account_id:
                    query += " AND account_id = ?"
                    params.append(account_id)
                if start_date:
                    query += " AND date >= ?"
                    params.append(start_date)
                if end_date:
                    query += " AND date <= ?"
                    params.append(end_date)
                query += " ORDER BY date DESC"
                cursor.execute(query, params)
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting investment transactions: {e}")
            return []
