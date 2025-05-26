#!/usr/bin/env python3
"""
Daily Prediction Performance Integration

This script integrates prediction performance tracking into the daily workflow.
It's designed to be called after the daily recommendations are generated.
"""

import os
import sys
import json
from datetime import datetime

# Add the src directory to the path
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from performance.prediction_tracker import PredictionTracker
from performance.config import (
    DATABASE_PATH, INTEGRATE_WITH_DAILY_WORKFLOW, 
    AUTO_GENERATE_TRIGGERS, REPORT_PATH
)

def run_daily_performance_analysis():
    """Run the daily prediction performance analysis"""
    if not INTEGRATE_WITH_DAILY_WORKFLOW:
        print("🚫 Daily performance analysis is disabled in config")
        return
        
    print("📊 Running daily prediction performance analysis...")
    
    try:
        # Initialize tracker
        tracker = PredictionTracker(DATABASE_PATH)
        
        # Import any new recommendations from today
        imported = tracker.import_historical_predictions()
        print(f"📥 Imported {imported} new predictions")
        
        # Update prediction outcomes
        updated = tracker.update_prediction_outcomes()
        print(f"🔄 Updated {updated} prediction outcomes")
        
        # Generate trading triggers if enabled
        triggers = []
        if AUTO_GENERATE_TRIGGERS:
            triggers = tracker.generate_trading_triggers()
            print(f"🎯 Generated {len(triggers)} trading triggers")
            
        # Generate performance report
        report = tracker.generate_performance_report()
        
        # Save report
        today = datetime.now().strftime('%Y%m%d')
        report_path = REPORT_PATH.format(date=today)
        os.makedirs(os.path.dirname(report_path), exist_ok=True)
        
        with open(report_path, 'w') as f:
            f.write(report)
            
        print(f"📄 Performance report saved to: {report_path}")
        
        # Return summary for integration with main workflow
        return {
            "status": "success",
            "imported_predictions": imported,
            "updated_outcomes": updated,
            "active_triggers": len(triggers),
            "report_path": report_path
        }
        
    except Exception as e:
        print(f"❌ Error in daily performance analysis: {e}")
        return {
            "status": "error",
            "error": str(e)
        }

def get_trading_triggers_summary():
    """Get a summary of active trading triggers for the daily report"""
    try:
        tracker = PredictionTracker(DATABASE_PATH)
        triggers = tracker.get_active_triggers()
        
        if not triggers:
            return "No active trading triggers."
            
        summary = []
        summary.append(f"🎯 **{len(triggers)} Active Trading Triggers:**")
        
        for trigger in triggers[:5]:  # Show top 5
            risk_emoji = {"LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🔴"}
            emoji = risk_emoji.get(trigger.risk_level, "⚪")
            
            summary.append(
                f"  {emoji} **{trigger.symbol}** {trigger.action} "
                f"({trigger.confidence:.0%} confidence, {trigger.risk_level} risk)"
            )
            
        if len(triggers) > 5:
            summary.append(f"  ... and {len(triggers) - 5} more")
            
        return "\n".join(summary)
        
    except Exception as e:
        return f"Error getting trading triggers: {e}"

def get_strategy_performance_summary():
    """Get a summary of strategy performance for the daily report"""
    try:
        tracker = PredictionTracker(DATABASE_PATH)
        performance = tracker.calculate_strategy_performance()
        
        if not performance:
            return "No strategy performance data available."
            
        # Sort by accuracy rate
        sorted_strategies = sorted(performance.items(), 
                                 key=lambda x: x[1].accuracy_rate, reverse=True)
        
        summary = []
        summary.append("📈 **Strategy Performance (Top 3):**")
        
        for name, perf in sorted_strategies[:3]:
            accuracy_emoji = "🎯" if perf.accuracy_rate >= 0.7 else "📊" if perf.accuracy_rate >= 0.6 else "📉"
            summary.append(
                f"  {accuracy_emoji} **{name}**: {perf.accuracy_rate:.1%} accuracy, "
                f"{perf.win_rate:.1%} win rate ({perf.total_predictions} predictions)"
            )
            
        return "\n".join(summary)
        
    except Exception as e:
        return f"Error getting strategy performance: {e}"

if __name__ == "__main__":
    # Run the daily analysis
    result = run_daily_performance_analysis()
    
    if result["status"] == "success":
        print("✅ Daily prediction performance analysis completed successfully")
        
        # Print summaries
        print("\n" + "="*50)
        print("TRADING TRIGGERS SUMMARY")
        print("="*50)
        print(get_trading_triggers_summary())
        
        print("\n" + "="*50)  
        print("STRATEGY PERFORMANCE SUMMARY")
        print("="*50)
        print(get_strategy_performance_summary())
        
    else:
        print(f"❌ Daily analysis failed: {result['error']}")
        sys.exit(1)
