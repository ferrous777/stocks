import json
import os
from typing import Optional, Tuple, Dict, Any
from datetime import datetime, timedelta
from .data_types import HistoricalData, FundamentalData

class CacheWriteError(Exception):
    """Custom exception for cache writing errors"""
    pass

class MarketDataStorage:
    """Handles local storage of market data"""
    
    def __init__(self, cache_dir: str = "cache"):
        self.cache_dir = cache_dir
        self._ensure_cache_dirs()
    
    def _ensure_cache_dirs(self):
        """Ensure cache directories exist"""
        os.makedirs(os.path.join(self.cache_dir, "historical"), exist_ok=True)
        os.makedirs(os.path.join(self.cache_dir, "fundamentals"), exist_ok=True)
    
    def _get_historical_cache_path(self, symbol: str) -> str:
        return os.path.join(self.cache_dir, "historical", f"{symbol}.json")
    
    def _get_fundamentals_cache_path(self, symbol: str) -> str:
        return os.path.join(self.cache_dir, "fundamentals", f"{symbol}.json")
    
    def _safe_write_json(self, path: str, data: dict):
        """Safely write data to JSON file with detailed error checking"""
        # First serialize to string to verify it's valid JSON
        json_str = json.dumps(data, indent=2)
        
        # Check if the directory exists and is writable
        dir_path = os.path.dirname(path)
        if not os.path.exists(dir_path):
            raise CacheWriteError(f"Directory does not exist: {dir_path}")
        if not os.access(dir_path, os.W_OK):
            raise CacheWriteError(f"Directory is not writable: {dir_path}")
        
        # Write to file
        with open(path, 'w') as f:
            f.write(json_str)
        
        # Verify the file was written correctly
        if not os.path.exists(path):
            raise CacheWriteError(f"File was not created: {path}")
        
        file_size = os.path.getsize(path)
        if file_size == 0:
            raise CacheWriteError(f"File was created but is empty: {path}")
        
        # Verify the content can be read back
        with open(path, 'r') as f:
            loaded_data = json.load(f)
        
        # Check if all top-level keys are present
        missing_keys = set(data.keys()) - set(loaded_data.keys())
        if missing_keys:
            raise CacheWriteError(f"Written data is missing keys: {missing_keys}")
    
    def get_historical_data(self, symbol: str, start_date: str, end_date: str) -> Optional[HistoricalData]:
        """Retrieve historical data from cache if available"""
        cache_path = self._get_historical_cache_path(symbol)
        
        # Check if file exists and has content
        if not os.path.exists(cache_path) or os.path.getsize(cache_path) == 0:
            return None
        
        # Try to read the file
        try:
            with open(cache_path, 'r') as f:
                cache_data = json.load(f)
        except json.JSONDecodeError:
            # Remove corrupted cache file
            os.remove(cache_path)
            return None
        
        # Check if cache covers the requested date range
        cache_start = datetime.strptime(cache_data['start_date'], '%Y-%m-%d')
        cache_end = datetime.strptime(cache_data['end_date'], '%Y-%m-%d')
        req_start = datetime.strptime(start_date, '%Y-%m-%d')
        req_end = datetime.strptime(end_date, '%Y-%m-%d')
        
        if cache_start <= req_start and cache_end >= req_end:
            return HistoricalData.from_dict(cache_data)
        
        return None
    
    def save_historical_data(self, symbol: str, data: HistoricalData):
        """Save historical data to cache"""
        if not data or not data.data_points:
            raise CacheWriteError(f"No valid data to save for symbol {symbol}")
        
        cache_path = self._get_historical_cache_path(symbol)
        cache_data = data.to_dict()
        self._safe_write_json(cache_path, cache_data)
        print(f"Successfully wrote historical data to {cache_path}")
    
    def get_fundamentals(self, symbol: str) -> Optional[FundamentalData]:
        """Retrieve fundamental data from cache if available and not expired"""
        cache_path = self._get_fundamentals_cache_path(symbol)
        
        # Check if file exists and has content
        if not os.path.exists(cache_path) or os.path.getsize(cache_path) == 0:
            return None
        
        # Try to read the file
        try:
            with open(cache_path, 'r') as f:
                cache_data = json.load(f)
        except json.JSONDecodeError:
            # Remove corrupted cache file
            os.remove(cache_path)
            return None
        
        # Check if cache is expired (older than 1 day)
        last_updated = datetime.strptime(cache_data['last_updated'], '%Y-%m-%d %H:%M:%S')
        if datetime.now() - last_updated > timedelta(days=1):
            os.remove(cache_path)  # Remove expired cache
            return None
        
        return FundamentalData.from_dict(cache_data)
    
    def save_fundamentals(self, symbol: str, data: FundamentalData):
        """Save fundamental data to cache"""
        if not data:
            raise CacheWriteError(f"No fundamental data to save for symbol {symbol}")
        
        cache_path = self._get_fundamentals_cache_path(symbol)
        cache_data = data.to_dict()
        self._safe_write_json(cache_path, cache_data)
        print(f"Successfully wrote fundamental data to {cache_path}")
    
    def validate_cache(self, symbol: str) -> Tuple[bool, Dict[str, str]]:
        """Validate that data was written correctly to cache files"""
        validation = {
            'historical': 'Not checked',
            'fundamentals': 'Not checked'
        }
        success = True
        
        # Check historical data
        historical_path = self._get_historical_cache_path(symbol)
        if os.path.exists(historical_path):
            with open(historical_path, 'r') as f:
                data = json.load(f)
            # Try to create HistoricalData object from cache
            HistoricalData.from_dict(data)
            validation['historical'] = 'Valid'
        else:
            validation['historical'] = 'File not found'
            success = False
        
        # Check fundamentals data
        fundamentals_path = self._get_fundamentals_cache_path(symbol)
        if os.path.exists(fundamentals_path):
            with open(fundamentals_path, 'r') as f:
                data = json.load(f)
            # Try to create FundamentalData object from cache
            FundamentalData.from_dict(data)
            validation['fundamentals'] = 'Valid'
        else:
            validation['fundamentals'] = 'File not found'
        
        return success, validation 