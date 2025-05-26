# Strategy Migration Guide

This guide explains how to migrate from the legacy class-based strategy system to the new functional interface while maintaining backward compatibility.

## Overview

The functional interface provides a simplified, composable approach to trading strategies while the strategy bridge ensures existing code continues to work during the transition.

## Migration Phases

### Phase 1: Bridge Integration (Complete)
- ✅ Strategy bridge implemented
- ✅ Automatic legacy strategy discovery
- ✅ Unified interface functions created
- ✅ Backward compatibility maintained

### Phase 2: Gradual Migration (In Progress)
- 🔄 Convert strategies to functional interface
- 🔄 Update calling code to use unified functions
- 🔄 Create comprehensive tests

### Phase 3: Legacy Deprecation (Future)
- ⏳ Mark legacy strategies as deprecated
- ⏳ Remove legacy implementations
- ⏳ Clean up bridge code

## Quick Start

### Using the Unified Interface

```python
from strategy_bridge import unified_backtest, unified_recommendations

# Works with both legacy and functional strategies
result = unified_backtest("MomentumStrategy", data, start_date, end_date)
result = unified_backtest("momentum", data, start_date, end_date)

# Same API for recommendations
signals = unified_recommendations("TrendFollowingStrategy", data, target_date)
signals = unified_recommendations("trend_following", data, target_date)
```

### Creating Mixed Ensembles

```python
from strategy_bridge import create_unified_ensemble

# Mix legacy and functional strategies
ensemble = create_unified_ensemble([
    "MomentumStrategy",      # Legacy class
    "momentum",              # Functional equivalent
    "TrendFollowingStrategy", # Legacy class
    "macd"                   # Functional strategy
], weights=[0.3, 0.3, 0.2, 0.2])
```

## Migration Examples

### Before (Legacy Class-Based)

```python
# Old way - class-based
from strategies.momentum import MomentumStrategy
from strategies.trend import TrendFollowingStrategy

# Create strategy instances
momentum = MomentumStrategy()
trend = TrendFollowingStrategy()

# Add data
momentum.add_data("AAPL", historical_data)
trend.add_data("AAPL", historical_data)

# Run backtest
momentum_result = momentum.backtest(start_date, end_date)["AAPL"]
trend_result = trend.backtest(start_date, end_date)["AAPL"]

# Get recommendations
momentum_signals = momentum.analyze(target_date)["AAPL"]
trend_signals = trend.analyze(target_date)["AAPL"]
```

### After (Unified Functional Interface)

```python
# New way - functional interface
from strategy_bridge import unified_backtest, unified_recommendations

# Run backtests directly
momentum_result = unified_backtest("momentum", data, start_date, end_date)
trend_result = unified_backtest("trend_following", data, start_date, end_date)

# Get recommendations directly
momentum_signals = unified_recommendations("momentum", data, target_date)
trend_signals = unified_recommendations("trend_following", data, target_date)
```

### Ensemble Creation

```python
# Before - Manual ensemble
from strategies.ensemble import EnsembleStrategy

ensemble = EnsembleStrategy([momentum, trend])
ensemble.add_data("AAPL", historical_data)
ensemble_result = ensemble.backtest(start_date, end_date)["AAPL"]

# After - Functional composition
from strategy_bridge import create_unified_ensemble
from functional_interface import backtest, BacktestConfig

ensemble_generator, ensemble_config = create_unified_ensemble([
    "momentum", "trend_following"
], weights=[0.6, 0.4])

ensemble_result = backtest(
    signal_generator=ensemble_generator,
    data=data,
    strategy_config=ensemble_config,
    backtest_config=BacktestConfig(initial_capital=10000.0),
    start_date=start_date,
    end_date=end_date
)
```

## Strategy Conversion Process

### 1. Analyze Legacy Strategy

```python
# Example legacy strategy structure
class MomentumStrategy(Strategy):
    def __init__(self):
        super().__init__(name="Momentum Strategy", description="...")
        self.rsi_period = 14
        self.rsi_oversold = 30
        self.rsi_overbought = 70
    
    def generate_signals(self, data_points, index):
        # Strategy logic here
        return signal_type, confidence, details
```

### 2. Create Functional Equivalent

```python
# Functional equivalent
from functional_interface import FunctionalSignal, StrategyConfig

def momentum_signal_generator(data: List[HistoricalData], 
                            config: StrategyConfig, 
                            current_index: int) -> FunctionalSignal:
    """Momentum strategy signal generator"""
    
    # Extract parameters from config
    rsi_period = config.params.get('rsi_period', 14)
    rsi_oversold = config.params.get('rsi_oversold', 30)
    rsi_overbought = config.params.get('rsi_overbought', 70)
    
    # Strategy logic (same as legacy)
    # ... calculate indicators ...
    
    return FunctionalSignal(
        signal=signal_type,
        confidence=confidence,
        details=details,
        metadata={"rsi": rsi_value}
    )

def create_momentum_strategy():
    """Strategy factory function"""
    config = StrategyConfig(
        name="momentum",
        params={
            'rsi_period': 14,
            'rsi_oversold': 30,
            'rsi_overbought': 70
        },
        min_required_points=20,
        profit_target=0.1,
        stop_loss=0.05
    )
    return momentum_signal_generator, config
```

### 3. Register Strategy

```python
# Add to strategy registry
from functional_interface import STRATEGY_REGISTRY

STRATEGY_REGISTRY['momentum'] = create_momentum_strategy
```

## Testing Migration

### 1. Consistency Tests

```python
def test_legacy_vs_functional_consistency():
    """Test that legacy and functional implementations produce similar results"""
    
    # Setup test data
    data = create_test_data()
    start_date = datetime(2024, 1, 1)
    end_date = datetime(2024, 2, 1)
    
    # Test legacy (wrapped)
    legacy_result = unified_backtest("MomentumStrategy", data, start_date, end_date)
    
    # Test functional
    functional_result = unified_backtest("momentum", data, start_date, end_date)
    
    # Compare results
    assert abs(legacy_result.strategy_returns.total_return - 
              functional_result.strategy_returns.total_return) < 0.01
    
    assert abs(legacy_result.total_trades - functional_result.total_trades) <= 1
```

### 2. Performance Tests

```python
def test_performance_comparison():
    """Compare performance between approaches"""
    import time
    
    data = create_large_dataset()  # e.g., 1000+ data points
    
    # Time legacy approach
    start_time = time.time()
    legacy_result = unified_backtest("MomentumStrategy", data, start_date, end_date)
    legacy_time = time.time() - start_time
    
    # Time functional approach
    start_time = time.time()
    functional_result = unified_backtest("momentum", data, start_date, end_date)
    functional_time = time.time() - start_time
    
    print(f"Legacy time: {legacy_time:.3f}s")
    print(f"Functional time: {functional_time:.3f}s")
    print(f"Speedup: {legacy_time/functional_time:.2f}x")
```

## Best Practices

### 1. Incremental Migration

- Start with simple strategies
- Test each migration thoroughly
- Keep legacy code until fully validated
- Use bridge for transition period

### 2. Code Organization

```
strategies/
├── functional/           # New functional strategies
│   ├── __init__.py
│   ├── momentum.py
│   ├── trend.py
│   └── macd.py
├── legacy/              # Original class-based strategies
│   ├── momentum.py      # Move here during transition
│   ├── trend.py
│   └── ensemble.py
└── bridge.py           # Bridge integration
```

### 3. Configuration Management

```python
# Centralized strategy configurations
STRATEGY_CONFIGS = {
    'momentum': {
        'rsi_period': 14,
        'rsi_oversold': 30,
        'rsi_overbought': 70,
        'min_required_points': 20
    },
    'trend_following': {
        'trend_period': 20,
        'breakout_threshold': 2.0,
        'min_trend_strength': 0.6,
        'min_required_points': 25
    }
}
```

### 4. Error Handling

```python
def safe_strategy_execution(strategy_name, data, **kwargs):
    """Safe strategy execution with fallbacks"""
    try:
        # Try functional first
        return unified_backtest(strategy_name, data, **kwargs)
    except Exception as e:
        logger.warning(f"Functional strategy failed: {e}")
        
        # Fallback to legacy if available
        legacy_name = f"{strategy_name}Strategy"
        if legacy_name in bridge.legacy_strategies:
            return unified_backtest(legacy_name, data, **kwargs)
        
        raise
```

## Migration Checklist

### For Each Strategy:

- [ ] Analyze legacy implementation
- [ ] Create functional equivalent
- [ ] Write consistency tests
- [ ] Performance benchmark
- [ ] Update documentation
- [ ] Register in strategy registry
- [ ] Test ensemble integration
- [ ] Validate edge cases

### For Calling Code:

- [ ] Replace direct strategy instantiation
- [ ] Use unified interface functions
- [ ] Update configuration management
- [ ] Add error handling
- [ ] Test integration points
- [ ] Update documentation

### For Infrastructure:

- [ ] Set up bridge monitoring
- [ ] Create migration metrics
- [ ] Plan deprecation timeline
- [ ] Update CI/CD pipelines
- [ ] Train team on new interface

## Common Issues and Solutions

### Issue: Legacy Strategy Not Found
```python
# Problem: ImportError when bridge tries to discover strategies
# Solution: Check module paths and ensure strategies inherit from Strategy base class

# Check bridge discovery
report = bridge.get_migration_report()
print(report['strategies'])
```

### Issue: Parameter Mismatch
```python
# Problem: Legacy and functional strategies use different parameters
# Solution: Create parameter mapping in wrapper

def create_legacy_wrapper_with_mapping(strategy_instance):
    parameter_mapping = {
        'legacy_param': 'functional_param'
    }
    # Apply mapping logic
```

### Issue: Performance Degradation
```python
# Problem: Functional interface slower than expected
# Solution: Profile and optimize hot paths

import cProfile
cProfile.run('unified_backtest(...)')
```

## Support and Resources

- 📚 **Documentation**: See `docs/functional_interface.md`
- 🐛 **Issues**: Report migration issues with detailed error logs
- 💬 **Questions**: Ask on team channel with `#migration` tag
- 🧪 **Testing**: Use `bridge_demo.py` for comprehensive testing

## Next Steps

1. **Review Current State**: Run `bridge_demo.py` to see migration status
2. **Pick Strategy**: Choose a legacy strategy to migrate
3. **Create Functional Version**: Follow conversion process
4. **Test Thoroughly**: Use consistency and performance tests
5. **Update Callers**: Gradually move to unified interface
6. **Monitor**: Track performance and correctness

The migration is designed to be gradual and safe. You can start using the unified interface immediately with existing strategies while slowly converting to the functional approach.
