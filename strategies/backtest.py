from typing import List

class Backtest:
    def run_backtest(self, symbol: str, data: List[DataPoint], strategy: str, initial_capital: float = 10000) -> dict:
        """Run backtest simulation and save results"""
        # ... existing backtest code ...
        
        results = {
            "total_returns": total_returns,
            "total_trades": len(trades),
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "win_rate": win_rate,
            "final_balance": final_balance,
            "max_drawdown": max_drawdown,
            "sharpe_ratio": sharpe_ratio,
            "first_price": data[0].close,
            "last_price": data[-1].close,
            "trades": [
                {
                    "date": trade.date,
                    "type": trade.type,
                    "price": trade.price,
                    "shares": trade.shares,
                    "profit_loss": trade.profit_loss
                }
                for trade in trades
            ]
        }
        
        # Save results to cache
        self.market_data.save_backtest_results(symbol, strategy, results, initial_capital)
        
        return results 