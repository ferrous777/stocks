#!/usr/bin/env python3
"""
Integration Tests for Strategy Bridge System

Tests the integration between legacy strategies and functional interface,
ensuring seamless interoperability and migration capabilities.
"""

import pytest
import sys
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any
import tempfile
import shutil

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from strategy_bridge import (
    discover_legacy_strategies, unified_backtest, unified_recommendations,
    create_unified_ensemble, wrap_legacy_strategy, get_migration_status,
    migrate_strategy_results, generate_migration_report
)

from functional_interface import (
    FunctionalSignal, StrategyConfig, BacktestConfig, RecommendationConfig,
    STRATEGY_REGISTRY, run_backtest, run_recommendations
)

try:
    from market_data.data_types import HistoricalData, DataPoint
    from strategies.strategy import Strategy
    from strategies.momentum import MomentumStrategy
    from strategies.mean_reversion import MeanReversionStrategy
    from strategies.macd import MACDStrategy
    LEGACY_IMPORTS_AVAILABLE = True
except ImportError:
    LEGACY_IMPORTS_AVAILABLE = False
    print("⚠️  Legacy strategy imports not available - some tests will be skipped")


@pytest.fixture(scope="session")
def integration_data():
    """Create comprehensive test data for integration testing"""
    data = []
    base_date = datetime(2023, 1, 1)
    base_price = 150.0
    
    # Create 200 data points with realistic market patterns
    for i in range(200):
        # Market trends and cycles
        long_trend = i * 0.02  # Long-term upward trend
        medium_cycle = 10 * (i % 40 - 20) * 0.01  # Medium-term cycles
        short_noise = (i % 5 - 2) * 0.1  # Short-term noise
        
        # Market volatility events
        if i % 50 == 25:  # Periodic volatility spikes
            volatility_spike = 5.0 if i % 100 == 25 else -3.0
        else:
            volatility_spike = 0.0
        
        price = base_price + long_trend + medium_cycle + short_noise + volatility_spike
        
        # Ensure price doesn't go negative
        price = max(price, 10.0)
        
        point = DataPoint(
            date=(base_date + timedelta(days=i)).strftime('%Y-%m-%d'),
            open=price - 0.3,
            high=price + max(0.5, abs(short_noise) * 2),
            low=price - max(0.5, abs(short_noise) * 2),
            close=price,
            volume=1000000 + int(abs(volatility_spike) * 100000),
            adjusted_close=price
        )
        
        hist_data = HistoricalData(
            symbol="INTEGRATION_TEST",
            data_points=[point]
        )
        data.append(hist_data)
    
    return data


@pytest.fixture
def temp_results_dir():
    """Create temporary directory for test results"""
    temp_dir = tempfile.mkdtemp(prefix="bridge_test_")
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


class TestStrategyDiscovery:
    """Test strategy discovery and cataloging"""
    
    @pytest.mark.integration
    def test_discover_legacy_strategies_comprehensive(self):
        """Test comprehensive discovery of legacy strategies"""
        strategies = discover_legacy_strategies()
        
        assert isinstance(strategies, dict)
        
        # Should find strategies in multiple directories if they exist
        total_strategies = sum(len(classes) for classes in strategies.values())
        
        # Log discovered strategies for debugging
        print(f"\nDiscovered {total_strategies} legacy strategies in {len(strategies)} directories:")
        for path, classes in strategies.items():
            print(f"  {path}: {len(classes)} strategies")
            for cls_info in classes:
                print(f"    - {cls_info['name']}")
        
        # Validate structure
        for path, strategy_classes in strategies.items():
            assert isinstance(strategy_classes, list)
            for cls_info in strategy_classes:
                assert isinstance(cls_info, dict)
                assert "name" in cls_info
                assert "class" in cls_info
                assert "module" in cls_info
                assert cls_info["name"] is not None
    
    @pytest.mark.integration
    def test_migration_status_reporting(self):
        """Test migration status reporting accuracy"""
        status = get_migration_status()
        
        # Validate structure
        required_keys = [
            "legacy_strategies", "functional_strategies", 
            "migration_progress", "strategy_details"
        ]
        
        for key in required_keys:
            assert key in status, f"Missing key: {key}"
        
        # Validate types and ranges
        assert isinstance(status["legacy_strategies"], int)
        assert isinstance(status["functional_strategies"], int)
        assert isinstance(status["migration_progress"], float)
        assert isinstance(status["strategy_details"], dict)
        
        assert status["legacy_strategies"] >= 0
        assert status["functional_strategies"] > 0  # Should have functional strategies
        assert 0.0 <= status["migration_progress"] <= 100.0
        
        # Validate detailed information
        details = status["strategy_details"]
        assert "legacy" in details
        assert "functional" in details
        
        print(f"\nMigration Status:")
        print(f"  Legacy strategies: {status['legacy_strategies']}")
        print(f"  Functional strategies: {status['functional_strategies']}")
        print(f"  Migration progress: {status['migration_progress']:.1f}%")


class TestLegacyIntegration:
    """Test integration with legacy strategy implementations"""
    
    @pytest.mark.integration
    @pytest.mark.skipif(not LEGACY_IMPORTS_AVAILABLE, reason="Legacy imports not available")
    def test_legacy_strategy_wrapping_comprehensive(self, integration_data):
        """Test comprehensive wrapping of different legacy strategies"""
        legacy_strategies = [
            ("MomentumStrategy", MomentumStrategy()),
            ("MeanReversionStrategy", MeanReversionStrategy()),
        ]
        
        # Add MACD if available
        try:
            legacy_strategies.append(("MACDStrategy", MACDStrategy()))
        except NameError:
            pass
        
        config = StrategyConfig(
            symbol="INTEGRATION_TEST",
            timeframe="1D",
            lookback_period=14,
            parameters={}
        )
        
        for strategy_name, legacy_strategy in legacy_strategies:
            with pytest.subTest(strategy=strategy_name):
                # Wrap the legacy strategy
                wrapped = wrap_legacy_strategy(legacy_strategy)
                
                assert callable(wrapped), f"Wrapped {strategy_name} should be callable"
                
                # Test signal generation
                if len(integration_data) >= 20:
                    signals = wrapped(integration_data[-5:], 0, config)
                    
                    assert isinstance(signals, list), f"{strategy_name} should return list of signals"
                    
                    # Validate signal structure if any signals generated
                    for signal in signals:
                        assert isinstance(signal, FunctionalSignal)
                        assert signal.signal_type in ["long", "short", "hold", "exit"]
                        assert 0.0 <= signal.confidence <= 1.0
    
    @pytest.mark.integration
    @pytest.mark.skipif(not LEGACY_IMPORTS_AVAILABLE, reason="Legacy imports not available")
    def test_legacy_backtest_integration(self, integration_data):
        """Test backtesting with legacy strategies through bridge"""
        if len(integration_data) < 50:
            pytest.skip("Not enough integration data")
        
        legacy_strategy = MomentumStrategy()
        
        # Test unified backtest with legacy strategy instance
        result = unified_backtest(
            strategy=legacy_strategy,
            data=integration_data,
            start_date=datetime(2023, 2, 1),
            end_date=datetime(2023, 4, 1),
            symbol="INTEGRATION_TEST"
        )
        
        # Validate result structure
        assert isinstance(result, dict)
        assert "total_return" in result
        assert "strategy_type" in result
        assert "trades" in result
        
        assert result["strategy_type"] == "legacy"
        assert isinstance(result["total_return"], (int, float))
        assert isinstance(result["trades"], list)
        
        print(f"\nLegacy backtest result:")
        print(f"  Total return: {result['total_return']:.2%}")
        print(f"  Number of trades: {len(result['trades'])}")
        print(f"  Strategy type: {result['strategy_type']}")


class TestUnifiedInterface:
    """Test unified interface functions that work with both legacy and functional strategies"""
    
    @pytest.mark.integration
    def test_unified_backtest_functional_strategies(self, integration_data):
        """Test unified backtest with functional strategies"""
        if len(integration_data) < 50:
            pytest.skip("Not enough integration data")
        
        # Test with different functional strategies
        functional_strategies = ["momentum", "mean_reversion", "macd"]
        
        for strategy_name in functional_strategies:
            if strategy_name in STRATEGY_REGISTRY:
                with pytest.subTest(strategy=strategy_name):
                    result = unified_backtest(
                        strategy=strategy_name,
                        data=integration_data,
                        start_date=datetime(2023, 2, 1),
                        end_date=datetime(2023, 4, 1),
                        symbol="INTEGRATION_TEST"
                    )
                    
                    assert isinstance(result, dict)
                    assert "total_return" in result
                    assert "strategy_type" in result
                    assert result["strategy_type"] == "functional"
                    
                    print(f"\n{strategy_name} unified backtest:")
                    print(f"  Total return: {result['total_return']:.2%}")
                    print(f"  Number of trades: {len(result.get('trades', []))}")
    
    @pytest.mark.integration
    def test_unified_recommendations_comparison(self, integration_data):
        """Test unified recommendations and compare functional vs legacy output"""
        if len(integration_data) < 30:
            pytest.skip("Not enough integration data")
        
        target_date = datetime(2023, 3, 1)
        
        # Test functional strategy
        func_recommendations = unified_recommendations(
            strategy="momentum",
            data=integration_data,
            target_date=target_date,
            symbol="INTEGRATION_TEST"
        )
        
        assert isinstance(func_recommendations, list)
        
        # Test legacy strategy if available
        if LEGACY_IMPORTS_AVAILABLE:
            legacy_strategy = MomentumStrategy()
            legacy_recommendations = unified_recommendations(
                strategy=legacy_strategy,
                data=integration_data,
                target_date=target_date,
                symbol="INTEGRATION_TEST"
            )
            
            assert isinstance(legacy_recommendations, list)
            
            # Both should return similar types of results
            for rec in func_recommendations + legacy_recommendations:
                assert isinstance(rec, FunctionalSignal)
                assert rec.signal_type in ["long", "short", "hold", "exit"]
    
    @pytest.mark.integration
    @pytest.mark.skipif(not LEGACY_IMPORTS_AVAILABLE, reason="Legacy imports not available") 
    def test_unified_ensemble_mixed_strategies(self, integration_data):
        """Test unified ensemble with mix of functional and legacy strategies"""
        if len(integration_data) < 30:
            pytest.skip("Not enough integration data")
        
        # Create ensemble with mix of strategies
        mixed_strategies = [
            "momentum",  # Functional strategy name
            MomentumStrategy(),  # Legacy strategy instance
            "mean_reversion",  # Another functional strategy
        ]
        
        ensemble = create_unified_ensemble(
            strategies=mixed_strategies,
            weights=[0.4, 0.3, 0.3],
            method="weighted_average"
        )
        
        assert callable(ensemble)
        
        # Test ensemble signal generation
        config = StrategyConfig(
            symbol="INTEGRATION_TEST",
            timeframe="1D",
            lookback_period=14,
            parameters={}
        )
        
        signals = ensemble(integration_data[-5:], 0, config)
        
        assert isinstance(signals, list)
        for signal in signals:
            assert isinstance(signal, FunctionalSignal)
            assert 0.0 <= signal.confidence <= 1.0


class TestMigrationUtilities:
    """Test migration utilities and reporting"""
    
    @pytest.mark.integration
    def test_migration_report_generation(self, temp_results_dir):
        """Test comprehensive migration report generation"""
        report = generate_migration_report(output_dir=temp_results_dir)
        
        assert isinstance(report, dict)
        
        # Validate report structure
        required_sections = [
            "summary", "legacy_strategies", "functional_strategies",
            "compatibility_matrix", "recommendations"
        ]
        
        for section in required_sections:
            assert section in report, f"Missing report section: {section}"
        
        # Validate summary
        summary = report["summary"]
        assert "total_legacy" in summary
        assert "total_functional" in summary
        assert "migration_progress" in summary
        
        # Check if report file was created
        report_files = list(Path(temp_results_dir).glob("migration_report_*.md"))
        assert len(report_files) > 0, "Migration report file should be created"
        
        # Validate report file content
        report_file = report_files[0]
        content = report_file.read_text()
        assert "Migration Status Report" in content
        assert "Legacy Strategies" in content
        assert "Functional Strategies" in content
        
        print(f"\nMigration report created: {report_file}")
        print(f"Report sections: {list(report.keys())}")
    
    @pytest.mark.integration
    @pytest.mark.skipif(not LEGACY_IMPORTS_AVAILABLE, reason="Legacy imports not available")
    def test_strategy_results_migration(self, integration_data, temp_results_dir):
        """Test migration of strategy results between formats"""
        if len(integration_data) < 50:
            pytest.skip("Not enough integration data")
        
        # Generate results with legacy strategy
        legacy_strategy = MomentumStrategy()
        legacy_result = unified_backtest(
            strategy=legacy_strategy,
            data=integration_data,
            start_date=datetime(2023, 2, 1),
            end_date=datetime(2023, 3, 1),
            symbol="MIGRATION_TEST"
        )
        
        # Generate results with functional strategy
        functional_result = unified_backtest(
            strategy="momentum",
            data=integration_data,
            start_date=datetime(2023, 2, 1),
            end_date=datetime(2023, 3, 1),
            symbol="MIGRATION_TEST"
        )
        
        # Migrate results
        migrated_results = migrate_strategy_results(
            legacy_results=[legacy_result],
            functional_results=[functional_result],
            output_dir=temp_results_dir
        )
        
        assert isinstance(migrated_results, dict)
        assert "legacy_count" in migrated_results
        assert "functional_count" in migrated_results
        assert "migration_success" in migrated_results
        
        assert migrated_results["legacy_count"] == 1
        assert migrated_results["functional_count"] == 1
        assert migrated_results["migration_success"] is True


class TestPerformanceComparison:
    """Test performance comparison between legacy and functional approaches"""
    
    @pytest.mark.integration
    @pytest.mark.performance
    def test_performance_comparison(self, integration_data):
        """Compare performance between functional and unified interfaces"""
        if len(integration_data) < 100:
            pytest.skip("Not enough data for performance testing")
        
        test_data = integration_data[:100]  # Use subset for speed
        
        # Time functional interface
        start_time = datetime.now()
        functional_result = run_backtest(
            strategy="momentum",
            data=test_data,
            date_range=(datetime(2023, 1, 15), datetime(2023, 3, 15)),
            symbol="PERF_TEST"
        )
        functional_time = (datetime.now() - start_time).total_seconds()
        
        # Time unified interface
        start_time = datetime.now()
        unified_result = unified_backtest(
            strategy="momentum",
            data=test_data,
            start_date=datetime(2023, 1, 15),
            end_date=datetime(2023, 3, 15),
            symbol="PERF_TEST"
        )
        unified_time = (datetime.now() - start_time).total_seconds()
        
        # Both should complete in reasonable time
        assert functional_time < 5.0, f"Functional interface too slow: {functional_time:.2f}s"
        assert unified_time < 5.0, f"Unified interface too slow: {unified_time:.2f}s"
        
        # Results should be comparable
        assert isinstance(functional_result["total_return"], (int, float))
        assert isinstance(unified_result["total_return"], (int, float))
        
        print(f"\nPerformance comparison:")
        print(f"  Functional interface: {functional_time:.3f}s")
        print(f"  Unified interface: {unified_time:.3f}s")
        print(f"  Overhead: {abs(unified_time - functional_time):.3f}s")
    
    @pytest.mark.integration
    @pytest.mark.slow
    def test_scalability_with_multiple_strategies(self, integration_data):
        """Test scalability when running multiple strategies"""
        if len(integration_data) < 50:
            pytest.skip("Not enough data for scalability testing")
        
        strategies_to_test = list(STRATEGY_REGISTRY.keys())[:3]  # Test first 3
        results = {}
        
        start_time = datetime.now()
        
        for strategy_name in strategies_to_test:
            strategy_start = datetime.now()
            
            result = unified_backtest(
                strategy=strategy_name,
                data=integration_data[:75],  # Use subset for speed
                start_date=datetime(2023, 1, 15),
                end_date=datetime(2023, 2, 15),
                symbol="SCALE_TEST"
            )
            
            strategy_time = (datetime.now() - strategy_start).total_seconds()
            results[strategy_name] = {
                "time": strategy_time,
                "return": result["total_return"]
            }
        
        total_time = (datetime.now() - start_time).total_seconds()
        
        # Should complete all strategies in reasonable time
        assert total_time < 15.0, f"Multiple strategies too slow: {total_time:.2f}s"
        
        # Each strategy should complete individually
        for strategy_name, result in results.items():
            assert result["time"] < 8.0, f"{strategy_name} too slow: {result['time']:.2f}s"
        
        print(f"\nScalability test:")
        print(f"  Total time for {len(strategies_to_test)} strategies: {total_time:.2f}s")
        print(f"  Average time per strategy: {total_time/len(strategies_to_test):.2f}s")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
