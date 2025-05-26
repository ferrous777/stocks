#!/usr/bin/env python3
"""
Flask Web Application for Stock Analysis Results
Provides a web interface to view backtest results, recommendations, and analysis data.
"""

import os
import json
import glob
from datetime import datetime, timedelta
from flask import Flask, render_template, jsonify, request, send_from_directory
from flask_cors import CORS
import pandas as pd

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
STATIC_DIR = app.config.get('STATIC_DIR', 'static')

def get_available_symbols():
    """Get list of available symbols from cache files."""
    cache_files = glob.glob(os.path.join(CACHE_DIR, '*_historical.json'))
    symbols = []
    for file in cache_files:
        symbol = os.path.basename(file).replace('_historical.json', '')
        symbols.append(symbol)
    return sorted(symbols)

def get_available_dates():
    """Get list of available dates from result files."""
    result_files = glob.glob(os.path.join(RESULTS_DIR, '*_backtest_*.json'))
    dates = set()
    for file in result_files:
        basename = os.path.basename(file)
        if '_backtest_' in basename:
            date_part = basename.split('_backtest_')[1].replace('.json', '')
            dates.add(date_part)
    return sorted(list(dates), reverse=True)

def load_backtest_results(symbol, date):
    """Load backtest results for a specific symbol and date."""
    filename = f"{symbol}_backtest_{date}.json"
    filepath = os.path.join(RESULTS_DIR, filename)
    
    if os.path.exists(filepath):
        with open(filepath, 'r') as f:
            return json.load(f)
    return None

def load_recommendations(symbol, date):
    """Load recommendations for a specific symbol and date."""
    filename = f"{symbol}_recommendations_{date}.json"
    filepath = os.path.join(RESULTS_DIR, filename)
    
    if os.path.exists(filepath):
        with open(filepath, 'r') as f:
            return json.load(f)
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
    symbols = get_available_symbols()
    dates = get_available_dates()
    return render_template('index.html', symbols=symbols, dates=dates)

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
    """Add a new ticker to the system."""
    try:
        data = request.get_json()
        symbol = data.get('symbol', '').upper().strip()
        
        if not symbol:
            return jsonify({'success': False, 'error': 'Symbol is required'}), 400
        
        # Check if symbol already exists
        existing_symbols = get_available_symbols()
        if symbol in existing_symbols:
            return jsonify({'success': False, 'error': f'{symbol} already exists'}), 400
        
        # Create historical data file
        historical_file = os.path.join(CACHE_DIR, f'{symbol}_historical.json')
        if not os.path.exists(historical_file):
            # Generate sample historical data
            historical_data = generate_sample_historical_data(symbol)
            with open(historical_file, 'w') as f:
                json.dump(historical_data, f, indent=2)
        
        # Create recommendation file
        today = datetime.now().strftime('%Y%m%d')
        recommendations_file = os.path.join(RESULTS_DIR, f'{symbol}_recommendations_{today}.json')
        if not os.path.exists(recommendations_file):
            recommendations_data = generate_sample_recommendations(symbol, today)
            with open(recommendations_file, 'w') as f:
                json.dump(recommendations_data, f, indent=2)
        
        # Create backtest file
        backtest_file = os.path.join(RESULTS_DIR, f'{symbol}_backtest_{today}.json')
        if not os.path.exists(backtest_file):
            backtest_data = generate_sample_backtest(symbol, today)
            with open(backtest_file, 'w') as f:
                json.dump(backtest_data, f, indent=2)
        
        return jsonify({
            'success': True, 
            'message': f'Successfully added {symbol}',
            'files_created': [
                f'{symbol}_historical.json',
                f'{symbol}_recommendations_{today}.json',
                f'{symbol}_backtest_{today}.json'
            ]
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/remove_ticker', methods=['POST'])
def remove_ticker():
    """Remove a ticker from the system."""
    try:
        data = request.get_json()
        symbol = data.get('symbol', '').upper().strip()
        
        if not symbol:
            return jsonify({'success': False, 'error': 'Symbol is required'}), 400
        
        # Check if symbol exists
        existing_symbols = get_available_symbols()
        if symbol not in existing_symbols:
            return jsonify({'success': False, 'error': f'{symbol} not found'}), 404
        
        removed_files = []
        
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
            'message': f'Successfully removed {symbol}',
            'files_removed': removed_files
        })
        
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
