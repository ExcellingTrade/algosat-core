#!/usr/bin/env python3
"""
Test script to verify the broker-specific behavior of calculate_end_date function.
"""

from datetime import datetime
from algosat.common.strategy_utils import calculate_end_date

def test_calculate_end_date_behavior():
    """Test the different behaviors for different brokers."""
    
    # Test case: Current time is 10:43, interval is 5 minutes
    current_time = datetime(2024, 1, 15, 10, 43, 0)  # 10:43:00
    interval_minutes = 5
    
    print(f"Current time: {current_time.strftime('%H:%M:%S')}")
    print(f"Interval: {interval_minutes} minutes")
    print()
    
    # Test Fyers behavior (default)
    fyers_result = calculate_end_date(current_time, interval_minutes, "fyers")
    print(f"Fyers result: {fyers_result.strftime('%H:%M:%S')}")
    print(f"Expected: 10:35:00 (floor to 10:40, then subtract 5 minutes)")
    
    # Test Zerodha behavior
    zerodha_result = calculate_end_date(current_time, interval_minutes, "zerodha")
    print(f"Zerodha result: {zerodha_result.strftime('%H:%M:%S')}")
    print(f"Expected: 10:40:00 (floor to 10:40, return as-is)")
    
    # Test default behavior (no broker_name)
    default_result = calculate_end_date(current_time, interval_minutes)
    print(f"Default result: {default_result.strftime('%H:%M:%S')}")
    print(f"Expected: 10:35:00 (same as Fyers for backward compatibility)")
    
    print()
    print("✅ Testing with different intervals...")
    
    # Test with 1-minute interval
    print(f"\n--- 1-minute interval test (current time: 10:43) ---")
    fyers_1m = calculate_end_date(current_time, 1, "fyers")
    zerodha_1m = calculate_end_date(current_time, 1, "zerodha")
    print(f"Fyers 1m: {fyers_1m.strftime('%H:%M:%S')} (expected: 10:42)")
    print(f"Zerodha 1m: {zerodha_1m.strftime('%H:%M:%S')} (expected: 10:43)")
    
    # Test with 15-minute interval
    print(f"\n--- 15-minute interval test (current time: 10:43) ---")
    fyers_15m = calculate_end_date(current_time, 15, "fyers")
    zerodha_15m = calculate_end_date(current_time, 15, "zerodha")
    print(f"Fyers 15m: {fyers_15m.strftime('%H:%M:%S')} (expected: 10:15)")
    print(f"Zerodha 15m: {zerodha_15m.strftime('%H:%M:%S')} (expected: 10:30)")

if __name__ == "__main__":
    test_calculate_end_date_behavior()
