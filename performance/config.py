"""
Configuration for Prediction Performance Tracker
"""

# Database settings
DATABASE_PATH = "data/prediction_tracker.db"

# Prediction evaluation settings
MAX_HOLDING_DAYS = 30  # Maximum days to hold a position before timeout
MIN_PREDICTIONS_FOR_STRATEGY = 5  # Minimum predictions needed to consider strategy reliable
MIN_ACCURACY_FOR_RELIABLE = 0.6  # Minimum accuracy rate for a strategy to be considered reliable

# Trading trigger generation settings
MIN_TRIGGER_CONFIDENCE = 0.7  # Minimum confidence to generate a trading trigger
MIN_STRATEGY_BACKING = 1  # Minimum number of reliable strategies needed
BASE_POSITION_VALUE = 1000  # Base position size in dollars
MAX_RISK_MULTIPLIER = 2.0  # Maximum multiplier for position sizing

# Risk level thresholds
RISK_LEVELS = {
    "LOW": 0.85,    # Confidence >= 85%
    "MEDIUM": 0.75, # Confidence >= 75%
    "HIGH": 0.70    # Confidence >= 70%
}

# Time horizon thresholds (in days)
TIME_HORIZONS = {
    "SHORT": 5,   # <= 5 days
    "MEDIUM": 15, # <= 15 days
    "LONG": 30    # > 15 days
}

# Performance calculation settings
SHARPE_RATIO_CALCULATION = True
PROFIT_FACTOR_CALCULATION = True
MAX_DRAWDOWN_CALCULATION = True

# Report generation settings
REPORT_PATH = "reports/prediction_performance_{date}.md"
INCLUDE_DETAILED_STRATEGY_BREAKDOWN = True
INCLUDE_SYMBOL_ANALYSIS = True
INCLUDE_TRIGGER_REASONING = True

# Integration settings
INTEGRATE_WITH_DAILY_WORKFLOW = True
AUTO_GENERATE_TRIGGERS = True
SAVE_PERFORMANCE_METRICS = True
UPDATE_STRATEGY_WEIGHTS = True  # Future feature

# Notification settings (for future implementation)
ENABLE_NOTIFICATIONS = False
NOTIFICATION_THRESHOLD = 0.8  # Only notify for high-confidence triggers
