#!/usr/bin/env python3
"""
Test script to verify action field normalization in place_order method
"""

import sys
import os
sys.path.append('/opt/algosat')

import asyncio
from datetime import datetime
from algosat.core.order_manager import OrderManager
from algosat.core.order_request import Side

async def test_action_normalization():
    """Test the normalize_action_field static method"""
    
    print("=== Testing Action Field Normalization ===")
    
    # Test cases
    test_cases = [
        (Side.BUY, "BUY"),           # Enum value
        (Side.SELL, "SELL"),        # Enum value  
        ("BUY", "BUY"),             # String value
        ("SELL", "SELL"),           # String value
        ("buy", "BUY"),             # Lowercase string
        ("sell", "SELL"),           # Lowercase string
        ("SIDE.BUY", "BUY"),        # SIDE. prefix
        ("SIDE.SELL", "SELL"),      # SIDE. prefix
        (None, "BUY"),              # None default
    ]
    
    print("\nTesting normalize_action_field:")
    for input_value, expected in test_cases:
        result = OrderManager.normalize_action_field(input_value)
        status = "✅ PASS" if result == expected else "❌ FAIL"
        print(f"  Input: {input_value!r:15} -> Output: {result!r:6} (Expected: {expected!r:6}) {status}")
    
    print(f"\n=== Action Normalization Test Complete ===")

if __name__ == "__main__":
    asyncio.run(test_action_normalization())
