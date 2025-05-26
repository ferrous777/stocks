from datetime import datetime
import os
import json
import yfinance as yf
from typing import Dict, List, Optional, Tuple
import time
from yfinance.exceptions import YFRateLimitError
import requests
import pandas as pd

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
        self.results_dir = "results"  # At same level as cache
        self.max_retries = 3
        self.data_cache = {}
        
        # Create both cache and results directories
        os.makedirs(cache_dir, exist_ok=True)
        os.makedirs(self.results_dir, exist_ok=True)
        
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        print("Set up Yahoo Finance session")
    
    def get_data(self, symbol: str, start_date: datetime, end_date: datetime, 
                 include_fundamentals: bool = False, force_refresh: bool = False) -> Tuple[HistoricalData, Optional[FundamentalData]]:
        """Get market data for a symbol from memory cache first"""
        if symbol in self.data_cache:
            historical = self.data_cache[symbol]
        else:
            historical = self._get_historical_data(symbol, start_date, end_date, force_refresh)
        
        fundamental = None
        if include_fundamentals:
            try:
                fundamental = self._get_fundamental_data(symbol, force_refresh)
            except Exception as e:
                raise FundamentalsError(f"Error fetching fundamentals for {symbol}: {str(e)}")
        
        return historical, fundamental

    def get_batch_data(self, symbols: List[str], start_date: datetime, end_date: datetime, force_refresh: bool = False) -> Dict[str, HistoricalData]:
        results = {}
        
        # Process cached data first
        symbols_to_fetch = []
        for symbol in symbols:
            if symbol in self.data_cache:
                results[symbol] = self.data_cache[symbol]
                continue
                
            cache_file = os.path.join(self.cache_dir, f"{symbol}_historical.json")
            if not force_refresh and os.path.exists(cache_file):
                with open(cache_file, 'r') as f:
                    data = HistoricalData.from_dict(json.load(f))
                    results[symbol] = data
                    self.data_cache[symbol] = data
                    print(f"Loaded {symbol} from cache")
            else:
                symbols_to_fetch.append(symbol)
        
        if not symbols_to_fetch:
            return results

        # Process symbols using direct API calls
        for symbol in symbols_to_fetch:
            try:
                print(f"\nFetching data for {symbol}...")
                period1 = int(start_date.timestamp())
                period2 = int(end_date.timestamp())
                
                url = f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?period1={period1}&period2={period2}&interval=1d'
                response = self.session.get(url)
                response.raise_for_status()
                
                data = response.json()
                if 'chart' not in data or 'result' not in data['chart'] or not data['chart']['result']:
                    print(f"Warning: No data returned for {symbol}")
                    continue
                    
                result = data['chart']['result'][0]
                timestamps = result['timestamp']
                quote = result['indicators']['quote'][0]
                
                data_points = []
                for i, ts in enumerate(timestamps):
                    if all(quote[field][i] is not None for field in ['open', 'high', 'low', 'close', 'volume']):
                        data_points.append(DataPoint(
                            date=datetime.fromtimestamp(ts).strftime('%Y-%m-%d'),
                            open=float(quote['open'][i]),
                            high=float(quote['high'][i]),
                            low=float(quote['low'][i]),
                            close=float(quote['close'][i]),
                            volume=int(quote['volume'][i])
                        ))
                
                if data_points:
                    historical_data = HistoricalData(symbol=symbol, data_points=data_points)
                    results[symbol] = historical_data
                    self.data_cache[symbol] = historical_data
                    
                    # Cache to file
                    cache_file = os.path.join(self.cache_dir, f"{symbol}_historical.json")
                    with open(cache_file, 'w') as f:
                        json.dump(historical_data.to_dict(), f)
                    print(f"Cached {symbol} data")

            except Exception as e:
                print(f"\nError fetching {symbol}: {str(e)}")
                continue

        return results

    def _process_single_symbol_data(self, data: pd.DataFrame, symbol: str, results: Dict[str, HistoricalData]):
        """Process data for a single symbol"""
        if len(data) == 0:
            print(f"Warning: No data returned for {symbol}")
            return
            
        data_points = []
        for index, row in data.iterrows():
            data_points.append(DataPoint(
                date=index.strftime('%Y-%m-%d'),
                open=float(row['Open']),
                high=float(row['High']),
                low=float(row['Low']),
                close=float(row['Close']),
                volume=int(row['Volume'])
            ))
        
        if data_points:
            historical_data = HistoricalData(symbol=symbol, data_points=data_points)
            results[symbol] = historical_data
            self.data_cache[symbol] = historical_data  # Add to in-memory cache
            
            # Cache to file
            cache_file = os.path.join(self.cache_dir, f"{symbol}_historical.json")
            with open(cache_file, 'w') as f:
                json.dump(historical_data.to_dict(), f)
            print(f"Cached {symbol} data")

    def _process_multiple_symbols_data(self, data: pd.DataFrame, symbols: List[str], results: Dict[str, HistoricalData]):
        """Process data for multiple symbols"""
        for symbol in symbols:
            try:
                if symbol not in data.columns.levels[0]:
                    print(f"Warning: No data returned for {symbol}")
                    continue
                    
                symbol_data = data[symbol]
                data_points = []
                for index, row in symbol_data.iterrows():
                    data_points.append(DataPoint(
                        date=index.strftime('%Y-%m-%d'),
                        open=float(row['Open']),
                        high=float(row['High']),
                        low=float(row['Low']),
                        close=float(row['Close']),
                        volume=int(row['Volume'])
                    ))
                
                if data_points:
                    historical_data = HistoricalData(symbol=symbol, data_points=data_points)
                    results[symbol] = historical_data
                    self.data_cache[symbol] = historical_data  # Add to in-memory cache
                    
                    # Cache to file
                    cache_file = os.path.join(self.cache_dir, f"{symbol}_historical.json")
                    with open(cache_file, 'w') as f:
                        json.dump(historical_data.to_dict(), f)
                    print(f"Cached {symbol} data")
            except Exception as e:
                print(f"Error processing {symbol}: {str(e)}")
                continue

    def _get_historical_data(self, symbol: str, start_date: datetime, end_date: datetime, force_refresh: bool) -> HistoricalData:
        """Get historical price data using yf.download"""
        cache_file = os.path.join(self.cache_dir, f"{symbol}_historical.json")
        
        # Try cache first
        if not force_refresh and os.path.exists(cache_file):
            with open(cache_file, 'r') as f:
                return HistoricalData.from_dict(json.load(f))

        # Fetch from Yahoo Finance with retries
        for attempt in range(self.max_retries):
            try:
                print(f"\nAttempting to fetch data for {symbol}...")
                data = yf.download(
                    symbol,
                    start=start_date.strftime('%Y-%m-%d'),
                    end=end_date.strftime('%Y-%m-%d'),
                    progress=False
                )
                
                if data.empty:
                    print(f"Warning: No data returned for {symbol}")
                    raise ValueError(f"Empty data received for {symbol}")

                print(f"Received {len(data)} data points")
                data_points = []
                for index, row in data.iterrows():
                    data_points.append(DataPoint(
                        date=index.strftime('%Y-%m-%d'),
                        open=float(row['Open']),
                        high=float(row['High']),
                        low=float(row['Low']),
                        close=float(row['Close']),
                        volume=int(row['Volume'])
                    ))

                historical_data = HistoricalData(
                    symbol=symbol,
                    data_points=sorted(data_points, key=lambda x: x.date)
                )
                
                # Cache the data
                with open(cache_file, 'w') as f:
                    json.dump(historical_data.to_dict(), f)

                return historical_data

            except Exception as e:
                print(f"\nError fetching {symbol}:")
                print(f"Error type: {type(e).__name__}")
                print(f"Error message: {str(e)}")
                print(f"Attempt {attempt + 1} of {self.max_retries}")
                
                if attempt < self.max_retries - 1:
                    wait_time = (2 ** attempt) * 5
                    print(f"Waiting {wait_time} seconds before retry...")
                    time.sleep(wait_time)
                else:
                    raise
    
    def _get_fundamental_data(self, symbol: str, force_refresh: bool) -> Optional[FundamentalData]:
        """Get basic fundamental data from Yahoo Finance"""
        cache_file = os.path.join(self.cache_dir, f"{symbol}_fundamental.json")
        
        if not force_refresh and os.path.exists(cache_file):
            with open(cache_file, 'r') as f:
                return FundamentalData.from_dict(json.load(f))

        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info

            fundamental_data = FundamentalData(
                symbol=symbol,
                market_cap=float(info.get('marketCap', 0)),
                pe_ratio=float(info.get('forwardPE', 0)),
                dividend_yield=float(info.get('dividendYield', 0) or 0),
                beta=float(info.get('beta', 0) or 0),
                sector=info.get('sector', ''),
                industry=info.get('industry', '')
            )

            # Cache the data
            with open(cache_file, 'w') as f:
                json.dump(fundamental_data.to_dict(), f)

            return fundamental_data

        except Exception as e:
            print(f"Error fetching fundamentals for {symbol}: {str(e)}")
            return None 

    def save_backtest_results(self, symbol: str, strategy: str, results: dict, initial_capital: float):
        """Save backtest results to the results directory"""
        today = datetime.now().strftime('%Y%m%d')
        filename = f"{symbol}_backtest_{strategy}_{today}.json"
        filepath = os.path.join(self.results_dir, filename)
        
        # Calculate buy and hold returns
        first_price = results.get("first_price", 0)
        last_price = results.get("last_price", 0)
        buy_hold_shares = initial_capital / first_price if first_price > 0 else 0
        buy_hold_value = buy_hold_shares * last_price
        buy_hold_return = ((buy_hold_value - initial_capital) / initial_capital) * 100 if initial_capital > 0 else 0
        
        # Ensure trades array exists and has required fields
        trades_data = []
        for trade in results.get("trades", []):
            trade_data = {
                "date": trade.get("date", ""),
                "type": trade.get("type", ""),
                "price": trade.get("price", 0.0),
                "shares": trade.get("shares", 0),
                "profit_loss": trade.get("profit_loss", None)
            }
            trades_data.append(trade_data)
        
        output = {
            "symbol": symbol,
            "strategy": strategy,
            "initial_capital": initial_capital,
            "date_run": datetime.now().isoformat(),
            "results": {
                "total_returns": results.get("total_returns", 0),
                "total_trades": results.get("total_trades", 0),
                "winning_trades": results.get("winning_trades", 0),
                "losing_trades": results.get("losing_trades", 0),
                "win_rate": results.get("win_rate", 0),
                "final_balance": results.get("final_balance", initial_capital),
                "max_drawdown": results.get("max_drawdown", 0),
                "sharpe_ratio": results.get("sharpe_ratio", 0),
                "trades": trades_data  # Use the processed trades data
            },
            "buy_and_hold": {
                "initial_price": first_price,
                "final_price": last_price,
                "shares_held": buy_hold_shares,
                "final_value": buy_hold_value,
                "total_return_pct": buy_hold_return,
                "total_return_dollars": buy_hold_value - initial_capital
            },
            "comparison": {
                "strategy_outperformance": results.get("total_returns", 0) - buy_hold_return,
                "strategy_vs_buyhold": "OUTPERFORM" if results.get("total_returns", 0) > buy_hold_return else "UNDERPERFORM"
            }
        }
        
        with open(filepath, 'w') as f:
            json.dump(output, f, indent=2)
        print(f"\nBacktest results saved to: {filepath}")

    def save_recommendations(self, symbol: str, recommendations: dict):
        """Save recommendations to a JSON file in the results directory"""
        today = datetime.now().strftime('%Y%m%d')
        filename = f"{symbol}_recommendations_{today}.json"
        filepath = os.path.join("results", filename)
        
        # Get current price from the most recent data point
        current_price = recommendations.get('entry_price', 0.0)
        
        output = {
            "symbol": symbol,
            "date_run": datetime.now().isoformat(),
            "recommendations": {
                "action": recommendations.get('action', 'HOLD'),
                "type": recommendations.get('type', 'NONE'),
                "confidence": recommendations.get('confidence', 0.0),
                "entry_price": recommendations.get('entry_price', current_price),
                "stop_loss": recommendations.get('stop_loss', current_price * 0.95),
                "take_profit": recommendations.get('take_profit', current_price * 1.05),
                "position_size": recommendations.get('position_size', 'NONE'),
                "order_type": recommendations.get('order_type', 'NONE'),
                "risk_reward": recommendations.get('risk_reward', 0.0),
                "time_horizon": recommendations.get('time_horizon', 'MEDIUM'),
                "risk_level": recommendations.get('risk_level', 'MODERATE')
            },
            "market_context": {
                "trend": recommendations.get('trend', 'NEUTRAL'),
                "volatility": recommendations.get('volatility', 'MODERATE'),
                "volume": recommendations.get('volume', 'NORMAL'),
                "support_level": recommendations.get('support_level', current_price * 0.95),
                "resistance_level": recommendations.get('resistance_level', current_price * 1.05)
            },
            "technical_signals": {
                "moving_averages": recommendations.get('moving_averages', 'NEUTRAL'),
                "rsi": recommendations.get('rsi', 'NEUTRAL'),
                "macd": recommendations.get('macd', 'NEUTRAL'),
                "bollinger": recommendations.get('bollinger', 'NEUTRAL')
            }
        }
        
        with open(filepath, 'w') as f:
            json.dump(output, f, indent=2)
        print(f"\nRecommendations saved to: {filepath}") 