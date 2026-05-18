"""
Fund Analyzer Module

Provides comprehensive analysis for mutual funds and ETFs including:
- Multi-year performance analysis (1, 3, 5, 10 year periods)
- Risk metrics (volatility, Sharpe ratio, max drawdown, beta, alpha)
- Fund metadata (expense ratio, holdings, category)
"""

import os
import json
import yfinance as yf
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
import math


@dataclass
class PerformanceMetrics:
    """Performance metrics for a specific time period"""
    period_years: int
    total_return: float  # Percentage
    annualized_return: float  # Percentage
    volatility: float  # Standard deviation, annualized
    max_drawdown: float  # Percentage
    sharpe_ratio: float
    start_date: str
    end_date: str
    start_price: float
    end_price: float
    data_points: int
    
    def to_dict(self) -> dict:
        return {
            'period_years': self.period_years,
            'total_return': self.total_return,
            'annualized_return': self.annualized_return,
            'volatility': self.volatility,
            'max_drawdown': self.max_drawdown,
            'sharpe_ratio': self.sharpe_ratio,
            'start_date': self.start_date,
            'end_date': self.end_date,
            'start_price': self.start_price,
            'end_price': self.end_price,
            'data_points': self.data_points
        }


@dataclass
class RiskMetrics:
    """Risk metrics compared to a benchmark"""
    beta: float  # Systematic risk relative to market
    alpha: float  # Excess return vs benchmark
    r_squared: float  # How much variance explained by benchmark
    standard_deviation: float  # Annualized
    downside_deviation: float  # Only negative returns
    sortino_ratio: float  # Return/downside deviation
    
    def to_dict(self) -> dict:
        return {
            'beta': self.beta,
            'alpha': self.alpha,
            'r_squared': self.r_squared,
            'standard_deviation': self.standard_deviation,
            'downside_deviation': self.downside_deviation,
            'sortino_ratio': self.sortino_ratio
        }


@dataclass
class FundInfo:
    """Fund metadata from Yahoo Finance"""
    symbol: str
    name: str
    category: str
    expense_ratio: Optional[float]
    fund_family: str
    total_assets: Optional[float]
    yield_percent: Optional[float]
    ytd_return: Optional[float]
    three_year_return: Optional[float]
    five_year_return: Optional[float]
    top_holdings: List[Dict[str, Any]]
    sector_weights: Dict[str, float]
    fund_type: str  # 'ETF', 'Mutual Fund', 'Index Fund'
    
    def to_dict(self) -> dict:
        return {
            'symbol': self.symbol,
            'name': self.name,
            'category': self.category,
            'expense_ratio': self.expense_ratio,
            'fund_family': self.fund_family,
            'total_assets': self.total_assets,
            'yield_percent': self.yield_percent,
            'ytd_return': self.ytd_return,
            'three_year_return': self.three_year_return,
            'five_year_return': self.five_year_return,
            'top_holdings': self.top_holdings,
            'sector_weights': self.sector_weights,
            'fund_type': self.fund_type
        }


class FundAnalyzer:
    """Analyzes mutual funds and ETFs with prospectus-style metrics"""
    
    # Benchmark symbol for comparison (S&P 500)
    BENCHMARK_SYMBOL = 'SPY'
    
    # Risk-free rate assumption (approximate annual)
    RISK_FREE_RATE = 0.045  # 4.5%
    
    def __init__(self, cache_dir: str = "cache"):
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)
    
    def calculate_period_performance(self, data_points: List[dict], years: int) -> Optional[PerformanceMetrics]:
        """
        Calculate performance metrics for a specific time period.
        
        Args:
            data_points: List of {'date': str, 'close': float, ...} dicts
            years: Number of years to analyze (1, 3, 5, or 10)
        
        Returns:
            PerformanceMetrics object or None if insufficient data
        """
        if not data_points or len(data_points) < 20:
            return None
        
        # Sort by date
        sorted_data = sorted(data_points, key=lambda x: x['date'])
        
        # Calculate target start date
        end_date = datetime.strptime(sorted_data[-1]['date'], '%Y-%m-%d')
        target_start = end_date - timedelta(days=365 * years)
        
        # Filter data to the period
        period_data = [dp for dp in sorted_data if datetime.strptime(dp['date'], '%Y-%m-%d') >= target_start]
        
        if len(period_data) < 20:
            return None

        # Require meaningful coverage of the requested horizon to avoid
        # overstating long-period metrics from short samples.
        coverage_days = (
            datetime.strptime(period_data[-1]['date'], '%Y-%m-%d')
            - datetime.strptime(period_data[0]['date'], '%Y-%m-%d')
        ).days
        min_required_days = int(365 * years * 0.75)
        if coverage_days < min_required_days:
            return None
        
        # Calculate returns
        start_price = period_data[0]['close']
        end_price = period_data[-1]['close']
        
        total_return = ((end_price - start_price) / start_price) * 100
        
        # Annualized return (CAGR)
        actual_years = (datetime.strptime(period_data[-1]['date'], '%Y-%m-%d') - 
                       datetime.strptime(period_data[0]['date'], '%Y-%m-%d')).days / 365.25
        
        if actual_years > 0 and start_price > 0:
            annualized_return = ((end_price / start_price) ** (1 / actual_years) - 1) * 100
        else:
            annualized_return = 0
        
        # Calculate daily returns for volatility
        daily_returns = []
        for i in range(1, len(period_data)):
            prev_close = period_data[i-1]['close']
            curr_close = period_data[i]['close']
            if prev_close > 0:
                daily_returns.append((curr_close - prev_close) / prev_close)
        
        # Volatility (annualized standard deviation)
        volatility = self._calculate_std(daily_returns) * math.sqrt(252) * 100 if daily_returns else 0
        
        # Max drawdown
        max_drawdown = self._calculate_max_drawdown(period_data)
        
        # Sharpe ratio
        if volatility > 0:
            excess_return = annualized_return - (self.RISK_FREE_RATE * 100)
            sharpe_ratio = excess_return / volatility
        else:
            sharpe_ratio = 0
        
        return PerformanceMetrics(
            period_years=years,
            total_return=round(total_return, 2),
            annualized_return=round(annualized_return, 2),
            volatility=round(volatility, 2),
            max_drawdown=round(max_drawdown, 2),
            sharpe_ratio=round(sharpe_ratio, 2),
            start_date=period_data[0]['date'],
            end_date=period_data[-1]['date'],
            start_price=round(start_price, 2),
            end_price=round(end_price, 2),
            data_points=len(period_data)
        )
    
    def calculate_all_periods(self, data_points: List[dict]) -> Dict[int, Optional[PerformanceMetrics]]:
        """Calculate performance for 1, 3, 5, and 10 year periods"""
        periods = {}
        for years in [1, 3, 5, 10]:
            periods[years] = self.calculate_period_performance(data_points, years)
        return periods
    
    def calculate_risk_metrics(self, data_points: List[dict], benchmark_data: List[dict] = None) -> Optional[RiskMetrics]:
        """
        Calculate risk metrics including beta, alpha, and downside metrics.
        
        Args:
            data_points: Fund price data
            benchmark_data: Benchmark (SPY) price data for comparison
        """
        if not data_points or len(data_points) < 252:  # Need at least 1 year
            return None
        
        # Sort data
        sorted_data = sorted(data_points, key=lambda x: x['date'])
        
        # Calculate daily returns
        fund_returns = []
        for i in range(1, len(sorted_data)):
            prev = sorted_data[i-1]['close']
            curr = sorted_data[i]['close']
            if prev > 0:
                fund_returns.append((curr - prev) / prev)
        
        if not fund_returns:
            return None
        
        # Standard deviation (annualized)
        std_dev = self._calculate_std(fund_returns) * math.sqrt(252) * 100
        
        # Downside deviation (only negative returns)
        negative_returns = [r for r in fund_returns if r < 0]
        downside_dev = self._calculate_std(negative_returns) * math.sqrt(252) * 100 if negative_returns else 0
        
        # Sortino ratio
        avg_return = sum(fund_returns) / len(fund_returns) * 252  # Annualized
        if downside_dev > 0:
            sortino = (avg_return * 100 - self.RISK_FREE_RATE * 100) / downside_dev
        else:
            sortino = 0
        
        # Beta, Alpha, R-squared (requires benchmark)
        beta = 1.0  # Default
        alpha = 0.0
        r_squared = 0.0
        
        if benchmark_data and len(benchmark_data) >= len(sorted_data) - 50:
            # Align dates and calculate
            benchmark_sorted = sorted(benchmark_data, key=lambda x: x['date'])
            fund_dates = {dp['date'] for dp in sorted_data}
            
            # Get matching benchmark returns
            benchmark_returns = []
            fund_dates_list = [dp['date'] for dp in sorted_data]
            
            benchmark_dict = {dp['date']: dp['close'] for dp in benchmark_sorted}
            aligned_fund_returns = []
            aligned_benchmark_returns = []
            
            for i in range(1, len(sorted_data)):
                curr_date = sorted_data[i]['date']
                prev_date = sorted_data[i-1]['date']
                
                if curr_date in benchmark_dict and prev_date in benchmark_dict:
                    bench_prev = benchmark_dict[prev_date]
                    bench_curr = benchmark_dict[curr_date]
                    
                    if bench_prev > 0:
                        bench_return = (bench_curr - bench_prev) / bench_prev
                        aligned_benchmark_returns.append(bench_return)
                        aligned_fund_returns.append(fund_returns[i-1] if i-1 < len(fund_returns) else 0)
            
            if len(aligned_benchmark_returns) >= 100:
                beta, alpha, r_squared = self._calculate_regression_metrics(
                    aligned_fund_returns, aligned_benchmark_returns
                )
                alpha = alpha * 252 * 100  # Annualize
        
        return RiskMetrics(
            beta=round(beta, 2),
            alpha=round(alpha, 2),
            r_squared=round(r_squared, 2),
            standard_deviation=round(std_dev, 2),
            downside_deviation=round(downside_dev, 2),
            sortino_ratio=round(sortino, 2)
        )
    
    def fetch_fund_info(self, symbol: str, use_cache: bool = True) -> Optional[FundInfo]:
        """
        Fetch fund metadata from Yahoo Finance.
        
        Args:
            symbol: Fund ticker symbol
            use_cache: Whether to use cached data
        """
        cache_file = os.path.join(self.cache_dir, f"{symbol}_fund_info.json")
        
        # Check cache (valid for 24 hours)
        if use_cache and os.path.exists(cache_file):
            try:
                with open(cache_file, 'r') as f:
                    cached = json.load(f)
                    cache_time = datetime.fromisoformat(cached.get('_cached_at', '2000-01-01'))
                    if datetime.now() - cache_time < timedelta(hours=24):
                        del cached['_cached_at']
                        return FundInfo(**cached)
            except Exception:
                pass
        
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            
            # Determine fund type
            quote_type = info.get('quoteType', '').upper()
            if quote_type == 'ETF':
                fund_type = 'ETF'
            elif 'fund' in info.get('longName', '').lower() or 'mutual' in str(info.get('category', '')).lower():
                fund_type = 'Mutual Fund'
            else:
                fund_type = 'Fund'
            
            # Get top holdings
            top_holdings = []
            try:
                holdings = ticker.get_mutualfund_holders() if hasattr(ticker, 'get_mutualfund_holders') else None
                if holdings is not None and not holdings.empty:
                    for _, row in holdings.head(10).iterrows():
                        top_holdings.append({
                            'name': row.get('Holder', ''),
                            'weight': float(row.get('% Out', 0)) if row.get('% Out') else 0
                        })
            except Exception:
                pass
            
            # Get sector weights
            sector_weights = {}
            try:
                sectors = ticker.get_info().get('sectorWeightings', [])
                if sectors:
                    for sector in sectors:
                        for name, weight in sector.items():
                            sector_weights[name] = float(weight) * 100
            except Exception:
                pass
            
            fund_info = FundInfo(
                symbol=symbol,
                name=info.get('longName', info.get('shortName', symbol)),
                category=info.get('category', 'Unknown'),
                expense_ratio=info.get('annualReportExpenseRatio') or info.get('expenseRatio'),
                fund_family=info.get('fundFamily', 'Unknown'),
                total_assets=info.get('totalAssets'),
                yield_percent=info.get('yield'),
                ytd_return=info.get('ytdReturn'),
                three_year_return=info.get('threeYearAverageReturn'),
                five_year_return=info.get('fiveYearAverageReturn'),
                top_holdings=top_holdings,
                sector_weights=sector_weights,
                fund_type=fund_type
            )
            
            # Cache the result
            cache_data = fund_info.to_dict()
            cache_data['_cached_at'] = datetime.now().isoformat()
            with open(cache_file, 'w') as f:
                json.dump(cache_data, f, indent=2)
            
            return fund_info
            
        except Exception as e:
            print(f"Error fetching fund info for {symbol}: {e}")
            return None
    
    def get_benchmark_data(self, start_date: datetime, end_date: datetime) -> List[dict]:
        """Fetch benchmark (SPY) data for comparison"""
        cache_file = os.path.join(self.cache_dir, f"{self.BENCHMARK_SYMBOL}_historical.json")
        
        # Try to load from cache
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'r') as f:
                    data = json.load(f)
                    return data.get('data_points', [])
            except Exception:
                pass
        
        # Fetch from API
        try:
            ticker = yf.Ticker(self.BENCHMARK_SYMBOL)
            hist = ticker.history(start=start_date, end=end_date)
            
            data_points = []
            for date, row in hist.iterrows():
                data_points.append({
                    'date': date.strftime('%Y-%m-%d'),
                    'open': float(row['Open']),
                    'high': float(row['High']),
                    'low': float(row['Low']),
                    'close': float(row['Close']),
                    'volume': int(row['Volume'])
                })
            
            return data_points
        except Exception as e:
            print(f"Error fetching benchmark data: {e}")
            return []
    
    def generate_prospectus_data(self, symbol: str, data_points: List[dict]) -> Dict[str, Any]:
        """
        Generate complete prospectus-style data for a fund.
        
        Returns comprehensive analysis including:
        - Performance for 1, 3, 5, 10 year periods
        - Risk metrics with benchmark comparison
        - Fund metadata
        """
        result = {
            'symbol': symbol,
            'generated_at': datetime.now().isoformat(),
            'performance': {},
            'risk_metrics': None,
            'fund_info': None,
            'current_price': None,
            'benchmark_comparison': {}
        }
        
        if data_points:
            # Current price
            sorted_data = sorted(data_points, key=lambda x: x['date'])
            result['current_price'] = sorted_data[-1]['close'] if sorted_data else None
            
            # Performance for each period
            periods = self.calculate_all_periods(data_points)
            for years, metrics in periods.items():
                if metrics:
                    result['performance'][f'{years}yr'] = metrics.to_dict()
            
            # Get benchmark data for risk calculations
            if sorted_data:
                start_date = datetime.strptime(sorted_data[0]['date'], '%Y-%m-%d')
                end_date = datetime.strptime(sorted_data[-1]['date'], '%Y-%m-%d')
                benchmark_data = self.get_benchmark_data(start_date, end_date)
                
                # Risk metrics
                risk_metrics = self.calculate_risk_metrics(data_points, benchmark_data)
                if risk_metrics:
                    result['risk_metrics'] = risk_metrics.to_dict()
                
                # Benchmark comparison
                benchmark_periods = self.calculate_all_periods(benchmark_data)
                for years, metrics in benchmark_periods.items():
                    if metrics:
                        result['benchmark_comparison'][f'{years}yr'] = {
                            'benchmark_return': metrics.annualized_return,
                            'fund_return': periods.get(years).annualized_return if periods.get(years) else None,
                            'outperformance': (periods.get(years).annualized_return - metrics.annualized_return) if periods.get(years) else None
                        }
        
        # Fund info
        fund_info = self.fetch_fund_info(symbol)
        if fund_info:
            result['fund_info'] = fund_info.to_dict()
        
        return result
    
    def _calculate_std(self, values: List[float]) -> float:
        """Calculate standard deviation"""
        if not values or len(values) < 2:
            return 0
        
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / (len(values) - 1)
        return math.sqrt(variance)
    
    def _calculate_max_drawdown(self, data_points: List[dict]) -> float:
        """Calculate maximum drawdown percentage"""
        if not data_points:
            return 0
        
        peak = data_points[0]['close']
        max_dd = 0
        
        for dp in data_points:
            price = dp['close']
            if price > peak:
                peak = price
            
            drawdown = (peak - price) / peak * 100 if peak > 0 else 0
            max_dd = max(max_dd, drawdown)
        
        return max_dd
    
    def _calculate_regression_metrics(self, fund_returns: List[float], benchmark_returns: List[float]) -> Tuple[float, float, float]:
        """
        Calculate beta, alpha, and R-squared using linear regression.
        Returns (beta, alpha, r_squared)
        """
        n = len(fund_returns)
        if n < 2 or n != len(benchmark_returns):
            return 1.0, 0.0, 0.0
        
        # Means
        mean_fund = sum(fund_returns) / n
        mean_bench = sum(benchmark_returns) / n
        
        # Covariance and variance
        cov = sum((fund_returns[i] - mean_fund) * (benchmark_returns[i] - mean_bench) for i in range(n)) / (n - 1)
        var_bench = sum((benchmark_returns[i] - mean_bench) ** 2 for i in range(n)) / (n - 1)
        var_fund = sum((fund_returns[i] - mean_fund) ** 2 for i in range(n)) / (n - 1)
        
        # Beta = Cov(fund, benchmark) / Var(benchmark)
        beta = cov / var_bench if var_bench > 0 else 1.0
        
        # Alpha = mean_fund - beta * mean_bench
        alpha = mean_fund - beta * mean_bench
        
        # R-squared = correlation^2
        if var_fund > 0 and var_bench > 0:
            correlation = cov / math.sqrt(var_fund * var_bench)
            r_squared = correlation ** 2
        else:
            r_squared = 0
        
        return beta, alpha, r_squared
