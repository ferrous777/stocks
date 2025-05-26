#!/usr/bin/env python3
"""
Pytest-based Test Suite for Functional Programming Interface

This provides pytest-compatible tests for the functional interface and bridge system.
"""

import pytest
import sys
import os
from datetime import datetime, timedelta
from typing import List, Dict, Any
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from functional_interface import (
    FunctionalSignal, StrategyConfig, BacktestConfig, RecommendationConfig,
    backtest, recommend, compose_strategies, run_backtest, run_recommendations,
    STRATEGY_REGISTRY
)

from strategy_bridge import (
    discover_legacy_strategies, unified_backtest, unified_recommendations,
    create_unified_ensemble, wrap_legacy_strategy, get_migration_status
)

try:
    from market_data.data_types import HistoricalData, DataPoint
    from strategies.momentum import MomentumStrategy
    from strategies.mean_reversion import MeanReversionStrategy
    LEGACY_IMPORTS_AVAILABLE = True
except ImportError:
    LEGACY_IMPORTS_AVAILABLE = False


@pytest.fixture(scope="session")
def sample_data():
    """Create sample historical data for testing"""
    data = []
    base_date = datetime(2024, 1, 1)
    base_price = 100.0
    
    for i in range(100):
        price_change = (i % 10 - 5) * 0.5
        price = base_price + price_change + (i * 0.1)
        
        point = DataPoint(
            date=(base_date + timedelta(days=i)).strftime('%Y-%m-%d'),
            open=price - 0.5,
            high=price + 1.0,
            low=price - 1.0,
            close=price,
            volume=1000000 + (i * 1000),
            adjusted_close=price
        )
        
        hist_data = HistoricalData(
            symbol="TEST",
            data_points=[point]
        )
        data.append(hist_data)
    
    return data


@pytest.fixture
def strategy_config():
    """Standard strategy configuration for testing"""
    return StrategyConfig(
        symbol="TEST",
        timeframe="1D",
        lookback_period=20,
        parameters={}
    )


@pytest.fixture
def backtest_config():
    """Standard backtest configuration for testing"""
    return BacktestConfig(
        initial_capital=10000.0,
        position_size=0.1,
        commission=0.001,
        risk_free_rate=0.02
    )


@pytest.fixture
def recommendation_config():
    """Standard recommendation configuration for testing"""
    return RecommendationConfig(
        min_confidence=0.6,
        max_positions=5,
        risk_tolerance="medium"
    )


@pytest.fixture(scope="session")
def large_dataset():
    """Create a larger dataset for performance testing"""
    data = []
    base_date = datetime(2020, 1, 1)
    base_price = 100.0
    
    for i in range(500):  # 500 points for faster tests
        trend = i * 0.01
        volatility = ((i % 50) - 25) * 0.1
        noise = ((i % 5) - 2) * 0.05
        
        price = base_price + trend + volatility + noise
        
        point = DataPoint(
            date=(base_date + timedelta(days=i)).strftime('%Y-%m-%d'),
            open=price - 0.2,
            high=price + 0.8,
            low=price - 0.8,
            close=price,
            volume=1000000 + (i * 500),
            adjusted_close=price
        )
        
        hist_data = HistoricalData(
            symbol="PERF_TEST",
            data_points=[point]
        )
        data.append(hist_data)
    
    return data


class TestFunctionalInterfaceCore:
    """Test core functional interface functionality"""
    
    @pytest.mark.unit
    def test_strategy_registry_populated(self):
        """Test that strategy registry is properly populated"""
        assert len(STRATEGY_REGISTRY) > 0, "Strategy registry should not be empty"
        
        for strategy_name, strategy_func in STRATEGY_REGISTRY.items():
            assert callable(strategy_func), f"Strategy {strategy_name} should be callable"
    
    @pytest.mark.unit
    def test_functional_signal_creation(self):
        """Test FunctionalSignal creation and validation"""
        signal = FunctionalSignal(
            signal_type="long",
            confidence=0.8,
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=110.0,
            timestamp=datetime.now(),
            details="Test signal"
        )
        
        assert signal.signal_type == "long"
        assert signal.confidence == 0.8
        assert signal.entry_price == 100.0
        assert isinstance(signal.timestamp, datetime)
    
    @pytest.mark.unit
    def test_strategy_config_creation(self, strategy_config):
        """Test StrategyConfig creation and validation"""
        assert strategy_config.symbol == "TEST"
        assert strategy_config.timeframe == "1D"
        assert strategy_config.lookback_period == 20
        assert isinstance(strategy_config.parameters, dict)
    
    @pytest.mark.unit
    @pytest.mark.parametrize("indicator,expected_type", [
        ("rsi", float),
        ("ema", float),
        ("macd", tuple)
    ])
    def test_technical_indicators(self, indicator, expected_type):
        """Test technical indicator calculations"""
        prices = [100.0, 101.0, 99.0, 102.0, 98.0, 103.0, 97.0, 104.0, 96.0, 105.0]
        
        if indicator == "rsi":
            result = calculate_rsi(prices, 9)
            assert isinstance(result, expected_type)
            assert 0 <= result <= 100
        elif indicator == "ema":
            result = calculate_ema(prices, 5)
            assert isinstance(result, expected_type)
            assert result > 0
        elif indicator == "macd":
            result = calculate_macd(prices)
            assert isinstance(result, expected_type)
            assert len(result) == 3
            for value in result:
                assert isinstance(value, float)


class TestFunctionalBacktesting:
    """Test functional backtesting capabilities"""
    
    @pytest.mark.functional
    @pytest.mark.parametrize("strategy_name", STRATEGY_REGISTRY.keys())
    def test_run_backtest_all_strategies(self, strategy_name, sample_data):
        """Test run_backtest with all available strategies"""
        if len(sample_data) < 20:
            pytest.skip("Not enough sample data")
        
        result = run_backtest(
            strategy=strategy_name,
            data=sample_data,
            date_range=(datetime(2024, 1, 15), datetime(2024, 2, 15)),
            symbol="TEST"
        )
        
        assert "total_return" in result
        assert "trades" in result
        assert isinstance(result["total_return"], (int, float))
        assert isinstance(result["trades"], list)
    
    @pytest.mark.functional
    def test_backtest_function_direct(self, sample_data, strategy_config, backtest_config):
        """Test backtest function directly"""
        if len(sample_data) < 20:
            pytest.skip("Not enough sample data")
        
        momentum_strategy = STRATEGY_REGISTRY.get("momentum")
        assert momentum_strategy is not None
        
        result = backtest(
            signal_generator=momentum_strategy,
            data=sample_data,
            strategy_config=strategy_config,
            backtest_config=backtest_config,
            start_date=datetime(2024, 1, 15),
            end_date=datetime(2024, 2, 15)
        )
        
        assert "total_return" in result
        assert "trades" in result
        assert isinstance(result["total_return"], (int, float))
    
    @pytest.mark.functional
    def test_strategy_composition(self, sample_data, strategy_config):
        """Test strategy composition functionality"""
        if len(sample_data) < 20:
            pytest.skip("Not enough sample data")
        
        momentum_strategy = STRATEGY_REGISTRY.get("momentum")
        mean_reversion_strategy = STRATEGY_REGISTRY.get("mean_reversion")
        
        if momentum_strategy and mean_reversion_strategy:
            composed = compose_strategies(
                [momentum_strategy, mean_reversion_strategy],
                method="weighted_average",
                weights=[0.6, 0.4]
            )
            
            assert callable(composed)
            
            signals = composed(sample_data[-1:], 0, strategy_config)
            assert isinstance(signals, list)


class TestFunctionalRecommendations:
    """Test functional recommendation capabilities"""
    
    @pytest.mark.functional
    @pytest.mark.parametrize("strategy_name", list(STRATEGY_REGISTRY.keys())[:3])  # Test first 3 for speed
    def test_run_recommendations_strategies(self, strategy_name, sample_data):
        """Test run_recommendations with strategies"""
        if len(sample_data) < 20:
            pytest.skip("Not enough sample data")
        
        recommendations = run_recommendations(
            strategy=strategy_name,
            data=sample_data,
            target_date=datetime(2024, 2, 1),
            symbol="TEST"
        )
        
        assert isinstance(recommendations, list)
        
        for rec in recommendations:
            assert isinstance(rec, FunctionalSignal)
            assert rec.signal_type in ["long", "short", "hold", "exit"]
            assert 0.0 <= rec.confidence <= 1.0
    
    @pytest.mark.functional
    def test_recommend_function_direct(self, sample_data, strategy_config, recommendation_config):
        """Test recommend function directly"""
        if len(sample_data) < 20:
            pytest.skip("Not enough sample data")
        
        mean_reversion_strategy = STRATEGY_REGISTRY.get("mean_reversion")
        assert mean_reversion_strategy is not None
        
        recommendations = recommend(
            signal_generator=mean_reversion_strategy,
            data=sample_data,
            strategy_config=strategy_config,
            recommendation_config=recommendation_config,
            target_date=datetime(2024, 2, 1)
        )
        
        assert isinstance(recommendations, list)


class TestStrategyBridge:
    """Test strategy bridge functionality"""
    
    @pytest.mark.integration
    def test_legacy_strategy_discovery(self):
        """Test discovery of legacy strategy implementations"""
        strategies = discover_legacy_strategies()
        assert isinstance(strategies, dict)
        assert len(strategies) >= 0  # May be empty in test environment
        
        for path, strategy_classes in strategies.items():
            assert isinstance(strategy_classes, list)
            for cls_info in strategy_classes:
                assert "name" in cls_info
                assert "class" in cls_info
                assert "module" in cls_info
    
    @pytest.mark.integration
    def test_migration_status(self):
        """Test migration status reporting"""
        status = get_migration_status()
        
        assert "legacy_strategies" in status
        assert "functional_strategies" in status
        assert "migration_progress" in status
        
        assert isinstance(status["legacy_strategies"], int)
        assert isinstance(status["functional_strategies"], int)
        assert isinstance(status["migration_progress"], float)
        assert 0.0 <= status["migration_progress"] <= 100.0
    
    @pytest.mark.integration
    def test_unified_backtest(self, sample_data):
        """Test unified backtest function"""
        if len(sample_data) < 20:
            pytest.skip("Not enough sample data")
        
        result = unified_backtest(
            strategy="momentum",
            data=sample_data,
            start_date=datetime(2024, 1, 15),
            end_date=datetime(2024, 2, 15),
            symbol="TEST"
        )
        
        assert "total_return" in result
        assert "strategy_type" in result
        assert result["strategy_type"] == "functional"
    
    @pytest.mark.integration
    def test_unified_recommendations(self, sample_data):
        """Test unified recommendations function"""
        if len(sample_data) < 20:
            pytest.skip("Not enough sample data")
        
        recommendations = unified_recommendations(
            strategy="mean_reversion",
            data=sample_data,
            target_date=datetime(2024, 2, 1),
            symbol="TEST"
        )
        
        assert isinstance(recommendations, list)
    
    @pytest.mark.integration
    @pytest.mark.skipif(not LEGACY_IMPORTS_AVAILABLE, reason="Legacy imports not available")
    def test_legacy_strategy_wrapping(self, sample_data, strategy_config):
        """Test wrapping legacy strategies"""
        legacy_strategy = MomentumStrategy()
        wrapped = wrap_legacy_strategy(legacy_strategy)
        
        assert callable(wrapped)
        
        if len(sample_data) >= 20:
            signals = wrapped(sample_data[-1:], 0, strategy_config)
            assert isinstance(signals, list)


class TestPerformance:
    """Test performance characteristics"""
    
    @pytest.mark.performance
    @pytest.mark.slow
    def test_performance_with_large_dataset(self, large_dataset):
        """Test performance with larger datasets"""
        start_time = datetime.now()
        
        result = run_backtest(
            strategy="momentum",
            data=large_dataset,
            date_range=(datetime(2020, 6, 1), datetime(2020, 12, 1)),
            symbol="PERF_TEST"
        )
        
        end_time = datetime.now()
        execution_time = (end_time - start_time).total_seconds()
        
        # Should complete within reasonable time
        assert execution_time < 15.0, f"Backtest took {execution_time:.2f}s, should be under 15s"
        assert "total_return" in result
        assert isinstance(result["total_return"], (int, float))
    
    @pytest.mark.performance
    def test_strategy_consistency(self, large_dataset):
        """Test that strategies produce consistent results"""
        test_data = large_dataset[:50]
        
        results = []
        for i in range(3):
            result = run_backtest(
                strategy="momentum",
                data=test_data,
                date_range=(datetime(2020, 1, 15), datetime(2020, 2, 15)),
                symbol="CONSISTENCY_TEST"
            )
            results.append(result["total_return"])
        
        # All results should be identical (deterministic)
        assert results[0] == results[1] == results[2]


class TestErrorHandling:
    """Test error handling and edge cases"""
    
    @pytest.mark.unit
    def test_invalid_strategy_name(self):
        """Test handling of invalid strategy names"""
        with pytest.raises((KeyError, ValueError)):
            run_backtest(
                strategy="nonexistent_strategy",
                data=[],
                date_range=(datetime(2024, 1, 1), datetime(2024, 2, 1)),
                symbol="TEST"
            )
    
    @pytest.mark.unit
    def test_invalid_date_range(self, sample_data):
        """Test handling of invalid date ranges"""
        with pytest.raises(ValueError):
            run_backtest(
                strategy="momentum",
                data=sample_data,
                date_range=(datetime(2024, 2, 1), datetime(2024, 1, 1)),  # End before start
                symbol="TEST"
            )
    
    @pytest.mark.unit
    def test_empty_data(self):
        """Test handling of empty data"""
        with pytest.raises((ValueError, IndexError)):
            run_backtest(
                strategy="momentum",
                data=[],
                date_range=(datetime(2024, 1, 1), datetime(2024, 2, 1)),
                symbol="EMPTY"
            )
    
    @pytest.mark.unit
    def test_none_data(self):
        """Test handling of None data"""
        with pytest.raises((TypeError, ValueError)):
            run_backtest(
                strategy="momentum",
                data=None,
                date_range=(datetime(2024, 1, 1), datetime(2024, 2, 1)),
                symbol="TEST"
            )


# Benchmark utilities
@pytest.mark.performance
@pytest.mark.slow
def test_benchmark_all_strategies(large_dataset):
    """Benchmark all strategies"""
    results = {}
    
    for strategy_name in list(STRATEGY_REGISTRY.keys())[:3]:  # Test first 3 for speed
        start_time = datetime.now()
        
        try:
            result = run_backtest(
                strategy=strategy_name,
                data=large_dataset[:100],  # Smaller subset for speed
                date_range=(datetime(2020, 1, 15), datetime(2020, 3, 15)),
                symbol="BENCHMARK"
            )
            
            end_time = datetime.now()
            execution_time = (end_time - start_time).total_seconds()
            
            results[strategy_name] = {
                "execution_time": execution_time,
                "total_return": result.get("total_return", 0),
                "num_trades": len(result.get("trades", [])),
                "success": True
            }
            
            # Should complete in reasonable time
            assert execution_time < 10.0, f"{strategy_name} took {execution_time:.2f}s"
            
        except Exception as e:
            results[strategy_name] = {
                "error": str(e),
                "success": False
            }
            pytest.fail(f"Strategy {strategy_name} failed: {e}")
    
    # At least one strategy should succeed
    successful = sum(1 for r in results.values() if r["success"])
    assert successful > 0, "At least one strategy should succeed"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
