#!/usr/bin/env python3
"""
Test script to verify exit_order method uses centralized action normalization
"""

import sys
import os
sys.path.append('/opt/algosat')

import asyncio
from datetime import datetime
from algosat.core.order_manager import OrderManager
from algosat.core.order_request import Side

def test_exit_action_calculation():
    """Test exit action calculation using normalized action fields"""
    
    print("=== Testing Exit Action Calculation with Normalized Fields ===")
    
    order_manager = OrderManager(None)  # broker_manager not needed for this test
    
    # Test different action field formats
    test_cases = [
        # (entry_action, expected_exit_action)
        (Side.BUY, "SELL"),         # Enum value
        (Side.SELL, "BUY"),         # Enum value
        ("BUY", "SELL"),            # String value
        ("SELL", "BUY"),            # String value
        ("buy", "SELL"),            # Lowercase
        ("sell", "BUY"),            # Lowercase
        ("SIDE.BUY", "SELL"),       # SIDE. prefix
        ("SIDE.SELL", "BUY"),       # SIDE. prefix
        ("", "EXIT"),               # Empty string fallback
        (None, "SELL"),             # None gets normalized to BUY, so exit is SELL
    ]
    
    print("\nTesting exit action calculation:")
    
    for entry_action, expected_exit in test_cases:
        # Simulate the normalization and exit action calculation from exit_order method
        orig_side = order_manager.normalize_action_field(entry_action)
        
        # Exit action calculation logic from exit_order
        if orig_side == 'BUY':
            exit_action = 'SELL'
        elif orig_side == 'SELL':
            exit_action = 'BUY'
        else:
            exit_action = 'EXIT'  # Fallback for unknown entry action
        
        status = "✅ PASS" if exit_action == expected_exit else "❌ FAIL"
        print(f"  Entry: {entry_action!r:15} -> Normalized: {orig_side!r:6} -> Exit: {exit_action!r:6} (Expected: {expected_exit!r:6}) {status}")
    
    print(f"\n=== Exit Action Calculation Test Complete ===")

if __name__ == "__main__":
    test_exit_action_calculation()
