#!/usr/bin/env python3
"""
Test script to verify Angel status mapping works correctly with actual Angel API status values.
Based on the real Angel API response showing status fields like "open", "completed", etc.
"""

import sys
import os
sys.path.append('/opt/algosat')

from algosat.core.order_manager import ANGEL_STATUS_MAP
from algosat.core.order_request import OrderStatus

def test_angel_status_mapping():
    """Test Angel status mapping with actual status values from Angel API response."""
    
    print("🔍 Testing Angel Status Mapping with Real API Values")
    print("=" * 60)
    
    # Test cases based on actual Angel API response
    test_cases = [
        # Status values seen in the real Angel API response
        ("open", OrderStatus.AWAITING_ENTRY),
        ("trigger pending", OrderStatus.AWAITING_ENTRY), 
        ("modify pending", OrderStatus.AWAITING_ENTRY),
        ("completed", OrderStatus.OPEN),
        ("cancelled", OrderStatus.CANCELLED),
        ("rejected", OrderStatus.REJECTED),
        ("failed", OrderStatus.FAILED),
        ("expired", OrderStatus.CANCELLED),
        ("partially filled", OrderStatus.PARTIALLY_FILLED),
        ("filled", OrderStatus.FILLED),
    ]
    
    print("📋 Angel Status Mapping Test Results:")
    print("-" * 40)
    
    all_passed = True
    for angel_status, expected_order_status in test_cases:
        # Test case-insensitive mapping (since we use .lower() in the code)
        mapped_status = ANGEL_STATUS_MAP.get(angel_status.lower())
        
        if mapped_status == expected_order_status:
            status_symbol = "✅"
        else:
            status_symbol = "❌"
            all_passed = False
        
        print(f"{status_symbol} '{angel_status}' → {mapped_status}")
        if mapped_status != expected_order_status:
            print(f"   Expected: {expected_order_status}")
    
    print("-" * 40)
    
    # Test case sensitivity
    print("\n🔤 Testing Case Sensitivity:")
    print("-" * 30)
    
    case_tests = [
        ("OPEN", "open"),
        ("Open", "open"), 
        ("COMPLETED", "completed"),
        ("Completed", "completed"),
        ("TRIGGER PENDING", "trigger pending"),
        ("Trigger Pending", "trigger pending"),
    ]
    
    for test_status, expected_lower in case_tests:
        mapped_status = ANGEL_STATUS_MAP.get(test_status.lower())
        expected_mapped = ANGEL_STATUS_MAP.get(expected_lower)
        
        if mapped_status == expected_mapped:
            status_symbol = "✅"
        else:
            status_symbol = "❌"
            all_passed = False
        
        print(f"{status_symbol} '{test_status}' → {mapped_status}")
    
    print("-" * 30)
    
    # Test unknown status handling
    print("\n❓ Testing Unknown Status Handling:")
    print("-" * 35)
    
    unknown_statuses = ["unknown_status", "invalid", "test_status"]
    for unknown_status in unknown_statuses:
        mapped_status = ANGEL_STATUS_MAP.get(unknown_status.lower(), unknown_status)
        print(f"⚠️  '{unknown_status}' → {mapped_status} (fallback)")
    
    print("\n" + "=" * 60)
    
    if all_passed:
        print("🎉 All Angel status mapping tests PASSED!")
        print("✅ Angel status normalization is working correctly")
    else:
        print("❌ Some Angel status mapping tests FAILED!")
        print("⚠️  Check the mapping configuration")
    
    print("=" * 60)
    
    # Simulate OrderMonitor logic
    print("\n🔄 Simulating OrderMonitor Status Processing:")
    print("-" * 45)
    
    # Sample Angel order response (similar to what user provided)
    sample_angel_order = {
        'status': 'open',
        'orderstatus': 'open',
        'orderid': '091389e428f2AO',
        'tradingsymbol': 'NIFTY16SEP2524950CE'
    }
    
    # Simulate the OrderMonitor logic
    broker_name = "angel"
    broker_status = sample_angel_order.get('status') or sample_angel_order.get('orderstatus')
    print(f"📥 Raw Angel status: '{broker_status}'")
    
    if broker_status and isinstance(broker_status, str) and broker_name == "angel":
        normalized_status = ANGEL_STATUS_MAP.get(broker_status.lower(), broker_status)
        print(f"🔄 Normalized status: {normalized_status}")
        
        if normalized_status != broker_status:
            print("✅ Status normalization applied successfully")
        else:
            print("⚠️  Status remained unchanged (not found in mapping)")
    
    return all_passed

if __name__ == "__main__":
    test_angel_status_mapping()