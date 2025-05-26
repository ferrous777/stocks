#!/usr/bin/env python3
"""
Test the Prediction Performance Tracker

This script tests the prediction tracker with existing recommendation data.
"""

import os
import sys
from datetime import datetime

# Add the src directory to the path
sys.path.append('src')

from performance.prediction_tracker import PredictionTracker

def test_prediction_tracker():
    """Test the prediction tracker functionality"""
    print("🧪 Testing Prediction Performance Tracker")
    print("="*50)
    
    # Initialize tracker with a test database
    test_db_path = "data/test_prediction_tracker.db"
    os.makedirs("data", exist_ok=True)
    
    # Remove test db if it exists
    if os.path.exists(test_db_path):
        os.remove(test_db_path)
    
    tracker = PredictionTracker(test_db_path)
    
    # Test 1: Import historical predictions
    print("\n1️⃣ Testing historical prediction import...")
    imported = tracker.import_historical_predictions()
    print(f"   ✅ Imported {imported} predictions")
    
    # Test 2: Update prediction outcomes (simulated)
    print("\n2️⃣ Testing prediction outcome updates...")
    updated = tracker.update_prediction_outcomes()
    print(f"   ✅ Updated {updated} prediction outcomes")
    
    # Test 3: Calculate strategy performance
    print("\n3️⃣ Testing strategy performance calculation...")
    performance = tracker.calculate_strategy_performance()
    print(f"   ✅ Calculated performance for {len(performance)} strategies")
    
    for name, perf in list(performance.items())[:3]:  # Show top 3
        print(f"      - {name}: {perf.accuracy_rate:.1%} accuracy, {perf.total_predictions} predictions")
    
    # Test 4: Generate trading triggers
    print("\n4️⃣ Testing trading trigger generation...")
    triggers = tracker.generate_trading_triggers()
    print(f"   ✅ Generated {len(triggers)} trading triggers")
    
    for trigger in triggers[:3]:  # Show first 3
        print(f"      - {trigger.symbol} {trigger.action}: {trigger.confidence:.1%} confidence ({trigger.risk_level} risk)")
    
    # Test 5: Generate performance report
    print("\n5️⃣ Testing performance report generation...")
    report = tracker.generate_performance_report()
    report_lines = len(report.split('\n'))
    print(f"   ✅ Generated report with {report_lines} lines")
    
    # Save test report
    test_report_path = f"reports/test_prediction_performance_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
    os.makedirs("reports", exist_ok=True)
    
    with open(test_report_path, 'w') as f:
        f.write(report)
    print(f"   📄 Test report saved to: {test_report_path}")
    
    # Test 6: Get active triggers
    print("\n6️⃣ Testing active trigger retrieval...")
    active_triggers = tracker.get_active_triggers()
    print(f"   ✅ Retrieved {len(active_triggers)} active triggers")
    
    print("\n" + "="*50)
    print("🎉 All tests completed successfully!")
    print("\nTest Summary:")
    print(f"- Historical predictions imported: {imported}")
    print(f"- Prediction outcomes updated: {updated}")
    print(f"- Strategies analyzed: {len(performance)}")
    print(f"- Trading triggers generated: {len(triggers)}")
    print(f"- Active triggers available: {len(active_triggers)}")
    
    # Clean up test database
    if os.path.exists(test_db_path):
        os.remove(test_db_path)
        print("🧹 Cleaned up test database")
    
    return True

if __name__ == "__main__":
    try:
        test_prediction_tracker()
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
