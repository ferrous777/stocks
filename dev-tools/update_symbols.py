#!/usr/bin/env python3
"""
Update configuration with symbols from default_symbols.json
"""
import json
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from config.config_manager import ConfigManager

def main():
    # Read default symbols
    with open('src/data/default_symbols.json', 'r') as f:
        symbols_list = json.load(f)
    
    print(f"Original symbols: {symbols_list}")
    
    # Clean up the symbols list
    cleaned_symbols = []
    seen = set()
    
    for symbol in symbols_list:
        # Remove duplicates and invalid symbols
        if symbol not in seen and symbol != "ETF":  # ETF is not a valid ticker symbol
            cleaned_symbols.append(symbol)
            seen.add(symbol)
    
    print(f"Cleaned symbols ({len(cleaned_symbols)}): {cleaned_symbols}")
    
    # Categorize symbols by type
    tech_stocks = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA"]
    mutual_funds = ["KMKNX", "FDEGX"] 
    etfs = ["QQQ", "VUG", "IWF", "SPYG", "VGT", "FDN", "VEA", "VWO", "FEZ", "EWJ", "MCHI", "INDA", "EWZ"]
    consumer_stocks = ["COST"]
    
    # Update configuration
    config_manager = ConfigManager()
    
    # Clear existing symbols
    config_manager.clear_symbols()
    
    # Add tech stocks with priority 1
    for symbol in tech_stocks:
        if symbol in cleaned_symbols:
            config_manager.add_symbol(symbol, priority=1, sector="Technology")
    
    # Add consumer stocks with priority 1  
    for symbol in consumer_stocks:
        if symbol in cleaned_symbols:
            config_manager.add_symbol(symbol, priority=1, sector="Consumer")
    
    # Add ETFs with priority 2
    for symbol in etfs:
        if symbol in cleaned_symbols:
            config_manager.add_symbol(symbol, priority=2, sector="ETF")
    
    # Add mutual funds with priority 3
    for symbol in mutual_funds:
        if symbol in cleaned_symbols:
            config_manager.add_symbol(symbol, priority=3, sector="Mutual Fund")
    
    # Save configuration
    success = config_manager.save_config()
    if success:
        print("✅ Configuration updated successfully!")
        
        # Show summary
        config = config_manager.get_config()
        symbols = config.symbols  # Access as attribute, not dict
        print(f"\nUpdated configuration with {len(symbols)} symbols:")
        
        by_priority = {}
        for sym in symbols:
            priority = sym.priority
            if priority not in by_priority:
                by_priority[priority] = []
            by_priority[priority].append(f"{sym.symbol} ({sym.sector})")
        
        for priority in sorted(by_priority.keys()):
            print(f"  Priority {priority}: {', '.join(by_priority[priority])}")
    else:
        print("❌ Failed to update configuration")

if __name__ == "__main__":
    main()
