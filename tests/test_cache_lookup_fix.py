#!/usr/bin/env python3
"""
Test script to validate the _get_cache_lookup_order_id fix for Fyers order matching.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'algosat'))

from algosat.core.order_manager import OrderManager
from algosat.core.order_monitor import OrderMonitor

def test_cache_lookup_logic():
    """Test the _get_cache_lookup_order_id logic for various scenarios."""
    
    print("Testing OrderManager._get_cache_lookup_order_id:")
    
    # Test cases based on log analysis
    test_cases = [
        # Fyers BO orders without suffix - should get -BO-1 suffix
        {
            "broker_order_id": "25080800069210",
            "broker_name": "fyers", 
            "product_type": "BO",
            "expected": "25080800069210-BO-1",
            "description": "Fyers BO order without suffix should get -BO-1 suffix"
        },
        # Fyers BO orders already with suffix - should not append
        {
            "broker_order_id": "25080800069210-BO-1",
            "broker_name": "fyers",
            "product_type": "BO", 
            "expected": "25080800069210-BO-1",
            "description": "Fyers BO order already has suffix, should not append"
        },
        # Fyers INTRADAY orders - should NOT get suffix
        {
            "broker_order_id": "25080800103792",
            "broker_name": "fyers",
            "product_type": "INTRADAY",
            "expected": "25080800103792",
            "description": "Fyers INTRADAY order should NOT get -BO-1 suffix"
        },
        # Fyers MARGIN orders - should NOT get suffix  
        {
            "broker_order_id": "25080800131213",
            "broker_name": "fyers",
            "product_type": "MARGIN", 
            "expected": "25080800131213",
            "description": "Fyers MARGIN order should NOT get -BO-1 suffix"
        },
        # Non-Fyers brokers - should not modify
        {
            "broker_order_id": "220811000123456",
            "broker_name": "zerodha",
            "product_type": "MIS",
            "expected": "220811000123456",
            "description": "Non-Fyers broker should not be modified"
        },
        # Fyers with non-BO product type - should not modify
        {
            "broker_order_id": "25080800999999", 
            "broker_name": "fyers",
            "product_type": "CNC",
            "expected": "25080800999999",
            "description": "Fyers with non-BO product should not be modified"
        },
        # Missing parameters - should handle gracefully
        {
            "broker_order_id": "25080800123456",
            "broker_name": None,
            "product_type": "BO",
            "expected": "25080800123456",
            "description": "Missing broker_name should return original"
        }
    ]
    
    for i, test_case in enumerate(test_cases, 1):
        result = OrderManager._get_cache_lookup_order_id(
            test_case["broker_order_id"],
            test_case["broker_name"], 
            test_case["product_type"]
        )
        
        status = "✓ PASS" if result == test_case["expected"] else "✗ FAIL"
        print(f"Test {i}: {status}")
        print(f"  Input: order_id={test_case['broker_order_id']}, broker={test_case['broker_name']}, product={test_case['product_type']}")
        print(f"  Expected: {test_case['expected']}")
        print(f"  Got: {result}")
        print(f"  Description: {test_case['description']}")
        print()
        
        if result != test_case["expected"]:
            print(f"❌ TEST FAILED!")
            return False
    
    print("✅ All OrderManager tests PASSED!")
    return True

def test_order_monitor_consistency():
    """Test that OrderMonitor has the same logic as OrderManager."""
    
    print("\nTesting OrderMonitor consistency with OrderManager:")
    
    # Import the actual OrderMonitor class
    try:
        from algosat.core.order_monitor import OrderMonitor
        
        # Create a dummy instance just to access the method
        class DummyOrderMonitor(OrderMonitor):
            def __init__(self):
                # Skip the full initialization, just need the method
                pass
        
        monitor = DummyOrderMonitor()
    except Exception as e:
        print(f"Could not import OrderMonitor: {e}")
        return False
    
    # Test key scenarios 
    test_cases = [
        ("25080800069210", "fyers", "BO"),  # Should get -BO-1 suffix
        ("25080800069210-BO-1", "fyers", "BO"),  # Already has suffix, no change
        ("25080800103792", "fyers", "INTRADAY"),  # Should NOT get suffix
        ("25080800131213", "fyers", "MARGIN"),  # Should NOT get suffix
    ]
    
    for order_id, broker_name, product_type in test_cases:
        manager_result = OrderManager._get_cache_lookup_order_id(order_id, broker_name, product_type)
        monitor_result = monitor._get_cache_lookup_order_id(order_id, broker_name, product_type)
        
        if manager_result == monitor_result:
            print(f"✓ CONSISTENT: {order_id} ({product_type}) -> {manager_result}")
        else:
            print(f"✗ INCONSISTENT: {order_id} ({product_type})")
            print(f"  OrderManager: {manager_result}")  
            print(f"  OrderMonitor:  {monitor_result}")
            return False
    
    print("✅ OrderManager and OrderMonitor are CONSISTENT!")
    return True

if __name__ == "__main__":
    print("Testing Fyers order ID cache lookup fix...\n")
    
    success1 = test_cache_lookup_logic()
    success2 = test_order_monitor_consistency()
    
    if success1 and success2:
        print("\n🎉 ALL TESTS PASSED! The fix should resolve the Fyers order matching issues.")
    else:
        print("\n❌ SOME TESTS FAILED! Please review the implementation.")
        sys.exit(1)
