#!/usr/bin/env python3
"""
Test Runner for Functional Programming Interface

Provides multiple test execution modes:
1. Quick tests - Basic functionality only
2. Full tests - Comprehensive test suite
3. Performance tests - Performance benchmarks
4. Integration tests - Bridge and legacy integration
5. Specific test categories
"""

import sys
import os
import argparse
import subprocess
from pathlib import Path
from datetime import datetime
import json

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


def run_command(cmd, capture_output=True, timeout=300):
    """Run a command and return the result"""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=capture_output,
            text=True,
            timeout=timeout
        )
        return result
    except subprocess.TimeoutExpired:
        print(f"❌ Command timed out after {timeout}s: {cmd}")
        return None
    except Exception as e:
        print(f"❌ Command failed: {e}")
        return None


def check_dependencies():
    """Check if required testing dependencies are installed"""
    print("🔍 Checking test dependencies...")
    
    required_packages = ["pytest", "pytest-cov", "pytest-benchmark"]
    missing_packages = []
    
    for package in required_packages:
        try:
            __import__(package.replace("-", "_"))
            print(f"  ✅ {package}")
        except ImportError:
            missing_packages.append(package)
            print(f"  ❌ {package}")
    
    if missing_packages:
        print(f"\n📦 Installing missing packages: {', '.join(missing_packages)}")
        install_cmd = f"{sys.executable} -m pip install {' '.join(missing_packages)}"
        result = run_command(install_cmd, capture_output=False)
        
        if result and result.returncode == 0:
            print("✅ Dependencies installed successfully")
        else:
            print("❌ Failed to install dependencies")
            return False
    
    return True


def run_quick_tests():
    """Run quick tests - basic functionality only"""
    print("\n🚀 Running Quick Tests")
    print("=" * 50)
    
    cmd = "python -m pytest tests/test_functional_interface_pytest.py::TestFunctionalInterfaceCore -v"
    result = run_command(cmd, capture_output=False)
    
    return result and result.returncode == 0


def run_unit_tests():
    """Run unit tests"""
    print("\n🧪 Running Unit Tests")
    print("=" * 50)
    
    cmd = "python -m pytest tests/test_functional_interface_pytest.py -m unit -v"
    result = run_command(cmd, capture_output=False)
    
    return result and result.returncode == 0


def run_functional_tests():
    """Run functional tests"""
    print("\n⚙️ Running Functional Tests")
    print("=" * 50)
    
    cmd = "python -m pytest tests/test_functional_interface_pytest.py -m functional -v"
    result = run_command(cmd, capture_output=False)
    
    return result and result.returncode == 0


def run_integration_tests():
    """Run integration tests"""
    print("\n🔗 Running Integration Tests")
    print("=" * 50)
    
    cmd = "python -m pytest tests/test_strategy_bridge_integration.py -m integration -v"
    result = run_command(cmd, capture_output=False)
    
    return result and result.returncode == 0


def run_performance_tests():
    """Run performance tests"""
    print("\n⚡ Running Performance Tests")
    print("=" * 50)
    
    cmd = "python -m pytest tests/ -m performance -v --tb=short"
    result = run_command(cmd, capture_output=False, timeout=600)  # Longer timeout
    
    return result and result.returncode == 0


def run_full_test_suite():
    """Run the complete test suite"""
    print("\n🎯 Running Full Test Suite")
    print("=" * 50)
    
    cmd = "python -m pytest tests/ -v --tb=short --durations=10"
    result = run_command(cmd, capture_output=False, timeout=900)  # 15 minute timeout
    
    return result and result.returncode == 0


def run_coverage_tests():
    """Run tests with coverage reporting"""
    print("\n📊 Running Tests with Coverage")
    print("=" * 50)
    
    cmd = "python -m pytest tests/ --cov=functional_interface --cov=strategy_bridge --cov-report=term-missing --cov-report=html -v"
    result = run_command(cmd, capture_output=False)
    
    if result and result.returncode == 0:
        print("\n📈 Coverage report generated in htmlcov/")
    
    return result and result.returncode == 0


def run_legacy_only_tests():
    """Run only tests that require legacy imports"""
    print("\n🏛️ Running Legacy Integration Tests")
    print("=" * 50)
    
    cmd = "python -m pytest tests/ -m legacy -v"
    result = run_command(cmd, capture_output=False)
    
    return result and result.returncode == 0


def run_unittest_suite():
    """Run the original unittest-based test suite"""
    print("\n🧪 Running Original Unittest Suite")
    print("=" * 50)
    
    cmd = "python test_functional_interface.py"
    result = run_command(cmd, capture_output=False)
    
    return result and result.returncode == 0


def benchmark_strategies():
    """Run strategy performance benchmarks"""
    print("\n📊 Running Strategy Benchmarks")
    print("=" * 50)
    
    try:
        from test_functional_interface import run_performance_benchmark
        results = run_performance_benchmark()
        
        # Save benchmark results
        benchmark_file = f"benchmark_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(benchmark_file, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        
        print(f"\n📄 Benchmark results saved to: {benchmark_file}")
        return True
        
    except Exception as e:
        print(f"❌ Benchmark failed: {e}")
        return False


def validate_functional_interface():
    """Validate that functional interface is working correctly"""
    print("\n✅ Validating Functional Interface")
    print("=" * 50)
    
    try:
        # Test basic imports
        from functional_interface import STRATEGY_REGISTRY, run_backtest, run_recommendations
        from strategy_bridge import unified_backtest, unified_recommendations
        
        print(f"  ✅ Imports successful")
        print(f"  ✅ Strategy registry has {len(STRATEGY_REGISTRY)} strategies")
        
        # Test basic functionality
        strategies = list(STRATEGY_REGISTRY.keys())[:2]  # Test first 2
        
        for strategy in strategies:
            print(f"  🧪 Testing {strategy}...")
            
            # Quick validation that strategy can be called
            strategy_func = STRATEGY_REGISTRY[strategy]
            if callable(strategy_func):
                print(f"    ✅ {strategy} is callable")
            else:
                print(f"    ❌ {strategy} is not callable")
                return False
        
        print("  ✅ All basic validations passed")
        return True
        
    except Exception as e:
        print(f"  ❌ Validation failed: {e}")
        return False


def main():
    """Main test runner"""
    parser = argparse.ArgumentParser(description="Test runner for functional programming interface")
    parser.add_argument("test_type", choices=[
        "quick", "unit", "functional", "integration", "performance", 
        "full", "coverage", "legacy", "unittest", "benchmark", "validate", "all"
    ], help="Type of tests to run")
    
    parser.add_argument("--no-deps", action="store_true", 
                       help="Skip dependency check")
    parser.add_argument("--timeout", type=int, default=300,
                       help="Test timeout in seconds")
    
    args = parser.parse_args()
    
    print("🧪 Functional Programming Interface Test Runner")
    print("=" * 60)
    print(f"Test type: {args.test_type}")
    print(f"Started at: {datetime.now()}")
    print()
    
    # Check dependencies unless skipped
    if not args.no_deps and not check_dependencies():
        print("❌ Dependency check failed")
        return 1
    
    # Validate functional interface first
    if not validate_functional_interface():
        print("❌ Functional interface validation failed")
        return 1
    
    # Run requested tests
    success = True
    start_time = datetime.now()
    
    if args.test_type == "quick":
        success = run_quick_tests()
    elif args.test_type == "unit":
        success = run_unit_tests()
    elif args.test_type == "functional":
        success = run_functional_tests()
    elif args.test_type == "integration":
        success = run_integration_tests()
    elif args.test_type == "performance":
        success = run_performance_tests()
    elif args.test_type == "full":
        success = run_full_test_suite()
    elif args.test_type == "coverage":
        success = run_coverage_tests()
    elif args.test_type == "legacy":
        success = run_legacy_only_tests()
    elif args.test_type == "unittest":
        success = run_unittest_suite()
    elif args.test_type == "benchmark":
        success = benchmark_strategies()
    elif args.test_type == "validate":
        success = validate_functional_interface()
    elif args.test_type == "all":
        # Run comprehensive test suite
        tests = [
            ("Quick Tests", run_quick_tests),
            ("Unit Tests", run_unit_tests), 
            ("Functional Tests", run_functional_tests),
            ("Integration Tests", run_integration_tests),
            ("Coverage Tests", run_coverage_tests),
            ("Performance Tests", run_performance_tests),
            ("Benchmarks", benchmark_strategies)
        ]
        
        results = {}
        for test_name, test_func in tests:
            print(f"\n{'='*20} {test_name} {'='*20}")
            try:
                test_success = test_func()
                results[test_name] = test_success
                if not test_success:
                    success = False
            except Exception as e:
                print(f"❌ {test_name} failed with exception: {e}")
                results[test_name] = False
                success = False
        
        # Summary of all tests
        print(f"\n{'='*60}")
        print("📋 Comprehensive Test Results")
        print(f"{'='*60}")
        
        for test_name, test_result in results.items():
            status = "✅ PASSED" if test_result else "❌ FAILED"
            print(f"  {test_name:.<30} {status}")
        
        passed_count = sum(results.values())
        total_count = len(results)
        print(f"\nOverall: {passed_count}/{total_count} test suites passed")
    
    # Final summary
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    
    print(f"\n{'='*60}")
    print("📊 Test Execution Summary")
    print(f"{'='*60}")
    print(f"Duration: {duration:.2f} seconds")
    print(f"End time: {end_time}")
    
    if success:
        print("🎉 All tests PASSED!")
        return 0
    else:
        print("❌ Some tests FAILED!")
        return 1


if __name__ == "__main__":
    sys.exit(main())
