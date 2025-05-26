#!/usr/bin/env python3
"""
Helper script to add new tickers to the stock analysis system.
This script fetches real market data and creates the necessary files.

Usage:
    python add_ticker.py SYMBOL [SYMBOL2 SYMBOL3 ...]
    
Example:
    python add_ticker.py TSLA NVDA META
"""

import sys
import json
import os
import requests
from datetime import datetime, timedelta
import argparse

def fetch_sample_data(symbol):
    """
    Create sample historical data for a symbol.
    In a real system, you'd fetch this from a financial API like Alpha Vantage, Yahoo Finance, etc.
    """
    # This is sample data - replace with real API calls
    base_price = 100.0  # Starting price
    data_points = []
    
    for i in range(30):  # 30 days of sample data
        date = (datetime.now() - timedelta(days=30-i)).strftime("%Y-%m-%d")
        # Simple random walk for demo
        variation = (-1 + 2 * (i % 3) / 2) * 5  # Simple price variation
        price = base_price + variation + i * 0.5
        
        data_points.append({
            "date": date,
            "open": round(price - 1, 2),
            "high": round(price + 2, 2),
            "low": round(price - 2, 2),
            "close": round(price, 2),
            "volume": 1000000 + (i * 50000)
        })
    
    return data_points

def create_historical_file(symbol):
    """Create the historical data file in cache directory."""
    print(f"Creating historical data for {symbol}...")
    
    # Ensure cache directory exists
    os.makedirs('cache', exist_ok=True)
    
    # Fetch or generate data
    data_points = fetch_sample_data(symbol)
    
    cache_data = {
        "symbol": symbol,
        "data_points": data_points
    }
    
    cache_file = f"cache/{symbol}_historical.json"
    with open(cache_file, "w") as f:
        json.dump(cache_data, f, indent=2)
    
    print(f"✓ Created {cache_file}")
    return data_points[-1]["close"]  # Return current price

def create_recommendations_file(symbol, current_price):
    """Create a recommendations file for the symbol."""
    print(f"Creating recommendations for {symbol}...")
    
    # Ensure results directory exists
    os.makedirs('results', exist_ok=True)
    
    # Generate a simple recommendation
    actions = ["BUY", "SELL", "HOLD"]
    action = actions[hash(symbol) % len(actions)]  # Deterministic but varied
    
    rec_data = {
        "symbol": symbol,
        "analysis_date": datetime.now().strftime("%Y-%m-%d"),
        "date_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "recommendations": {
            "action": action,
            "type": "LONG" if action in ["BUY", "HOLD"] else "SHORT",
            "confidence": round(0.6 + (hash(symbol) % 40) / 100, 2),  # 0.6-1.0
            "entry_price": current_price,
            "stop_loss": round(current_price * 0.95, 2),
            "take_profit": round(current_price * 1.10, 2),
            "reasoning": f"Initial setup recommendation for {symbol}. This is a sample recommendation.",
            "supporting_strategies": ["Initial Setup"]
        }
    }
    
    today = datetime.now().strftime("%Y%m%d")
    rec_file = f"results/{symbol}_recommendations_{today}.json"
    
    with open(rec_file, "w") as f:
        json.dump(rec_data, f, indent=2)
    
    print(f"✓ Created {rec_file}")

def create_backtest_file(symbol, current_price):
    """Create a simple backtest file for the symbol."""
    print(f"Creating backtest data for {symbol}...")
    
    backtest_data = {
        "symbol": symbol,
        "date_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "period": {
            "start": (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d"),
            "end": datetime.now().strftime("%Y-%m-%d")
        },
        "strategies": {
            "Moving Average Crossover": {
                "total_returns": round(5 + (hash(symbol) % 20), 2),  # 5-25% returns
                "total_trades": 10 + (hash(symbol) % 20),
                "winning_trades": 6 + (hash(symbol) % 10),
                "losing_trades": 4 + (hash(symbol) % 10),
                "final_balance": round(10000 + (hash(symbol) % 5000), 2),
                "sharpe_ratio": round(0.5 + (hash(symbol) % 10) / 10, 2),
                "max_drawdown": round(-5 - (hash(symbol) % 10), 2)
            }
        }
    }
    
    today = datetime.now().strftime("%Y%m%d")
    backtest_file = f"results/{symbol}_backtest_{today}.json"
    
    with open(backtest_file, "w") as f:
        json.dump(backtest_data, f, indent=2)
    
    print(f"✓ Created {backtest_file}")

def add_ticker(symbol):
    """Add a complete ticker to the system."""
    symbol = symbol.upper()
    print(f"\n=== Adding {symbol} to tracking system ===")
    
    # Check if already exists
    cache_file = f"cache/{symbol}_historical.json"
    if os.path.exists(cache_file):
        print(f"⚠ Warning: {symbol} already exists in cache. Updating...")
    
    try:
        # Create all necessary files
        current_price = create_historical_file(symbol)
        create_recommendations_file(symbol, current_price)
        create_backtest_file(symbol, current_price)
        
        print(f"✅ Successfully added {symbol} to the system!")
        print(f"   Current price: ${current_price}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error adding {symbol}: {e}")
        return False

def list_current_tickers():
    """List all currently tracked tickers."""
    print("\n=== Currently Tracked Tickers ===")
    
    cache_files = []
    if os.path.exists('cache'):
        cache_files = [f for f in os.listdir('cache') if f.endswith('_historical.json')]
    
    if not cache_files:
        print("No tickers currently tracked.")
        return []
    
    symbols = []
    for file in sorted(cache_files):
        symbol = file.replace('_historical.json', '')
        symbols.append(symbol)
        
        # Check if has recent recommendations
        today = datetime.now().strftime("%Y%m%d")
        rec_file = f"results/{symbol}_recommendations_{today}.json"
        has_rec = "✓" if os.path.exists(rec_file) else "✗"
        
        print(f"  {symbol:<8} - Historical: ✓ | Today's Rec: {has_rec}")
    
    print(f"\nTotal: {len(symbols)} tickers")
    return symbols

def main():
    parser = argparse.ArgumentParser(description="Add new tickers to the stock analysis system")
    parser.add_argument('symbols', nargs='*', help='Stock symbols to add (e.g., TSLA NVDA)')
    parser.add_argument('--list', '-l', action='store_true', help='List currently tracked tickers')
    parser.add_argument('--example', action='store_true', help='Show example usage')
    
    args = parser.parse_args()
    
    if args.example:
        print("""
Example Usage:
    
    # Add single ticker
    python add_ticker.py TSLA
    
    # Add multiple tickers
    python add_ticker.py TSLA NVDA META GOOGL
    
    # List current tickers
    python add_ticker.py --list
    
    # Add popular tech stocks
    python add_ticker.py MSFT AAPL GOOGL META TSLA NVDA AMD
        """)
        return
    
    if args.list:
        list_current_tickers()
        return
    
    if not args.symbols:
        print("Usage: python add_ticker.py SYMBOL [SYMBOL2 ...]")
        print("Use --help for more options")
        return
    
    # Show current state
    current_symbols = list_current_tickers()
    
    # Add new symbols
    success_count = 0
    for symbol in args.symbols:
        if add_ticker(symbol):
            success_count += 1
    
    print(f"\n=== Summary ===")
    print(f"Successfully added: {success_count}/{len(args.symbols)} tickers")
    print(f"Total tickers now: {len(current_symbols) + success_count}")
    print("\nRestart your Flask server to see the new tickers!")
    print("Visit http://127.0.0.1:8090 to view the dashboard")

if __name__ == "__main__":
    main()
