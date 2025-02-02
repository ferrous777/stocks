from datetime import datetime
import os
import json
import yfinance as yf
from typing import Dict, List, Optional, Tuple

from .data_types import (
    DataPoint,
    HistoricalData,
    FundamentalData
)

class FundamentalsError(Exception):
    """Raised when there's an error fetching fundamental data"""
    pass

class MarketData:
    def __init__(self, cache_dir: str = "cache"):
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)
    
    def get_data(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        include_fundamentals: bool = False,
        force_refresh: bool = False
    ) -> Tuple[HistoricalData, Optional[FundamentalData]]:
        """Get market data for a symbol"""
        
        historical = self._get_historical_data(symbol, start_date, end_date, force_refresh)
        fundamental = None
        
        if include_fundamentals:
            try:
                fundamental = self._get_fundamental_data(symbol, force_refresh)
            except Exception as e:
                raise FundamentalsError(f"Error fetching fundamentals for {symbol}: {str(e)}")
        
        return historical, fundamental
    
    def _get_historical_data(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        force_refresh: bool
    ) -> HistoricalData:
        """Get historical price data"""
        
        cache_file = os.path.join(self.cache_dir, f"{symbol}_historical.json")
        
        # Try to load from cache first
        if not force_refresh and os.path.exists(cache_file):
            with open(cache_file, 'r') as f:
                return HistoricalData.from_dict(json.load(f))
        
        # Fetch from yfinance
        ticker = yf.Ticker(symbol)
        history = ticker.history(start=start_date, end=end_date)
        
        # Convert to our data structure
        data_points = []
        for index, row in history.iterrows():
            data_points.append(DataPoint(
                date=index.strftime('%Y-%m-%d'),
                open=float(row['Open']),
                high=float(row['High']),
                low=float(row['Low']),
                close=float(row['Close']),
                volume=int(row['Volume'])
            ))
        
        historical_data = HistoricalData(symbol=symbol, data_points=data_points)
        
        # Cache the data
        with open(cache_file, 'w') as f:
            json.dump(historical_data.to_dict(), f)
        
        return historical_data
    
    def _get_fundamental_data(
        self,
        symbol: str,
        force_refresh: bool
    ) -> FundamentalData:
        """Get fundamental data"""
        
        cache_file = os.path.join(self.cache_dir, f"{symbol}_fundamental.json")
        
        # Try to load from cache first
        if not force_refresh and os.path.exists(cache_file):
            with open(cache_file, 'r') as f:
                return FundamentalData.from_dict(json.load(f))
        
        # Fetch from yfinance
        ticker = yf.Ticker(symbol)
        info = ticker.info
        
        fundamental_data = FundamentalData(
            symbol=symbol,
            market_cap=info.get('marketCap', 0),
            pe_ratio=info.get('forwardPE', 0),
            dividend_yield=info.get('dividendYield', 0),
            beta=info.get('beta', 0),
            sector=info.get('sector', ''),
            industry=info.get('industry', '')
        )
        
        # Cache the data
        with open(cache_file, 'w') as f:
            json.dump(fundamental_data.to_dict(), f)
        
        return fundamental_data 