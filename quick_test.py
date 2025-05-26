#!/usr/bin/env python3
"""
Quick validation check for Algosat components.
"""
import sys
import os
import tempfile
from pathlib import Path

# Add the algosat directory to Python path
sys.path.insert(0, '/opt/algosat/algosat')

def test_component(name, test_func):
    """Test a component and return success status."""
    try:
        test_func()
        print(f"✓ {name}")
        return True
    except Exception as e:
        print(f"✗ {name}: {e}")
        return False

def test_security():
    from core.security import SecurityManager
    with tempfile.TemporaryDirectory() as temp_dir:
        security_manager = SecurityManager(data_dir=temp_dir)

def test_config():
    from core.config_management import ConfigurationManager
    with tempfile.TemporaryDirectory() as temp_dir:
        config_manager = ConfigurationManager(config_dir=temp_dir)
        config_manager.validate_configuration()

def test_resilience():
    from core.resilience import ErrorTracker
    with tempfile.TemporaryDirectory() as temp_dir:
        error_tracker = ErrorTracker(data_dir=temp_dir)

def test_monitoring():
    from core.monitoring import TradingMetrics
    metrics = TradingMetrics()

def test_vps():
    from core.vps_performance import VPSOptimizer
    optimizer = VPSOptimizer()

def test_api():
    from api import enhanced_app
    # Just check import

def main():
    print("Algosat Component Validation")
    print("=" * 40)
    
    results = {}
    results['SecurityManager'] = test_component('SecurityManager', test_security)
    results['ConfigurationManager'] = test_component('ConfigurationManager', test_config)
    results['ErrorTracker'] = test_component('ErrorTracker', test_resilience)
    results['TradingMetrics'] = test_component('TradingMetrics', test_monitoring)
    results['VPSOptimizer'] = test_component('VPSOptimizer', test_vps)
    results['Enhanced API'] = test_component('Enhanced API', test_api)
    
    working = sum(results.values())
    total = len(results)
    
    print(f"\nResult: {working}/{total} components working")
    
    if working == total:
        print("✅ All components functional!")
        return True
    else:
        print("❌ Some components need fixes")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
