#!/usr/bin/env python3
"""
Test script to verify OrderMonitor strategy instance handling.
"""

import ast
import sys

def check_strategy_instance_usage():
    """Check if OrderMonitor properly handles strategy instances vs database objects."""
    
    # Read OrderMonitor file
    with open('/opt/algosat/algosat/core/order_monitor.py', 'r') as f:
        order_monitor_content = f.read()
    
    # Check for key patterns
    checks = [
        ("call_strategy_method usage", "await self.call_strategy_method('evaluate_exit'"),
        ("strategy_instance debug logging", "Received strategy instance of type"),
        ("fallback to database strategy", "Falling back to database strategy"),
        ("live strategy instance first", "Using live strategy instance"),
    ]
    
    results = []
    for check_name, pattern in checks:
        if pattern in order_monitor_content:
            results.append(f"✅ {check_name}: Found")
        else:
            results.append(f"❌ {check_name}: Missing")
    
    # Read strategy_manager file  
    with open('/opt/algosat/algosat/core/strategy_manager.py', 'r') as f:
        strategy_manager_content = f.read()
    
    # Check strategy cache usage
    strategy_checks = [
        ("strategy_cache definition", "strategy_cache: Dict[int, object] = {}"),
        ("get_strategy_for_order function", "async def get_strategy_for_order"),
        ("strategy instance reuse", "Reusing cached strategy instance"),
        ("order_monitor_loop strategy lookup", "await get_strategy_for_order"),
    ]
    
    for check_name, pattern in strategy_checks:
        if pattern in strategy_manager_content:
            results.append(f"✅ {check_name}: Found")
        else:
            results.append(f"❌ {check_name}: Missing")
    
    return results

def main():
    print("🔍 Checking OrderMonitor strategy instance handling...")
    results = check_strategy_instance_usage()
    
    for result in results:
        print(result)
    
    # Count successes
    successes = sum(1 for r in results if r.startswith("✅"))
    total = len(results)
    
    print(f"\n📊 Results: {successes}/{total} checks passed")
    
    if successes == total:
        print("✅ All checks passed! OrderMonitor should now properly use strategy instances.")
        print("🔧 Key improvements:")
        print("   - OrderMonitor tries live strategy instance first")
        print("   - Falls back to database strategy if needed")
        print("   - Strategy cache ensures instance reuse")
        print("   - Debug logging shows strategy type received")
        return True
    else:
        print("❌ Some checks failed. Review the implementation.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
