#!/usr/bin/env python3
"""
Test Angel One order normalization with multiple status types.
"""
import sys
import os

# Add the project root to the path
sys.path.insert(0, '/opt/algosat')

def test_angel_status_variations():
    """Test Angel One status normalization with different status values."""
    try:
        print("🧪 Testing Angel One Status Variations")
        print("=" * 60)
        
        # Import required modules
        from algosat.core.order_manager import ANGEL_STATUS_MAP
        from algosat.core.order_request import OrderStatus
        
        # Test different status variations
        test_statuses = [
            "cancelled",
            "rejected", 
            "complete",
            "filled",
            "open",
            "pending",
            "trigger pending",
            "modified",
            "unknown_status"  # Test fallback
        ]
        
        print("📊 Angel Status Mapping Test:")
        print("-" * 40)
        
        for status in test_statuses:
            normalized = ANGEL_STATUS_MAP.get(status.lower(), status)
            print(f"  '{status}' → {normalized}")
        
        print(f"\n✅ Angel status mapping test completed!")
        
        # Test Angel order types
        print(f"\n🔄 Testing Angel Order Type Variations")
        print("-" * 40)
        
        from algosat.core.order_manager import ANGEL_ORDER_TYPE_MAP
        
        test_order_types = [
            "MARKET",
            "LIMIT",
            "SL", 
            "SL-M",
            "STOPLOSS_LIMIT",
            "STOPLOSS_MARKET",
            "UNKNOWN_TYPE"  # Test fallback
        ]
        
        for order_type in test_order_types:
            normalized = ANGEL_ORDER_TYPE_MAP.get(order_type, order_type)
            print(f"  '{order_type}' → '{normalized}'")
        
        print(f"\n✅ Angel order type mapping test completed!")
        
    except Exception as e:
        print(f"❌ Error during status variation test: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_angel_status_variations()