import argparse
from datetime import datetime, timedelta
import json
import os
from market_data.market_data import MarketData, FundamentalsError
from market_data.market_data_storage import MarketDataStorage, CacheWriteError
from strategies.strategy import Strategy
from market_data.data_types import BacktestResult, TradeMetrics, Trade
import sys
from tabulate import tabulate
from market_data.market_data import MarketData
from typing import Dict, List
from recommendations.recommendation_engine import RecommendationEngine

DEFAULT_SYMBOLS_FILE = "src/data/default_symbols.json"

def ensure_data_dir():
    """Ensure the data directory exists and create default symbols file if needed"""
    os.makedirs(os.path.dirname(DEFAULT_SYMBOLS_FILE), exist_ok=True)
    
    # Create default symbols file if it doesn't exist
    if not os.path.exists(DEFAULT_SYMBOLS_FILE):
        default_symbols = [
            "AAPL",
            "MSFT",
            "GOOGL",
            "AMZN",
            "NVDA",
            "HALO",
            "CPRX",
            "CORT",
            "EXEL",
            "LGND"
        ]
        with open(DEFAULT_SYMBOLS_FILE, 'w') as f:
            json.dump(default_symbols, f, indent=4)

def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(description='Stock Market Analysis Tool')
    parser.add_argument('--source', type=str, help='JSON file with symbols to analyze')
    parser.add_argument('--symbol', type=str, help='Individual stock symbol(s) (e.g., AAPL or AAPL MSFT)')
    parser.add_argument('--start', type=str, help='Start date (YYYY-MM-DD)', 
                       default=(datetime.now() - timedelta(days=3*365)).strftime('%Y-%m-%d'))
    parser.add_argument('--end', type=str, help='End date (YYYY-MM-DD)', 
                       default=datetime.now().strftime('%Y-%m-%d'))
    parser.add_argument('--cache-dir', type=str, default='cache', help='Cache directory path')
    parser.add_argument('--fundamentals', action='store_true', help='Fetch fundamental data')
    parser.add_argument('--force', action='store_true', help='Force refresh data from source')
    parser.add_argument('--debug', action='store_true', help='Enable debug output')
    parser.add_argument('--analyze', action='store_true', help='Run strategy analysis')
    parser.add_argument('--backtest', action='store_true', help='Run strategy backtest')
    parser.add_argument('--signals', action='store_true', help='Show detailed signal history')
    parser.add_argument('--verbose', action='store_true', help='Show detailed output')
    parser.add_argument('--grouped', action='store_true', help='Group results by symbol instead of strategy')
    return parser.parse_args()

def debug_print(msg: str, debug: bool = False):
    """Print debug messages if debug mode is enabled"""
    if debug:
        print(f"DEBUG: {msg}")

def get_market_data(symbol: str, start_date: str, end_date: str, storage: MarketDataStorage, force: bool = False, debug: bool = False):
    """Get market data, checking cache first"""
    debug_print(f"Getting market data for {symbol} from {start_date} to {end_date}", debug)
    
    if not force:
        debug_print("Checking cache for market data", debug)
        data = storage.get_historical_data(symbol, start_date, end_date)
        if data is not None:
            debug_print("Found cached market data", debug)
            print("Retrieved market data from cache")
            return data
    
    debug_print("Fetching market data from source", debug)
    data = MarketData.get_historical_data(symbol, start_date, end_date)
    debug_print(f"Fetched market data with {len(data.data_points)} data points", debug)
    
    debug_print("Saving market data to cache", debug)
    storage.save_historical_data(symbol, data)
    debug_print("Successfully saved to cache", debug)
    
    print("Retrieved market data from source")
    return data

def get_fundamentals(symbol: str, storage: MarketDataStorage, force: bool = False, debug: bool = False):
    """Get fundamental data, checking cache first"""
    debug_print(f"Getting fundamental data for {symbol}", debug)
    
    if not force:
        debug_print("Checking cache for fundamental data", debug)
        data = storage.get_fundamentals(symbol)
        if data is not None:
            debug_print(f"Found cached fundamental data", debug)
            print("Retrieved fundamental data from cache")
            return data
    
    debug_print("Fetching fundamental data from market", debug)
    data = MarketData.get_fundamentals(symbol)
    
    if data.failed_attributes:
        print("\nWarning: Some fundamental data components failed to fetch:")
        for failure in data.failed_attributes:
            print(f"- {failure}")
    
    debug_print(f"Fetched fundamental data", debug)
    
    debug_print("Saving fundamental data to cache", debug)
    storage.save_fundamentals(symbol, data)
    debug_print("Successfully saved fundamentals to cache", debug)
    
    print("Retrieved fundamental data from market")
    return data

def load_strategies() -> list[Strategy]:
    """Load available strategy implementations"""
    from strategies.moving_average import MovingAverageStrategy
    from strategies.volume_price import VolumePriceStrategy
    from strategies.macd import MACDStrategy
    from strategies.trend import TrendFollowingStrategy
    from strategies.bollinger import BollingerBandsStrategy
    from strategies.ensemble import EnsembleStrategy
    
    base_strategies = [
        MovingAverageStrategy(),
        VolumePriceStrategy(),
        MACDStrategy(),
        TrendFollowingStrategy(),
        BollingerBandsStrategy()
    ]
    
    # Add ensemble strategy that combines all others
    return base_strategies + [EnsembleStrategy(base_strategies)]

def format_backtest_table(summaries: Dict[str, Dict], strategy_name: str) -> str:
    """Format backtest results as a table, grouped by strategy"""
    headers = [
        "Symbol",
        "Signals", 
        "Strat Tot Ret", "Strat Ann Ret", "Trades",
        "B&H Tot Ret", "B&H Ann Ret"
    ]
    
    rows = []
    for symbol, summary in summaries.items():
        sr = summary['strategy_returns']
        bh = summary['buy_and_hold']
        
        rows.append([
            symbol,
            summary['total_trades'],
            f"{sr['total_return']:.2%}",
            f"{sr['annualized_return']:.2%}",
            sr['total_trades_executed'],
            f"{bh['total_return']:.2%}",
            f"{bh['annualized_return']:.2%}"
        ])
    
    return f"\n{strategy_name} Results:\n" + tabulate(rows, headers=headers, tablefmt="grid")

def format_grouped_table(all_results: Dict[str, Dict[str, Dict]], symbol: str) -> str:
    """Format backtest results as a table, grouped by symbol"""
    headers = [
        "Strategy",
        "Signals", 
        "Strat Tot Ret", "Strat Ann Ret", "Trades",
        "B&H Tot Ret", "B&H Ann Ret"
    ]
    
    rows = []
    # Find first strategy that has data for this symbol
    bh = None
    for strategy_results in all_results.values():
        if symbol in strategy_results:
            bh = strategy_results[symbol]['buy_and_hold']
            break
    
    if bh is None:
        return f"\n{symbol} Results:\nNo data available"
    
    for strategy_name, summaries in all_results.items():
        if symbol not in summaries:
            # Skip strategies that don't have data for this symbol
            continue
            
        summary = summaries[symbol]
        sr = summary['strategy_returns']
        
        rows.append([
            strategy_name,
            summary['total_trades'],
            f"{sr['total_return']:.2%}",
            f"{sr['annualized_return']:.2%}",
            sr['total_trades_executed'],
            f"{bh['total_return']:.2%}",
            f"{bh['annualized_return']:.2%}"
        ])
    
    if not rows:
        return f"\n{symbol} Results:\nNo strategy results available"
    
    return f"\n{symbol} Results:\n" + tabulate(rows, headers=headers, tablefmt="grid")

def load_symbols(source_file: str) -> List[str]:
    """Load symbols from JSON file"""
    ensure_data_dir()
    
    if not os.path.exists(source_file):
        raise FileNotFoundError(f"Symbols file not found: {source_file}")
        
    with open(source_file, 'r') as f:
        try:
            data = json.load(f)
            if not isinstance(data, list):
                raise ValueError("Symbols file must contain a list of symbols")
            return data
        except json.JSONDecodeError:
            raise ValueError(f"Invalid JSON in symbols file: {source_file}")

def format_analysis_table(results: Dict[str, Dict], strategy_name: str) -> str:
    """Format analysis results as a table, grouped by strategy"""
    headers = [
        "Symbol",
        "Signal",
        "Confidence",
        "Details"
    ]
    
    rows = []
    for symbol, analysis in results.items():
        rows.append([
            symbol,
            analysis['signal'],
            f"{analysis['confidence']:.1%}",
            analysis['details']
        ])
    
    return f"\n{strategy_name} Analysis:\n" + tabulate(rows, headers=headers, tablefmt="grid")

def format_grouped_analysis_table(all_results: Dict[str, Dict[str, Dict]], symbol: str) -> str:
    """Format analysis results as a table, grouped by symbol"""
    headers = [
        "Strategy",
        "Signal",
        "Confidence",
        "Details"
    ]
    
    rows = []
    for strategy_name, results in all_results.items():
        if symbol not in results:
            continue
            
        analysis = results[symbol]
        rows.append([
            strategy_name,
            analysis['signal'],
            f"{analysis['confidence']:.1%}",
            analysis['details']
        ])
    
    if not rows:
        return f"\n{symbol} Analysis:\nNo analysis results available"
    
    return f"\n{symbol} Analysis:\n" + tabulate(rows, headers=headers, tablefmt="grid")

def convert_backtest_result(result: BacktestResult) -> Dict:
    """Convert BacktestResult object to dictionary format"""
    return {
        'strategy_returns': {
            'total_return': result.strategy_returns.total_return,
            'annualized_return': result.strategy_returns.annualized_return,
            'total_trades_executed': result.strategy_returns.total_trades_executed,
            'avg_return_per_trade': result.strategy_returns.avg_return_per_trade
        },
        'buy_and_hold': result.buy_and_hold,
        'total_trades': result.total_trades
    }

def process_group(group_name: str, symbols_data: Dict[str, Dict], args: argparse.Namespace, 
                 market: MarketData, strategies: List[Strategy], engine: RecommendationEngine):
    """Process a group of symbols"""
    print(f"\nProcessing {group_name} ({len(symbols_data)} symbols):")
    
    # Store results for all strategies
    analysis_results = {}
    backtest_results = {}
    
    # Run each strategy
    for strategy in strategies:
        if args.verbose:
            print(f"\nRunning {strategy.name}...")
        
        # Add data to strategy
        for symbol, data in symbols_data.items():
            strategy.add_data(symbol, data['historical'], data.get('fundamental'))
        
        # Run analysis if requested
        if args.analyze:
            analysis_results[strategy.name] = strategy.analyze()
            
        # Run backtest if requested
        if args.backtest:
            raw_results = strategy.backtest(
                start_date=datetime.strptime(args.start, '%Y-%m-%d'),
                end_date=datetime.strptime(args.end, '%Y-%m-%d')
            )
            # Convert BacktestResult objects to dictionaries
            backtest_results[strategy.name] = {
                symbol: convert_backtest_result(result)
                for symbol, result in raw_results.items()
            }
    
    # Display results
    if args.analyze:
        if args.grouped:
            for symbol in symbols_data.keys():
                print(format_grouped_analysis_table(analysis_results, symbol))
        else:
            for strategy_name, results in analysis_results.items():
                print(format_analysis_table(results, strategy_name))
    
    if args.backtest:
        if args.grouped:
            for symbol in symbols_data.keys():
                print(format_grouped_table(backtest_results, symbol))
        else:
            for strategy_name, results in backtest_results.items():
                print(format_backtest_table(results, strategy_name))
    
    # Generate recommendations if we have both analysis and backtest results
    if args.analyze and args.backtest:
        recommendations = engine.generate_recommendations(
            symbols_data.keys(),
            analysis_results,
            backtest_results
        )
        print("\nRecommendations:")
        for symbol, rec in recommendations.items():
            print(f"\n{symbol}:")
            print(f"Action: {rec.action}")
            print(f"Confidence: {rec.confidence:.1%}")
            print(f"Supporting Strategies: {', '.join(rec.supporting_strategies)}")
            print(f"Details: {rec.details}")

def main():
    args = parse_args()
    debug = args.debug
    
    # Get symbols either from command line or file
    if args.symbol:
        symbols = args.symbol.split()
    else:
        try:
            symbols = load_symbols(args.source)
        except (FileNotFoundError, ValueError) as e:
            print(f"Error loading symbols: {str(e)}")
            return 1
    
    if args.verbose:
        print(f"\nProcessing {len(symbols)} symbol(s)...")
    
    # Initialize market data
    market = MarketData(cache_dir=args.cache_dir)
    
    # Load market data
    historical_data = {}
    fundamental_data = {}
    
    for symbol in symbols:
        if args.verbose:
            print(f"\nProcessing {symbol}:")
        historical_data[symbol], fundamental_data[symbol] = market.get_data(
            symbol=symbol,
            start_date=datetime.strptime(args.start, '%Y-%m-%d'),
            end_date=datetime.strptime(args.end, '%Y-%m-%d'),
            include_fundamentals=args.fundamentals,
            force_refresh=args.force
        )
    
    # Load strategies
    strategies = load_strategies()
    
    if args.verbose:
        print(f"\nRunning {len(strategies)} strategies:")
    
    # Initialize recommendation engine if needed
    engine = None
    if args.analyze and args.backtest:
        engine = RecommendationEngine()
    
    # Process all symbols
    symbols_data = {}
    for symbol in symbols:
        historical, fundamental = market.get_data(
            symbol=symbol,
            start_date=datetime.strptime(args.start, '%Y-%m-%d'),
            end_date=datetime.strptime(args.end, '%Y-%m-%d'),
            include_fundamentals=args.fundamentals,
            force_refresh=args.force
        )
        symbols_data[symbol] = {
            'historical': historical,
            'fundamental': fundamental
        }
    
    # Process the group
    process_group("All Symbols", symbols_data, args, market, strategies, engine)
    
    return 0

if __name__ == "__main__":
    sys.exit(main())