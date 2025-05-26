"""
Data Aggregation & Rollup System

Provides functions for aggregating daily data into weekly, monthly periods
and calculating rolling window metrics for performance analysis.
"""
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
import statistics
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from storage.timeseries_db import TimeSeriesDB
from storage.models import DailySnapshot


@dataclass
class AggregatedMetrics:
    """Aggregated metrics for a time period"""
    symbol: str
    start_date: datetime
    end_date: datetime
    period_type: str  # 'daily', 'weekly', 'monthly'
    
    # Price metrics
    open_price: float
    close_price: float
    high_price: float
    low_price: float
    volume: int
    
    # Calculated metrics
    price_change: float
    price_change_pct: float
    volatility: float  # Standard deviation of daily returns
    avg_volume: float
    
    # Technical indicators (averaged)
    avg_rsi: Optional[float] = None
    avg_macd: Optional[float] = None
    avg_sma_20: Optional[float] = None
    avg_sma_50: Optional[float] = None


@dataclass
class RollingMetrics:
    """Rolling window performance metrics"""
    symbol: str
    date: datetime
    window_days: int
    
    # Performance metrics
    total_return: float
    annualized_return: float
    volatility: float
    max_drawdown: float
    avg_price: float
    momentum_score: float
    price_trend: str  # 'up', 'down', 'sideways'
    sharpe_ratio: Optional[float] = None


class DataAggregator:
    """Handles data aggregation and rollup calculations"""
    
    def __init__(self, db_path: str = "data/timeseries.db"):
        self.db = TimeSeriesDB(db_path)
    
    def aggregate_daily_to_weekly(self, symbol: str, start_date: datetime, end_date: datetime) -> List[AggregatedMetrics]:
        """Aggregate daily data into weekly periods (Monday to Sunday)"""
        weekly_data = []
        
        # Get all daily data for the period
        start_str = start_date.strftime('%Y-%m-%d')
        end_str = end_date.strftime('%Y-%m-%d')
        daily_snapshots = self.db.get_symbol_data(symbol, start_str, end_str)
        
        if not daily_snapshots:
            return []
        
        # Group by week
        current_week_start = self._get_week_start(self._parse_date(daily_snapshots[0].date))
        current_week_data = []
        
        for snapshot in daily_snapshots:
            week_start = self._get_week_start(self._parse_date(snapshot.date))
            
            if week_start != current_week_start:
                # Process previous week
                if current_week_data:
                    weekly_metrics = self._aggregate_period(current_week_data, 'weekly')
                    weekly_data.append(weekly_metrics)
                
                # Start new week
                current_week_start = week_start
                current_week_data = [snapshot]
            else:
                current_week_data.append(snapshot)
        
        # Process final week
        if current_week_data:
            weekly_metrics = self._aggregate_period(current_week_data, 'weekly')
            weekly_data.append(weekly_metrics)
        
        return weekly_data
    
    def aggregate_daily_to_monthly(self, symbol: str, start_date: datetime, end_date: datetime) -> List[AggregatedMetrics]:
        """Aggregate daily data into monthly periods"""
        monthly_data = []
        
        # Get all daily data for the period
        start_str = start_date.strftime('%Y-%m-%d')
        end_str = end_date.strftime('%Y-%m-%d')
        daily_snapshots = self.db.get_symbol_data(symbol, start_str, end_str)
        
        if not daily_snapshots:
            return []
        
        # Group by month
        current_month = self._get_month_tuple(self._parse_date(daily_snapshots[0].date))
        current_month_data = []
        
        for snapshot in daily_snapshots:
            month = self._get_month_tuple(self._parse_date(snapshot.date))
            
            if month != current_month:
                # Process previous month
                if current_month_data:
                    monthly_metrics = self._aggregate_period(current_month_data, 'monthly')
                    monthly_data.append(monthly_metrics)
                
                # Start new month
                current_month = month
                current_month_data = [snapshot]
            else:
                current_month_data.append(snapshot)
        
        # Process final month
        if current_month_data:
            monthly_metrics = self._aggregate_period(current_month_data, 'monthly')
            monthly_data.append(monthly_metrics)
        
        return monthly_data
    
    def calculate_rolling_metrics(self, symbol: str, date: datetime, window_days: int) -> Optional[RollingMetrics]:
        """Calculate rolling window metrics for a specific date"""
        end_date = date
        start_date = date - timedelta(days=window_days)
        
        # Get daily data for the window
        start_str = start_date.strftime('%Y-%m-%d')
        end_str = end_date.strftime('%Y-%m-%d')
        daily_snapshots = self.db.get_symbol_data(symbol, start_str, end_str)
        
        if len(daily_snapshots) < 2:
            return None
        
        # Sort by date
        daily_snapshots.sort(key=lambda x: x.date)
        
        # Calculate returns
        returns = []
        prices = [snapshot.close for snapshot in daily_snapshots]
        
        for i in range(1, len(prices)):
            daily_return = (prices[i] - prices[i-1]) / prices[i-1]
            returns.append(daily_return)
        
        if not returns:
            return None
        
        # Calculate metrics
        total_return = (prices[-1] - prices[0]) / prices[0]
        annualized_return = ((1 + total_return) ** (365 / window_days)) - 1
        volatility = statistics.stdev(returns) * (252 ** 0.5)  # Annualized volatility
        avg_price = statistics.mean(prices)
        
        # Calculate Sharpe ratio (assuming 0 risk-free rate)
        mean_return = statistics.mean(returns)
        sharpe_ratio = mean_return / statistics.stdev(returns) * (252 ** 0.5) if statistics.stdev(returns) > 0 else None
        
        # Calculate maximum drawdown
        max_drawdown = self._calculate_max_drawdown(prices)
        
        # Determine trend
        price_trend = self._determine_trend(prices)
        
        # Calculate momentum score (price relative to moving average)
        if len(prices) >= 20:
            sma_20 = statistics.mean(prices[-20:])
            momentum_score = (prices[-1] - sma_20) / sma_20
        else:
            momentum_score = 0.0
        
        return RollingMetrics(
            symbol=symbol,
            date=date,
            window_days=window_days,
            total_return=total_return,
            annualized_return=annualized_return,
            volatility=volatility,
            max_drawdown=max_drawdown,
            avg_price=avg_price,
            momentum_score=momentum_score,
            price_trend=price_trend,
            sharpe_ratio=sharpe_ratio
        )
    
    def get_comparison_baselines(self, date: datetime) -> Dict[str, float]:
        """Get benchmark returns for comparison (S&P 500, sector averages, etc.)"""
        baselines = {}
        
        # Try to get SPY data as S&P 500 proxy
        start_str = (date - timedelta(days=30)).strftime('%Y-%m-%d')
        end_str = date.strftime('%Y-%m-%d')
        spy_data = self.db.get_symbol_data("SPY", start_str, end_str)
        if spy_data and len(spy_data) >= 2:
            spy_data.sort(key=lambda x: x.date)
            spy_30d_return = (spy_data[-1].close - spy_data[0].close) / spy_data[0].close
            baselines["SP500_30d"] = spy_30d_return
        
        # Try to get QQQ data as NASDAQ proxy
        qqq_data = self.db.get_symbol_data("QQQ", start_str, end_str)
        if qqq_data and len(qqq_data) >= 2:
            qqq_data.sort(key=lambda x: x.date)
            qqq_30d_return = (qqq_data[-1].close - qqq_data[0].close) / qqq_data[0].close
            baselines["NASDAQ_30d"] = qqq_30d_return
        
        return baselines
    
    def _get_week_start(self, date: datetime) -> datetime:
        """Get the Monday of the week for a given date"""
        return date - timedelta(days=date.weekday())
    
    def _parse_date(self, date_str: str) -> datetime:
        """Parse date string to datetime object"""
        if isinstance(date_str, datetime):
            return date_str
        return datetime.strptime(date_str, '%Y-%m-%d')
    
    def _get_month_tuple(self, date: datetime) -> tuple:
        """Get year, month tuple from datetime"""
        return (date.year, date.month)
    
    def _aggregate_period(self, snapshots: List[DailySnapshot], period_type: str) -> AggregatedMetrics:
        """Aggregate a list of daily snapshots into a single period"""
        if not snapshots:
            raise ValueError("Cannot aggregate empty snapshots list")
        
        # Sort by date
        snapshots.sort(key=lambda x: self._parse_date(x.date))
        
        symbol = snapshots[0].symbol
        start_date = self._parse_date(snapshots[0].date)
        end_date = self._parse_date(snapshots[-1].date)
        
        # OHLC data
        open_price = snapshots[0].open
        close_price = snapshots[-1].close
        high_price = max(snapshot.high for snapshot in snapshots)
        low_price = min(snapshot.low for snapshot in snapshots)
        total_volume = sum(snapshot.volume for snapshot in snapshots)
        
        # Calculate metrics
        price_change = close_price - open_price
        price_change_pct = price_change / open_price if open_price > 0 else 0.0
        
        # Calculate volatility (standard deviation of daily returns)
        returns = []
        for i in range(1, len(snapshots)):
            daily_return = (snapshots[i].close - snapshots[i-1].close) / snapshots[i-1].close
            returns.append(daily_return)
        
        volatility = statistics.stdev(returns) if len(returns) > 1 else 0.0
        avg_volume = total_volume / len(snapshots)
        
        # Average technical indicators
        avg_rsi = None
        avg_macd = None
        avg_sma_20 = None
        avg_sma_50 = None
        
        rsi_values = [s.rsi for s in snapshots if s.rsi is not None]
        if rsi_values:
            avg_rsi = statistics.mean(rsi_values)
        
        macd_values = [s.macd for s in snapshots if s.macd is not None]
        if macd_values:
            avg_macd = statistics.mean(macd_values)
        
        sma_20_values = [s.sma_20 for s in snapshots if s.sma_20 is not None]
        if sma_20_values:
            avg_sma_20 = statistics.mean(sma_20_values)
        
        sma_50_values = [s.sma_50 for s in snapshots if s.sma_50 is not None]
        if sma_50_values:
            avg_sma_50 = statistics.mean(sma_50_values)
        
        return AggregatedMetrics(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            period_type=period_type,
            open_price=open_price,
            close_price=close_price,
            high_price=high_price,
            low_price=low_price,
            volume=total_volume,
            price_change=price_change,
            price_change_pct=price_change_pct,
            volatility=volatility,
            avg_volume=avg_volume,
            avg_rsi=avg_rsi,
            avg_macd=avg_macd,
            avg_sma_20=avg_sma_20,
            avg_sma_50=avg_sma_50
        )
    
    def _calculate_max_drawdown(self, prices: List[float]) -> float:
        """Calculate maximum drawdown from a series of prices"""
        if len(prices) < 2:
            return 0.0
        
        max_dd = 0.0
        peak = prices[0]
        
        for price in prices[1:]:
            if price > peak:
                peak = price
            else:
                drawdown = (peak - price) / peak
                max_dd = max(max_dd, drawdown)
        
        return max_dd
    
    def _determine_trend(self, prices: List[float]) -> str:
        """Determine trend direction from price series"""
        if len(prices) < 3:
            return 'sideways'
        
        # Compare first third vs last third
        first_third = statistics.mean(prices[:len(prices)//3])
        last_third = statistics.mean(prices[-len(prices)//3:])
        
        change_pct = (last_third - first_third) / first_third
        
        if change_pct > 0.02:  # 2% threshold
            return 'up'
        elif change_pct < -0.02:
            return 'down'
        else:
            return 'sideways'
