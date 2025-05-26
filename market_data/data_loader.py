from dataclasses import dataclass
from datetime import datetime
import os
import json
import yfinance as yf
from .data_types import HistoricalData, FundamentalData, DataPoint

@dataclass
class MarketDataConfig:
    """Configuration for market data fetching"""
    symbol: str
    start_date: str
    end_date: str
    cache_dir: str = 'cache'
    fetch_fundamentals: bool = False
    force_refresh: bool = False
    debug: bool = False

def get_market_data(symbol: str, start_date: str, end_date: str, 
                   storage: str = 'cache', fundamentals: bool = False,
                   force_refresh: bool = False, debug: bool = False) -> tuple[HistoricalData, FundamentalData | None]:
    """Fetch market data for a given symbol"""
    
    # Create cache directory if it doesn't exist
    os.makedirs(storage, exist_ok=True)
    
    # Cache file paths
    historical_cache = os.path.join(storage, f"{symbol}_historical.json")
    fundamental_cache = os.path.join(storage, f"{symbol}_fundamental.json")
    
    historical_data = None
    fundamental_data = None
    
    # Try to load from cache first
    if not force_refresh and os.path.exists(historical_cache):
        if debug:
            print(f"Loading {symbol} historical data from cache...")
        with open(historical_cache, 'r') as f:
            historical_data = HistoricalData.from_dict(json.load(f))
    
    if not force_refresh and fundamentals and os.path.exists(fundamental_cache):
        if debug:
            print(f"Loading {symbol} fundamental data from cache...")
        with open(fundamental_cache, 'r') as f:
            fundamental_data = FundamentalData.from_dict(json.load(f))
    
    # Fetch from yfinance if needed
    if historical_data is None or force_refresh:
        if debug:
            print(f"Fetching {symbol} historical data from yfinance...")
        
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
        with open(historical_cache, 'w') as f:
            json.dump(historical_data.to_dict(), f)
    
    if (fundamental_data is None or force_refresh) and fundamentals:
        if debug:
            print(f"Fetching {symbol} fundamental data from yfinance...")
        
        ticker = yf.Ticker(symbol)
        info = ticker.info
        
        # Convert to our data structure
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
        with open(fundamental_cache, 'w') as f:
            json.dump(fundamental_data.to_dict(), f)
    
    return historical_data, fundamental_data 