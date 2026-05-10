#!/usr/bin/env python3
"""
Flask Web Application for Stock Analysis Results
Provides a web interface to view backtest results, recommendations, and analysis data.
"""

import os
import json
import glob
import yaml
import threading
import time
from datetime import datetime, timedelta
from flask import Flask, render_template, jsonify, request, send_from_directory
from flask_cors import CORS
import pandas as pd
from analysis.fund_analyzer import FundAnalyzer
from utils.recommendation_contract import (
    normalize_recommendation_payload,
    validate_recommendation_payload,
)

app = Flask(__name__)
CORS(app)

# Configuration - Load from config file if in production
try:
    if os.environ.get('FLASK_ENV') == 'production':
        app.config.from_object('config')
    else:
        app.config['DEBUG'] = True
except:
    # Fallback configuration
    app.config['DEBUG'] = os.environ.get('FLASK_ENV') != 'production'

# Configuration
RESULTS_DIR = app.config.get('RESULTS_DIR', 'results')
CACHE_DIR = app.config.get('CACHE_DIR', 'cache')
CONFIG_FILE = app.config.get('CONFIG_FILE', 'config/system_config.yaml')
SCHEDULER_STATUS_FILE = 'data/scheduler_status.json'

# Scheduler state
scheduler_thread = None
scheduler_lock = threading.Lock()


def update_scheduler_status(status, message, progress=0, symbols_processed=0, total_symbols=0, stage=''):
    """Update the scheduler status file."""
    status_data = {
        'status': status,  # 'idle', 'running', 'completed', 'error'
        'message': message,
        'progress': progress,
        'symbols_processed': symbols_processed,
        'total_symbols': total_symbols,
        'stage': stage,  # 'fetching', 'analyzing', 'reports'
        'updated_at': datetime.now().isoformat(),
        'started_at': None
    }
    
    # Preserve started_at from existing file if running
    if os.path.exists(SCHEDULER_STATUS_FILE):
        try:
            with open(SCHEDULER_STATUS_FILE, 'r') as f:
                existing = json.load(f)
                if status == 'running' and existing.get('started_at'):
                    status_data['started_at'] = existing['started_at']
        except:
            pass
    
    if status == 'running' and not status_data['started_at']:
        status_data['started_at'] = datetime.now().isoformat()
    
    os.makedirs(os.path.dirname(SCHEDULER_STATUS_FILE), exist_ok=True)
    with open(SCHEDULER_STATUS_FILE, 'w') as f:
        json.dump(status_data, f, indent=2)


def reset_scheduler_status():
    """Reset scheduler status to idle."""
    status_data = {
        'status': 'idle',
        'message': 'Ready to run',
        'progress': 0,
        'symbols_processed': 0,
        'total_symbols': 0,
        'stage': '',
        'updated_at': datetime.now().isoformat(),
        'started_at': None
    }
    os.makedirs(os.path.dirname(SCHEDULER_STATUS_FILE), exist_ok=True)
    with open(SCHEDULER_STATUS_FILE, 'w') as f:
        json.dump(status_data, f, indent=2)


def run_scheduler_task(force=False):
    """Run the daily scheduler in background."""
    try:
        update_scheduler_status('running', 'Initializing scheduler...', 0, 0, 0, 'init')
        
        # Import scheduler components
        from scheduler.daily_scheduler import MarketDataCollector, StrategyRunner, DailyReportGenerator
        
        collector = MarketDataCollector()
        strategy_runner = StrategyRunner()
        report_generator = DailyReportGenerator()
        
        symbols = get_available_symbols()
        total = len(symbols)
        today = datetime.now()
        date_str = today.strftime('%Y%m%d')
        
        # ========== STAGE 1: FETCH DATA (0-50%) ==========
        update_scheduler_status('running', f'Stage 1/2: Fetching market data for {total} symbols...', 1, 0, total, 'fetching')
        
        for i, symbol in enumerate(symbols):
            progress = int((i / total) * 48) + 1  # 1-49%
            update_scheduler_status(
                'running', 
                f'Fetching: {symbol} ({i+1}/{total})', 
                progress,
                i + 1, 
                total,
                'fetching'
            )
            try:
                collector.fetch_latest_data(symbol)
            except Exception as e:
                print(f"Error fetching {symbol}: {e}")
        
        # ========== STAGE 2: ANALYZE & GENERATE PREDICTIONS (50-95%) ==========
        update_scheduler_status('running', f'Stage 2/2: Generating predictions for {total} symbols...', 50, 0, total, 'analyzing')
        
        os.makedirs(RESULTS_DIR, exist_ok=True)
        
        for i, symbol in enumerate(symbols):
            progress = 50 + int((i / total) * 45)  # 50-95%
            update_scheduler_status(
                'running',
                f'Analyzing: {symbol} ({i+1}/{total})',
                progress,
                i + 1,
                total,
                'analyzing'
            )
            try:
                # Run strategies
                strategy_results = strategy_runner.run_all_strategies(symbol, today)
                
                # Save backtest results
                if strategy_results:
                    backtest_file = os.path.join(RESULTS_DIR, f'{symbol}_backtest_{date_str}.json')
                    with open(backtest_file, 'w') as f:
                        json.dump(strategy_results, f, indent=2)
                
                # Generate and save recommendations based on strategy results
                recommendations = generate_recommendations_from_strategies(symbol, strategy_results, today)
                if recommendations:
                    rec_file = os.path.join(RESULTS_DIR, f'{symbol}_recommendations_{date_str}.json')
                    with open(rec_file, 'w') as f:
                        json.dump({'symbol': symbol, 'date': date_str, 'recommendations': recommendations}, f, indent=2)
                        
            except Exception as e:
                print(f"Error analyzing {symbol}: {e}")
                import traceback
                traceback.print_exc()
        
        # ========== FINALIZE ==========
        update_scheduler_status('running', 'Generating daily report...', 96, total, total, 'reports')
        
        try:
            report_generator.generate_daily_report(today)
        except Exception as e:
            print(f"Error generating report: {e}")
        
        update_scheduler_status('completed', f'Complete! Processed {total} symbols for {date_str}', 100, total, total, 'done')
        
    except Exception as e:
        update_scheduler_status('error', f'Scheduler error: {str(e)}', 0, 0, 0, 'error')
        print(f"Scheduler error: {e}")
        import traceback
        traceback.print_exc()


def generate_recommendations_from_strategies(symbol, strategy_results, date):
    """Generate recommendations from strategy results, including time estimates."""
    if not strategy_results:
        return None

    def extract_strategy_metrics(strategy_name, result):
        """Expose deterministic per-strategy metrics for richer UI diagnostics."""
        if not isinstance(result, dict):
            return {}

        if strategy_name == 'momentum_strategy':
            return {
                'momentum_score': result.get('momentum_score'),
                'avg_price': result.get('avg_price')
            }

        if strategy_name == 'mean_reversion_strategy':
            return {
                'avg_change': result.get('avg_change')
            }

        if strategy_name == 'breakout_strategy':
            return {
                'recent_high': result.get('recent_high'),
                'recent_low': result.get('recent_low')
            }

        if strategy_name == 'bollinger_strategy':
            return {
                'z_score': result.get('z_score'),
                'band_width_pct': result.get('band_width_pct'),
                'position': result.get('position'),
                'upper_band': result.get('upper_band'),
                'middle_band': result.get('middle_band'),
                'lower_band': result.get('lower_band')
            }

        return {}

    def format_strategy_details(strategy_name, result):
        """Build compact, deterministic detail text for per-strategy diagnostics."""
        if not isinstance(result, dict):
            return ''

        if strategy_name == 'momentum_strategy':
            momentum_score = result.get('momentum_score')
            avg_price = result.get('avg_price')
            if momentum_score is not None and avg_price is not None:
                return f"Momentum vs 20d average: {momentum_score:+.2%}; 20d average price: ${avg_price:.2f}"

        if strategy_name == 'mean_reversion_strategy':
            avg_change = result.get('avg_change')
            if avg_change is not None:
                return f"Average daily change (20d): {avg_change:+.2%}"

        if strategy_name == 'breakout_strategy':
            recent_high = result.get('recent_high')
            recent_low = result.get('recent_low')
            if recent_high is not None and recent_low is not None:
                return f"20d breakout range - resistance: ${recent_high:.2f}, support: ${recent_low:.2f}"

        if strategy_name == 'bollinger_strategy':
            z_score = result.get('z_score')
            band_width = result.get('band_width_pct')
            position = result.get('position')
            if z_score is not None and band_width is not None and position is not None:
                return f"Price is {position.replace('_', ' ')}, z-score {z_score:+.2f}, band width {band_width:.2%}"

        return ''
    
    # Collect all signals
    signals = []
    for strategy_name, result in strategy_results.items():
        if isinstance(result, dict) and 'signal' in result:
            signals.append({
                'strategy': strategy_name,
                'signal': result.get('signal', 'HOLD'),
                'confidence': result.get('confidence', 0.5),
                'details': format_strategy_details(strategy_name, result),
                'metrics': extract_strategy_metrics(strategy_name, result)
            })
    
    if not signals:
        return None
    
    # Determine consensus action using confidence-weighted scoring so strong
    # directional signals win over a same-count but weaker opposing side.
    buy_confidence = sum(s['confidence'] for s in signals if s['signal'] == 'BUY')
    sell_confidence = sum(s['confidence'] for s in signals if s['signal'] == 'SELL')
    hold_count = sum(1 for s in signals if s['signal'] == 'HOLD')

    if buy_confidence > sell_confidence and buy_confidence > 0:
        action = 'BUY'
    elif sell_confidence > buy_confidence and sell_confidence > 0:
        action = 'SELL'
    elif hold_count > 0:
        action = 'HOLD'
    else:
        action = 'HOLD'
    
    # Get average confidence
    avg_confidence = sum(s['confidence'] for s in signals) / len(signals) if signals else 0.5
    
    # Get current price and historical data from cache
    cache_file = os.path.join(CACHE_DIR, f'{symbol}_historical.json')
    current_price = None
    data_points = []
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'r') as f:
                data = json.load(f)
                if data.get('data_points'):
                    data_points = data['data_points']
                    # Sort by date and get latest
                    sorted_points = sorted(data_points, key=lambda x: x.get('date', ''))
                    if sorted_points:
                        current_price = sorted_points[-1].get('close')
        except Exception as e:
            print(f"Error reading cache for {symbol}: {e}")
    
    # Calculate stop loss and take profit
    if action == 'BUY' and current_price is not None:
        stop_loss = current_price * 0.95  # 5% below
        take_profit = current_price * 1.10  # 10% above
        direction = 'long'
    elif action == 'SELL' and current_price is not None:
        stop_loss = current_price * 1.05  # 5% above
        take_profit = current_price * 0.90  # 10% below
        direction = 'short'
    else:
        # HOLD and missing prices should remain neutral/non-directional.
        stop_loss = current_price
        take_profit = current_price
        direction = 'neutral'
    
    # Generate time estimate
    time_estimate = None
    if len(data_points) >= 30 and action != 'HOLD' and current_price is not None and stop_loss is not None and take_profit is not None:
        try:
            from time_estimation import create_default_ensemble
            ensemble = create_default_ensemble()
            estimate = ensemble.estimate(
                current_price=current_price,
                target_price=take_profit,
                stop_price=stop_loss,
                data_points=data_points,
                direction=direction
            )
            if estimate:
                time_estimate = estimate.to_dict()
        except Exception as e:
            print(f"Time estimation error for {symbol}: {e}")

    raw_payload = {
        'action': action,
        'confidence': avg_confidence,
        'entry_price': current_price,
        'stop_loss': stop_loss,
        'take_profit': take_profit,
        'signals': signals,
        'details': f'{action} signal based on {len(signals)} strategies',
        'time_estimate': time_estimate,
        'benchmark': {
            'spy_return_pct': None,
            'period_days': round(time_estimate.get('days_to_target')) if isinstance(time_estimate, dict) and time_estimate.get('days_to_target') else None,
        },
        'metrics': {}
    }

    normalized = normalize_recommendation_payload(
        {'symbol': symbol, 'analysis_date': str(date), 'recommendations': raw_payload},
        symbol=symbol,
        analysis_date=str(date),
        fallback_price=current_price,
    )
    valid, errors = validate_recommendation_payload(normalized)
    if not valid:
        print(f"Recommendation schema validation failed for {symbol}: {'; '.join(errors)}")
    return normalized['recommendations']

def load_config():
    """Load system configuration from YAML file."""
    try:
        with open(CONFIG_FILE, 'r') as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        return {'symbols': []}
    except Exception as e:
        print(f"Error loading config: {e}")
        return {'symbols': []}

def save_config(config):
    """Save system configuration to YAML file."""
    try:
        with open(CONFIG_FILE, 'w') as f:
            yaml.safe_dump(config, f, default_flow_style=False, indent=2)
        return True
    except Exception as e:
        print(f"Error saving config: {e}")
        return False

def get_config_symbols():
    """Get list of symbols from the configuration file."""
    config = load_config()
    return [symbol['symbol'] for symbol in config.get('symbols', []) if symbol.get('enabled', True)]

def get_available_symbols():
    """Get list of available symbols from config file."""
    try:
        with open(CONFIG_FILE, 'r') as f:
            config = yaml.safe_load(f)
        symbols = []
        for symbol_config in config.get('symbols', []):
            if symbol_config.get('enabled', True):
                symbols.append(symbol_config['symbol'])
        return sorted(symbols)
    except Exception as e:
        print(f"Error loading symbols from config: {e}")
        # Fallback to cache files if config fails
        cache_files = glob.glob(os.path.join(CACHE_DIR, '*_historical.json'))
        symbols = []
        for file in cache_files:
            symbol = os.path.basename(file).replace('_historical.json', '')
            symbols.append(symbol)
        return sorted(symbols)


def get_fund_symbols():
    """Get list of fund/ETF symbols from config file based on sector."""
    fund_sectors = {'ETF', 'Mutual Fund', 'Fund'}
    try:
        with open(CONFIG_FILE, 'r') as f:
            config = yaml.safe_load(f)
        fund_symbols = []
        for symbol_config in config.get('symbols', []):
            if symbol_config.get('enabled', True):
                sector = symbol_config.get('sector', '')
                if sector in fund_sectors:
                    fund_symbols.append(symbol_config['symbol'])
        return sorted(fund_symbols)
    except Exception as e:
        print(f"Error loading fund symbols from config: {e}")
        return []

def get_available_dates():
    """Get list of available dates from result files."""
    result_files = glob.glob(os.path.join(RESULTS_DIR, '*_backtest_*.json'))
    dates = set()
    for file in result_files:
        basename = os.path.basename(file)
        if '_backtest_' in basename:
            # Extract the date portion (last 8 digits before .json)
            # Handles both old format: symbol_backtest_YYYYMMDD.json
            # and new format: symbol_backtest_strategy_period_YYYYMMDD.json
            date_part = basename.split('_backtest_')[1].replace('.json', '')
            # Extract the actual date (last 8 digits)
            import re
            date_match = re.search(r'(\d{8})$', date_part)
            if date_match:
                dates.add(date_match.group(1))
    return sorted(list(dates), reverse=True)

def load_backtest_results(symbol, date):
    """Load backtest results for a specific symbol and date."""
    # Check if this is an algorithm-specific request (contains algorithm and timeframe)
    if '_' in symbol and any(alg in symbol for alg in ['trend_following', 'momentum', 'mean_reversion', 'bollinger']):
        # This is an algorithm-specific request like "AAPL_trend_following_30d"
        # The file format is: AAPL_backtest_trend_following_30d_20250616.json
        # But the symbol comes in as: AAPL_trend_following_30d
        parts = symbol.split('_')
        if len(parts) >= 3:
            base_symbol = parts[0]  # AAPL
            algorithm = '_'.join(parts[1:-1])  # trend_following
            timeframe = parts[-1]  # 30d
            filename = f"{base_symbol}_backtest_{algorithm}_{timeframe}_{date}.json"
            filepath = os.path.join(RESULTS_DIR, filename)
            
            if os.path.exists(filepath):
                with open(filepath, 'r') as f:
                    return json.load(f)
        return None
    
    # For general symbol requests, try the old format first
    filename = f"{symbol}_backtest_{date}.json"
    filepath = os.path.join(RESULTS_DIR, filename)
    
    if os.path.exists(filepath):
        with open(filepath, 'r') as f:
            return json.load(f)
    
    # If old format doesn't exist, try to find strategy-specific files
    # Look for any backtest file with the matching symbol and date
    pattern = f"{symbol}_backtest_*_{date}.json"
    matching_files = glob.glob(os.path.join(RESULTS_DIR, pattern))
    
    if matching_files:
        # If multiple files exist, prioritize trend_following strategy
        for file in matching_files:
            if 'trend_following' in file:
                with open(file, 'r') as f:
                    return json.load(f)
        
        # If no trend_following file, use the first available
        with open(matching_files[0], 'r') as f:
            return json.load(f)
    
    return None

def load_recommendations(symbol, date):
    """Load recommendations for a specific symbol and date."""

    def get_latest_cached_close() -> float | None:
        historical_data = load_historical_data(symbol)
        if not historical_data:
            return None
        points = historical_data.get('data_points') or historical_data.get('data') or []
        if not points:
            return None
        latest = points[-1] if isinstance(points[-1], dict) else None
        if not latest:
            return None
        try:
            return float(latest.get('close'))
        except (TypeError, ValueError):
            return None

    def normalize_payload(payload):
        fallback_price = get_latest_cached_close()
        normalized = normalize_recommendation_payload(
            payload,
            symbol=symbol,
            analysis_date=str(date),
            fallback_price=fallback_price,
        )
        valid, errors = validate_recommendation_payload(normalized)
        if not valid:
            print(f"Recommendation schema validation failed for {symbol} ({date}): {'; '.join(errors)}")
        return normalized

    # Try individual symbol file first (old format)
    filename = f"{symbol}_recommendations_{date}.json"
    filepath = os.path.join(RESULTS_DIR, filename)
    
    if os.path.exists(filepath):
        with open(filepath, 'r') as f:
            return normalize_payload(json.load(f))
    
    # Try combined recommendations file (new format)
    combined_filename = f"recommendations_{date}.json"
    combined_filepath = os.path.join(RESULTS_DIR, combined_filename)
    
    if os.path.exists(combined_filepath):
        with open(combined_filepath, 'r') as f:
            data = json.load(f)
            if symbol in data:
                symbol_data = data[symbol]
                
                # Get current price from historical data
                current_price = get_latest_cached_close() or 0
                
                # Determine the primary action based on strongest signal
                strongest_signal = "HOLD"
                max_confidence = 0
                primary_strategy = None
                
                for strategy_name, strategy_data in symbol_data.items():
                    confidence = strategy_data.get("confidence", 0)
                    signal = strategy_data.get("signal", "hold").upper()
                    
                    if confidence > max_confidence:
                        max_confidence = confidence
                        primary_strategy = strategy_name
                        
                        # Map strategy signals to trading actions
                        if signal in ["ENTRY", "BUY"]:
                            strongest_signal = "BUY"
                        elif signal in ["EXIT", "SELL"]:
                            strongest_signal = "SELL"
                        else:
                            strongest_signal = "HOLD"
                
                # Calculate entry price, stop loss, and take profit based on action
                entry_price = current_price
                stop_loss = 0
                take_profit = 0
                
                if current_price > 0:
                    if strongest_signal == "BUY":
                        # For buy signals: entry at current price, stop loss 5% below, take profit 10% above
                        entry_price = current_price
                        stop_loss = current_price * 0.95  # 5% stop loss
                        take_profit = current_price * 1.10  # 10% take profit
                    elif strongest_signal == "SELL":
                        # For sell signals: entry at current price, stop loss 5% above, take profit 10% below
                        entry_price = current_price
                        stop_loss = current_price * 1.05  # 5% stop loss (price going up)
                        take_profit = current_price * 0.90  # 10% take profit (price going down)
                    else:  # HOLD
                        # For hold signals: no directional target should be implied
                        entry_price = current_price
                        stop_loss = current_price
                        take_profit = current_price
                
                # Build reasoning from all strategies
                reasoning_parts = []
                for strategy_name, strategy_data in symbol_data.items():
                    reason = strategy_data.get('reason', '')
                    signal = strategy_data.get('signal', 'hold')
                    confidence = strategy_data.get('confidence', 0)
                    reasoning_parts.append(f"{strategy_name} ({signal}, {confidence:.1%}): {reason}")
                
                return normalize_payload({
                    "symbol": symbol,
                    "analysis_date": date,
                    "recommendations": {
                        "action": strongest_signal,
                        "confidence": max_confidence,
                        "entry_price": round(entry_price, 2),
                        "reasoning": "; ".join(reasoning_parts),
                        "stop_loss": round(stop_loss, 2),
                        "take_profit": round(take_profit, 2),
                        "primary_strategy": primary_strategy,
                        "current_price": round(current_price, 2)
                    }
                })
    
    return None

def load_historical_data(symbol):
    """Load historical price data for a symbol."""
    filename = f"{symbol}_historical.json"
    filepath = os.path.join(CACHE_DIR, filename)
    
    if os.path.exists(filepath):
        with open(filepath, 'r') as f:
            return json.load(f)
    return None

def format_currency(value):
    """Format value as currency."""
    if value is None:
        return "N/A"
    return f"${value:,.2f}"

def format_percentage(value):
    """Format value as percentage."""
    if value is None:
        return "N/A"
    return f"{value:.2f}%"

# Template filters
app.jinja_env.filters['currency'] = format_currency
app.jinja_env.filters['percentage'] = format_percentage

# Helper functions for ticker detail page
def get_latest_recommendation(symbol):
    """Get the latest recommendation for a symbol."""
    dates = get_available_dates()
    for date in dates:  # dates are sorted newest first
        recommendations = load_recommendations(symbol, date)
        if recommendations:
            return recommendations, date
    return None, None

def get_latest_backtest(symbol):
    """Get the latest backtest results for a symbol."""
    dates = get_available_dates()
    for date in dates:  # dates are sorted newest first
        backtest = load_backtest_results(symbol, date)
        if backtest:
            return backtest, date
    return None, None

def get_all_recommendations(symbol):
    """Get all recommendations for a symbol with dates."""
    all_recommendations = []
    result_files = glob.glob(os.path.join(RESULTS_DIR, f'{symbol}_recommendations_*.json'))
    
    for file in result_files:
        basename = os.path.basename(file)
        date_part = basename.split('_recommendations_')[1].replace('.json', '')
        
        try:
            with open(file, 'r') as f:
                data = json.load(f)
                data['file_date'] = date_part
                all_recommendations.append(data)
        except:
            continue
    
    # Sort by date (newest first)
    all_recommendations.sort(key=lambda x: x.get('file_date', ''), reverse=True)
    return all_recommendations

def get_all_backtests(symbol):
    """Get all backtest results for a symbol with dates."""
    all_backtests = []
    result_files = glob.glob(os.path.join(RESULTS_DIR, f'{symbol}_backtest_*.json'))
    
    for file in result_files:
        basename = os.path.basename(file)
        date_part = basename.split('_backtest_')[1].replace('.json', '')
        
        try:
            with open(file, 'r') as f:
                data = json.load(f)
                data['file_date'] = date_part
                all_backtests.append(data)
        except:
            continue
    
    # Sort by date (newest first)
    all_backtests.sort(key=lambda x: x.get('file_date', ''), reverse=True)
    return all_backtests

@app.route('/')
def index():
    """Main dashboard page."""
    try:
        symbols = get_available_symbols()
        dates = get_available_dates()
        fund_symbols = get_fund_symbols()
        print(f"Template data - Symbols: {len(symbols)}, Dates: {len(dates)}, Funds: {len(fund_symbols)}")
        return render_template('index.html', symbols=symbols, dates=dates, fund_symbols=fund_symbols)
    except Exception as e:
        print(f"Error in index route: {e}")
        import traceback
        traceback.print_exc()
        return render_template('index.html', symbols=[], dates=[], fund_symbols=[])

@app.route('/ticker/<symbol>')
def ticker_detail(symbol):
    """Ticker detail page showing comprehensive analysis."""
    symbol = symbol.upper()
    
    # Check if symbol exists
    available_symbols = get_available_symbols()
    if symbol not in available_symbols:
        return render_template('error.html', message=f"Ticker '{symbol}' not found"), 404
    
    # Get all data for this symbol
    historical_data = load_historical_data(symbol)
    latest_recommendation, latest_rec_date = get_latest_recommendation(symbol)
    latest_backtest, latest_backtest_date = get_latest_backtest(symbol)
    all_recommendations = get_all_recommendations(symbol)
    all_backtests = get_all_backtests(symbol)
    
    # Calculate current price from historical data
    current_price = None
    if historical_data and 'data_points' in historical_data:
        latest_data = historical_data['data_points'][-1] if historical_data['data_points'] else None
        if latest_data:
            current_price = latest_data.get('close')
    
    # Get best performing strategy from latest backtest
    best_strategy = None
    best_return = None
    if latest_backtest:
        best_return = -999
        for strategy_name, strategy_data in latest_backtest.items():
            if isinstance(strategy_data, dict) and 'total_returns' in strategy_data:
                if strategy_data['total_returns'] > best_return:
                    best_return = strategy_data['total_returns']
                    best_strategy = strategy_name
    
    return render_template('ticker_detail.html',
                         symbol=symbol,
                         historical_data=historical_data,
                         current_price=current_price,
                         latest_recommendation=latest_recommendation,
                         latest_rec_date=latest_rec_date,
                         latest_backtest=latest_backtest,
                         latest_backtest_date=latest_backtest_date,
                         all_recommendations=all_recommendations,
                         all_backtests=all_backtests,
                         best_strategy=best_strategy,
                         best_return=best_return)


@app.route('/fund/<symbol>')
def fund_detail(symbol):
    """
    Fund/ETF detail page with prospectus-style analysis.
    Shows comprehensive performance metrics for 1, 3, 5, and 10 year periods.
    """
    symbol = symbol.upper()
    
    # Check if symbol exists
    available_symbols = get_available_symbols()
    if symbol not in available_symbols:
        return render_template('error.html', message=f"Fund '{symbol}' not found"), 404
    
    # Load historical data
    historical_data = load_historical_data(symbol)
    
    if not historical_data or 'data_points' not in historical_data:
        return render_template('error.html', message=f"No data available for fund '{symbol}'"), 404
    
    # Initialize fund analyzer
    analyzer = FundAnalyzer(cache_dir=CACHE_DIR)
    
    # Generate comprehensive prospectus data
    prospectus_data = analyzer.generate_prospectus_data(symbol, historical_data['data_points'])
    
    # Get recommendation data if available
    latest_recommendation, latest_rec_date = get_latest_recommendation(symbol)
    
    return render_template('fund_detail.html',
                         symbol=symbol,
                         prospectus=prospectus_data,
                         historical_data=historical_data,
                         latest_recommendation=latest_recommendation,
                         latest_rec_date=latest_rec_date)


@app.route('/api/fund/<symbol>/prospectus')
def api_fund_prospectus(symbol):
    """API endpoint to get fund prospectus data."""
    symbol = symbol.upper()
    
    # Load historical data
    historical_data = load_historical_data(symbol)
    
    if not historical_data or 'data_points' not in historical_data:
        return jsonify({'error': f'No data available for {symbol}'}), 404
    
    # Initialize fund analyzer
    analyzer = FundAnalyzer(cache_dir=CACHE_DIR)
    
    # Generate prospectus data
    prospectus_data = analyzer.generate_prospectus_data(symbol, historical_data['data_points'])
    
    return jsonify(prospectus_data)


@app.route('/api/fund/<symbol>/info')
def api_fund_info(symbol):
    """API endpoint to get fund metadata (expense ratio, holdings, etc.)."""
    symbol = symbol.upper()
    
    analyzer = FundAnalyzer(cache_dir=CACHE_DIR)
    fund_info = analyzer.fetch_fund_info(symbol)
    
    if fund_info:
        return jsonify(fund_info.to_dict())
    
    return jsonify({'error': f'Unable to fetch fund info for {symbol}'}), 404


@app.route('/api/scheduler/run', methods=['POST'])
def api_run_scheduler():
    """API endpoint to trigger the daily scheduler."""
    global scheduler_thread
    
    with scheduler_lock:
        # Check if scheduler is already running
        if scheduler_thread and scheduler_thread.is_alive():
            return jsonify({
                'success': False,
                'message': 'Scheduler is already running'
            }), 409
        
        # Reset status before starting
        reset_scheduler_status()
        
        # Check force parameter
        force = request.json.get('force', False) if request.is_json else False
        
        # Start scheduler in background thread
        scheduler_thread = threading.Thread(target=run_scheduler_task, args=(force,), daemon=True)
        scheduler_thread.start()
        
        return jsonify({
            'success': True,
            'message': 'Scheduler started'
        })


@app.route('/api/scheduler/reset', methods=['POST'])
def api_reset_scheduler():
    """Reset scheduler status to idle."""
    reset_scheduler_status()
    return jsonify({'success': True, 'message': 'Status reset to idle'})


@app.route('/api/scheduler/status')
def api_scheduler_status():
    """API endpoint to get scheduler status."""
    if os.path.exists(SCHEDULER_STATUS_FILE):
        try:
            with open(SCHEDULER_STATUS_FILE, 'r') as f:
                status = json.load(f)
            
            # Check if thread is still alive
            global scheduler_thread
            if scheduler_thread and scheduler_thread.is_alive():
                status['thread_alive'] = True
            else:
                status['thread_alive'] = False
                # If status says running but thread is dead, mark as error
                if status.get('status') == 'running':
                    status['status'] = 'error'
                    status['message'] = 'Scheduler thread died unexpectedly'
            
            return jsonify(status)
        except Exception as e:
            return jsonify({
                'status': 'unknown',
                'message': f'Error reading status: {str(e)}',
                'thread_alive': False
            })
    
    return jsonify({
        'status': 'idle',
        'message': 'Scheduler has not been run yet',
        'progress': 0,
        'thread_alive': False
    })


@app.route('/api/symbols')
def api_symbols():
    """API endpoint to get available symbols."""
    return jsonify(get_available_symbols())

@app.route('/api/dates')
def api_dates():
    """API endpoint to get available dates."""
    return jsonify(get_available_dates())

@app.route('/api/backtest/<symbol>/<date>')
def api_backtest(symbol, date):
    """API endpoint to get backtest results."""
    results = load_backtest_results(symbol, date)
    if results:
        return jsonify(results)
    return jsonify({'error': 'Results not found'}), 404

@app.route('/api/recommendations/<symbol>/<date>')
def api_recommendations(symbol, date):
    """API endpoint to get recommendations."""
    recommendations = load_recommendations(symbol, date)
    if recommendations:
        return jsonify(recommendations)
    return jsonify({'error': 'Recommendations not found'}), 404

@app.route('/api/historical/<symbol>')
def api_historical(symbol):
    """API endpoint to get historical data."""
    data = load_historical_data(symbol)
    if data:
        return jsonify(data)
    return jsonify({'error': 'Historical data not found'}), 404

@app.route('/api/add_ticker', methods=['POST'])
def add_ticker():
    """Add a new ticker to the system configuration."""
    try:
        data = request.get_json()
        symbol = data.get('symbol', '').upper().strip()
        sector = data.get('sector', 'Technology').strip()
        priority = data.get('priority', 1)
        
        if not symbol:
            return jsonify({'success': False, 'error': 'Symbol is required'}), 400
        
        # Load current configuration
        config = load_config()
        
        # Check if symbol already exists in config
        existing_symbols = [s['symbol'] for s in config.get('symbols', [])]
        if symbol in existing_symbols:
            return jsonify({'success': False, 'error': f'{symbol} already exists in configuration'}), 400
        
        # Add new symbol to configuration
        new_symbol = {
            'symbol': symbol,
            'enabled': True,
            'priority': priority,
            'sector': sector,
            'custom_params': None
        }
        
        if 'symbols' not in config:
            config['symbols'] = []
        
        config['symbols'].append(new_symbol)
        
        # Save updated configuration
        if save_config(config):
            return jsonify({
                'success': True, 
                'message': f'Successfully added {symbol} to configuration',
                'symbol': new_symbol
            })
        else:
            return jsonify({'success': False, 'error': 'Failed to save configuration'}), 500
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/remove_ticker', methods=['POST'])
def remove_ticker():
    """Remove a ticker from the system configuration."""
    try:
        data = request.get_json()
        symbol = data.get('symbol', '').upper().strip()
        
        if not symbol:
            return jsonify({'success': False, 'error': 'Symbol is required'}), 400
        
        # Load current configuration
        config = load_config()
        
        # Check if symbol exists in config
        existing_symbols = [s['symbol'] for s in config.get('symbols', [])]
        if symbol not in existing_symbols:
            return jsonify({'success': False, 'error': f'{symbol} not found in configuration'}), 404
        
        # Remove symbol from configuration
        config['symbols'] = [s for s in config.get('symbols', []) if s['symbol'] != symbol]
        
        # Save updated configuration
        if save_config(config):
            # Optionally remove data files (but keep them for historical purposes)
            removed_files = []
            
            # Only remove files if explicitly requested
            if data.get('remove_files', False):
                # Remove historical data file
                historical_file = os.path.join(CACHE_DIR, f'{symbol}_historical.json')
                if os.path.exists(historical_file):
                    os.remove(historical_file)
                    removed_files.append(f'{symbol}_historical.json')
                
                # Remove all recommendation files for this symbol
                recommendation_files = glob.glob(os.path.join(RESULTS_DIR, f'{symbol}_recommendations_*.json'))
                for file in recommendation_files:
                    os.remove(file)
                    removed_files.append(os.path.basename(file))
                
                # Remove all backtest files for this symbol
                backtest_files = glob.glob(os.path.join(RESULTS_DIR, f'{symbol}_backtest_*.json'))
                for file in backtest_files:
                    os.remove(file)
                    removed_files.append(os.path.basename(file))
            
            return jsonify({
                'success': True, 
                'message': f'Successfully removed {symbol} from configuration',
                'files_removed': removed_files if removed_files else 'Configuration updated, data files preserved'
            })
        else:
            return jsonify({'success': False, 'error': 'Failed to save configuration'}), 500
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/store/info')
def api_store_info():
    """API endpoint to get information about the key/value store structure."""
    store_info = {
        'description': 'File-based key/value store for stock analysis data',
        'structure': {
            'historical_data': {
                'location': 'cache/',
                'key_pattern': '{symbol}_historical.json',
                'description': 'Historical price data for each symbol',
                'example_key': 'AAPL_historical.json'
            },
            'recommendations': {
                'location': 'results/',
                'key_pattern': '{symbol}_recommendations_{date}.json',
                'description': 'Trading recommendations for symbol on specific date',
                'example_key': 'AAPL_recommendations_20250524.json'
            },
            'backtest_results': {
                'location': 'results/',
                'key_pattern': '{symbol}_backtest_{date}.json',
                'description': 'Backtest results for all strategies on symbol for specific date',
                'example_key': 'AAPL_backtest_20250524.json'
            }
        },
        'access_patterns': {
            'get_latest': 'Iterate through available dates (newest first) to find latest data',
            'get_all_history': 'Use glob patterns to find all files for a symbol',
            'get_specific': 'Direct file access using symbol and date'
        },
        'current_statistics': {
            'total_symbols': len(get_available_symbols()),
            'total_dates': len(get_available_dates()),
            'cache_files': len(glob.glob(os.path.join(CACHE_DIR, '*_historical.json'))),
            'result_files': len(glob.glob(os.path.join(RESULTS_DIR, '*.json')))
        }
    }
    
    return jsonify(store_info)

@app.route('/api/store/keys')
def api_store_keys():
    """API endpoint to list all keys in the store."""
    keys = {
        'historical_keys': [],
        'recommendation_keys': [],
        'backtest_keys': []
    }
    
    # Get historical keys
    historical_files = glob.glob(os.path.join(CACHE_DIR, '*_historical.json'))
    for file in historical_files:
        keys['historical_keys'].append(os.path.basename(file))
    
    # Get recommendation keys
    rec_files = glob.glob(os.path.join(RESULTS_DIR, '*_recommendations_*.json'))
    for file in rec_files:
        keys['recommendation_keys'].append(os.path.basename(file))
    
    # Get backtest keys
    backtest_files = glob.glob(os.path.join(RESULTS_DIR, '*_backtest_*.json'))
    for file in backtest_files:
        keys['backtest_keys'].append(os.path.basename(file))
    
    return jsonify(keys)

@app.route('/compare')
def compare():
    """Compare multiple symbols."""
    symbols = get_available_symbols()
    dates = get_available_dates()
    return render_template('compare.html', symbols=symbols, dates=dates)

@app.route('/api/compare/<date>')
def api_compare(date):
    """API endpoint to get comparison data for all symbols on a date."""
    symbols = get_available_symbols()
    comparison_data = {}
    
    for symbol in symbols:
        backtest_results = load_backtest_results(symbol, date)
        recommendations = load_recommendations(symbol, date)
        
        if backtest_results:
            # Extract summary statistics for each strategy
            strategy_summaries = {}
            for strategy_name, strategy_data in backtest_results.items():
                if isinstance(strategy_data, dict) and 'total_returns' in strategy_data:
                    strategy_summaries[strategy_name] = {
                        'total_returns': strategy_data.get('total_returns', 0),
                        'win_rate': strategy_data.get('win_rate', 0),
                        'total_trades': strategy_data.get('total_trades', 0),
                        'final_balance': strategy_data.get('final_balance', 10000),
                        'sharpe_ratio': strategy_data.get('sharpe_ratio', 0)
                    }
            
            comparison_data[symbol] = {
                'strategies': strategy_summaries,
                'recommendations': recommendations
            }
    
    return jsonify(comparison_data)

@app.route('/health')
def health():
    """Health check endpoint."""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'available_symbols': len(get_available_symbols()),
        'available_dates': len(get_available_dates())
    })


# ════════════════════════════════════════════════════════════════════════
#  Plaid Integration Routes
# ════════════════════════════════════════════════════════════════════════

def _get_plaid_client():
    """Return a configured PlaidClientWrapper or raise RuntimeError."""
    from config.config_manager import ConfigManager
    from plaid_integration.plaid_client import get_plaid_client
    cfg = ConfigManager().get_config()
    return get_plaid_client(cfg.plaid)


@app.route('/plaid/link-token', methods=['GET'])
def plaid_link_token():
    """
    Create a Plaid Link Token.
    The browser uses this to initialise the Plaid Link widget.
    GET /plaid/link-token  →  { "link_token": "..." }
    """
    try:
        client = _get_plaid_client()
        # Use a stable user identifier; here we use a static app-level user.
        user_id = os.environ.get("PLAID_USER_ID", "stock-analyzer-user-1")
        link_token = client.create_link_token(user_id=user_id)
        return jsonify({"link_token": link_token})
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 503
    except Exception as exc:
        return jsonify({"error": f"Failed to create link token: {exc}"}), 500


@app.route('/plaid/exchange-token', methods=['POST'])
def plaid_exchange_token():
    """
    Exchange a Plaid public_token (returned by the Link widget) for an access_token.
    Stores the encrypted access_token in the database.

    POST /plaid/exchange-token
    Body (JSON): { "public_token": "...", "institution_id": "...", "institution_name": "..." }
    Response:    { "item_id": "...", "institution_name": "..." }
    """
    data = request.get_json(silent=True) or {}
    public_token = data.get("public_token")
    if not public_token:
        return jsonify({"error": "public_token is required"}), 400

    try:
        client = _get_plaid_client()
        exchange = client.exchange_public_token(public_token)
        access_token = exchange["access_token"]
        item_id      = exchange["item_id"]

        encrypted = client.encrypt_token(access_token)

        from storage.timeseries_db import TimeSeriesDB
        db = TimeSeriesDB()
        db.upsert_plaid_item(
            item_id=item_id,
            access_token_encrypted=encrypted,
            institution_id=data.get("institution_id"),
            institution_name=data.get("institution_name"),
        )

        return jsonify({
            "item_id": item_id,
            "institution_name": data.get("institution_name"),
            "status": "connected",
        })
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 503
    except Exception as exc:
        return jsonify({"error": f"Token exchange failed: {exc}"}), 500


@app.route('/plaid/sync', methods=['POST'])
def plaid_sync():
    """
    Manually trigger a Plaid sync (accounts + holdings + transactions).
    POST /plaid/sync  →  { "accounts": N, "positions": N, "new_symbols": [...], "new_transactions": N }
    """
    try:
        from config.config_manager import ConfigManager
        from storage.timeseries_db import TimeSeriesDB
        from plaid_integration.plaid_client import get_plaid_client
        from plaid_integration.accounts import sync_accounts
        from plaid_integration.transactions import sync_transactions

        config = ConfigManager().get_config()
        client = get_plaid_client(config.plaid)
        db = TimeSeriesDB()

        sync_result  = sync_accounts(db, client, config_manager=ConfigManager())
        new_tx       = sync_transactions(db, client)

        return jsonify({
            "accounts":         len(sync_result["accounts"]),
            "positions":        len(sync_result["positions"]),
            "new_symbols":      sync_result["new_symbols"],
            "new_transactions": len(new_tx),
        })
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 503
    except Exception as exc:
        return jsonify({"error": f"Sync failed: {exc}"}), 500


# ════════════════════════════════════════════════════════════════════════
#  Portfolio API Routes
# ════════════════════════════════════════════════════════════════════════

@app.route('/api/portfolio')
def api_portfolio():
    """
    Return current portfolio positions with the latest model recommendation overlaid.
    GET /api/portfolio?account_id=<optional>
    """
    try:
        from storage.timeseries_db import TimeSeriesDB
        import json

        account_id = request.args.get("account_id")
        db = TimeSeriesDB()
        positions = db.get_portfolio_positions(account_id=account_id)

        # Enrich with latest prediction
        for pos in positions:
            symbol = pos.get("symbol")
            try:
                with db.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT data FROM projections
                        WHERE symbol = ?
                        ORDER BY projection_date DESC
                        LIMIT 1
                    """, (symbol,))
                    row = cursor.fetchone()
                    if row:
                        rec = json.loads(row["data"])
                        pos["current_rec_action"]     = rec.get("action")
                        pos["current_rec_confidence"] = rec.get("confidence")
                        pos["current_rec_stop_loss"]  = rec.get("stop_loss")
                        pos["current_rec_take_profit"] = rec.get("take_profit")
            except Exception:
                pass

        return jsonify({"positions": positions, "count": len(positions)})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route('/api/portfolio/transactions')
def api_portfolio_transactions():
    """
    Return investment transactions.
    GET /api/portfolio/transactions?symbol=AAPL&start_date=2026-01-01
    """
    try:
        from storage.timeseries_db import TimeSeriesDB
        db = TimeSeriesDB()
        txs = db.get_investment_transactions(
            symbol=request.args.get("symbol"),
            account_id=request.args.get("account_id"),
            start_date=request.args.get("start_date"),
            end_date=request.args.get("end_date"),
        )
        return jsonify({"transactions": txs, "count": len(txs)})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route('/api/portfolio/accounts')
def api_portfolio_accounts():
    """Return all synced Plaid accounts."""
    try:
        from storage.timeseries_db import TimeSeriesDB
        db = TimeSeriesDB()
        return jsonify({"accounts": db.get_plaid_accounts()})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

@app.errorhandler(404)
def not_found(error):
    return render_template('error.html', message="Page not found"), 404

@app.errorhandler(500)
def internal_error(error):
    return render_template('error.html', message="Internal server error"), 500

if __name__ == '__main__':
    # Create necessary directories
    os.makedirs('templates', exist_ok=True)
    os.makedirs('static/css', exist_ok=True)
    os.makedirs('static/js', exist_ok=True)
    os.makedirs(RESULTS_DIR, exist_ok=True)
    os.makedirs(CACHE_DIR, exist_ok=True)
    
    # Development server only (PythonAnywhere will use WSGI)
    if os.environ.get('FLASK_ENV') != 'production':
        app.run(host='0.0.0.0', port=8090, debug=True)
    else:
        # Production - let WSGI handle this
        pass
