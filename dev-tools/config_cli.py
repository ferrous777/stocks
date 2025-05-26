#!/usr/bin/env python3
"""
Configuration management CLI tool
"""
import argparse
import os
import sys
from typing import List

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from config.config_manager import get_config_manager, ConfigManager

def list_symbols(args):
    """List all configured symbols"""
    manager = get_config_manager()
    config = manager.get_config()
    
    print("\nConfigured Symbols:")
    print("-" * 60)
    print(f"{'Symbol':<8} {'Enabled':<8} {'Sector':<15} {'Priority':<8}")
    print("-" * 60)
    
    for symbol_config in sorted(config.symbols, key=lambda x: x.symbol):
        enabled = "✓" if symbol_config.enabled else "✗"
        sector = symbol_config.sector or "N/A"
        priority_map = {1: "High", 2: "Medium", 3: "Low"}
        priority = priority_map.get(symbol_config.priority, str(symbol_config.priority))
        
        print(f"{symbol_config.symbol:<8} {enabled:<8} {sector:<15} {priority:<8}")
    
    print(f"\nTotal: {len(config.symbols)} symbols")
    enabled_count = sum(1 for s in config.symbols if s.enabled)
    print(f"Enabled: {enabled_count} symbols")

def list_strategies(args):
    """List all configured strategies"""
    manager = get_config_manager()
    config = manager.get_config()
    
    print("\nConfigured Strategies:")
    print("-" * 80)
    print(f"{'Strategy':<25} {'Enabled':<8} {'Weight':<8} {'Min Data':<10} {'Parameters'}")
    print("-" * 80)
    
    for strategy in config.strategies:
        enabled = "✓" if strategy.enabled else "✗"
        params = str(strategy.parameters) if strategy.parameters else "None"
        if len(params) > 30:
            params = params[:27] + "..."
        
        print(f"{strategy.name:<25} {enabled:<8} {strategy.weight:<8.1f} {strategy.min_data_points:<10} {params}")
    
    print(f"\nTotal: {len(config.strategies)} strategies")
    enabled_count = sum(1 for s in config.strategies if s.enabled)
    print(f"Enabled: {enabled_count} strategies")

def add_symbol(args):
    """Add a new symbol"""
    manager = get_config_manager()
    
    priority_map = {"high": 1, "medium": 2, "low": 3}
    priority = priority_map.get(args.priority.lower(), 2)
    
    success = manager.add_symbol(args.symbol.upper(), args.sector, priority)
    if success:
        print(f"✓ Added {args.symbol.upper()}")
    else:
        print(f"✗ Failed to add {args.symbol.upper()}")

def remove_symbol(args):
    """Remove a symbol"""
    manager = get_config_manager()
    
    if args.confirm or input(f"Remove {args.symbol.upper()}? (y/N): ").lower() == 'y':
        success = manager.remove_symbol(args.symbol.upper())
        if success:
            print(f"✓ Removed {args.symbol.upper()}")
        else:
            print(f"✗ Failed to remove {args.symbol.upper()}")
    else:
        print("Cancelled")

def enable_symbol(args):
    """Enable/disable a symbol"""
    manager = get_config_manager()
    
    success = manager.enable_symbol(args.symbol.upper(), not args.disable)
    if success:
        status = "disabled" if args.disable else "enabled"
        print(f"✓ {args.symbol.upper()} {status}")
    else:
        print(f"✗ Symbol {args.symbol.upper()} not found")

def update_strategy_weight(args):
    """Update strategy weight"""
    manager = get_config_manager()
    
    success = manager.update_strategy_weight(args.strategy, args.weight)
    if success:
        print(f"✓ Updated {args.strategy} weight to {args.weight}")
    else:
        print(f"✗ Strategy {args.strategy} not found")

def show_config(args):
    """Show current configuration summary"""
    manager = get_config_manager()
    config = manager.get_config()
    
    print("\nSystem Configuration Summary")
    print("=" * 50)
    
    print(f"\nEnvironment: {config.environment}")
    print(f"Debug Mode: {config.debug_mode}")
    print(f"Log Level: {config.log_level}")
    
    print(f"\nDatabase:")
    print(f"  Path: {config.database.db_path}")
    print(f"  Backup: {config.database.backup_enabled}")
    print(f"  Retention: {config.database.retention_days} days")
    
    print(f"\nScheduling:")
    print(f"  Enabled: {config.scheduling.enabled}")
    print(f"  Market Data: {config.scheduling.market_data_time}")
    print(f"  Analysis: {config.scheduling.analysis_time}")
    print(f"  Timezone: {config.scheduling.timezone}")
    
    print(f"\nData Source:")
    print(f"  Primary: {config.data_source.primary_source}")
    print(f"  Cache: {config.data_source.cache_enabled}")
    print(f"  Rate Limit: {config.data_source.rate_limit_per_minute}/min")
    
    print(f"\nSymbols: {len(config.symbols)} total")
    enabled_symbols = [s for s in config.symbols if s.enabled]
    print(f"  Enabled: {len(enabled_symbols)}")
    
    print(f"\nStrategies: {len(config.strategies)} total")
    enabled_strategies = [s for s in config.strategies if s.enabled]
    print(f"  Enabled: {len(enabled_strategies)}")

def create_default_config(args):
    """Create default configuration file"""
    manager = get_config_manager()
    
    if manager.config_file.exists() and not args.force:
        if input("Config file exists. Overwrite? (y/N): ").lower() != 'y':
            print("Cancelled")
            return
    
    config = manager.get_default_config()
    manager.save_config(config)
    print(f"✓ Created default configuration at {manager.config_file}")

def main():
    parser = argparse.ArgumentParser(description='Stock Analysis Configuration Manager')
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # List commands
    list_parser = subparsers.add_parser('list', help='List configuration items')
    list_subparsers = list_parser.add_subparsers(dest='list_type')
    
    symbols_parser = list_subparsers.add_parser('symbols', help='List symbols')
    strategies_parser = list_subparsers.add_parser('strategies', help='List strategies')
    
    # Symbol management
    add_parser = subparsers.add_parser('add', help='Add symbol')
    add_parser.add_argument('symbol', help='Symbol to add')
    add_parser.add_argument('--sector', help='Sector classification')
    add_parser.add_argument('--priority', choices=['high', 'medium', 'low'], 
                           default='medium', help='Priority level')
    
    remove_parser = subparsers.add_parser('remove', help='Remove symbol')
    remove_parser.add_argument('symbol', help='Symbol to remove')
    remove_parser.add_argument('--confirm', action='store_true', 
                              help='Skip confirmation prompt')
    
    enable_parser = subparsers.add_parser('enable', help='Enable/disable symbol')
    enable_parser.add_argument('symbol', help='Symbol to enable/disable')
    enable_parser.add_argument('--disable', action='store_true', 
                              help='Disable instead of enable')
    
    # Strategy management
    weight_parser = subparsers.add_parser('weight', help='Update strategy weight')
    weight_parser.add_argument('strategy', help='Strategy name')
    weight_parser.add_argument('weight', type=float, help='New weight (0.0-2.0)')
    
    # Configuration management
    show_parser = subparsers.add_parser('show', help='Show configuration summary')
    
    init_parser = subparsers.add_parser('init', help='Create default configuration')
    init_parser.add_argument('--force', action='store_true', 
                            help='Overwrite existing config')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    # Route commands
    if args.command == 'list':
        if args.list_type == 'symbols':
            list_symbols(args)
        elif args.list_type == 'strategies':
            list_strategies(args)
        else:
            print("Use 'list symbols' or 'list strategies'")
    elif args.command == 'add':
        add_symbol(args)
    elif args.command == 'remove':
        remove_symbol(args)
    elif args.command == 'enable':
        enable_symbol(args)
    elif args.command == 'weight':
        update_strategy_weight(args)
    elif args.command == 'show':
        show_config(args)
    elif args.command == 'init':
        create_default_config(args)

if __name__ == "__main__":
    main()
