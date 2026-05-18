import json
import glob
import os

def check_all_dates(strategy):
    # Match all backtest files for this strategy
    pattern = f"results/*_backtest_{strategy}_30d_*.json"
    files = glob.glob(pattern)
    # Sort by date (suffix before .json) descending
    files.sort(key=lambda x: x.split('_')[-1], reverse=True)
    
    for f in files:
        try:
            with open(f, 'r') as jf:
                data = json.load(jf)
                total_trades = data.get('total_trades', 0)
                if total_trades > 0:
                    symbol = os.path.basename(f).split('_')[0]
                    date = os.path.basename(f).split('_')[-1].replace('.json', '')
                    return symbol, total_trades, date
        except Exception:
            continue
    return None, 0, None

s_mom, t_mom, d_mom = check_all_dates("momentum")
s_mr, t_mr, d_mr = check_all_dates("mean_reversion")

if s_mom:
    print(f"Momentum: {s_mom} ({t_mom} trades) Date: {d_mom}")
else:
    prin    prin    prin    prin    prin r:
    print(f"Mean Reversion: {s_mr} ({t_mr} trades) Date: {d_mr}")    print(f"Mean Reversion: {s_mr} ({t_mr} d")
