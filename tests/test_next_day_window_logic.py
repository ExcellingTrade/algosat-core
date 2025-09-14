#!/usr/bin/env python3
"""
Test script to demonstrate the new next day check window logic
"""

from datetime import datetime, timedelta

def test_next_day_window_logic(stoploss_minutes):
    """Test the next day check window logic with different stoploss_minutes values"""
    
    # Simulate current time as 9:30 AM
    current_datetime = datetime(2025, 9, 10, 9, 30, 0)  # 9:30 AM
    
    # Calculate the windows
    market_open_time = current_datetime.replace(hour=9, minute=15, second=0, microsecond=0)
    first_candle_end_time = market_open_time + timedelta(minutes=stoploss_minutes)
    next_day_check_threshold_time = first_candle_end_time + timedelta(minutes=stoploss_minutes)
    
    print(f"\n=== Stoploss Minutes: {stoploss_minutes} ===")
    print(f"Market Open Time: {market_open_time.strftime('%H:%M')}")
    print(f"First Candle Period: {market_open_time.strftime('%H:%M')} - {first_candle_end_time.strftime('%H:%M')}")
    print(f"Check Window: {first_candle_end_time.strftime('%H:%M')} - {next_day_check_threshold_time.strftime('%H:%M')}")
    print(f"Total Check Duration: {stoploss_minutes} minutes")
    
    # Test different current times
    test_times = [
        datetime(2025, 9, 10, 9, 10, 0),  # 9:10 AM - too early
        datetime(2025, 9, 10, 9, 22, 0),  # 9:22 AM - might be in window
        datetime(2025, 9, 10, 9, 50, 0),  # 9:50 AM - might be in window
        datetime(2025, 9, 10, 10, 20, 0), # 10:20 AM - might be too late
    ]
    
    for test_time in test_times:
        if test_time >= first_candle_end_time and test_time <= next_day_check_threshold_time:
            status = "✅ IN WINDOW"
        elif test_time < first_candle_end_time:
            status = "⏰ TOO EARLY"
        else:
            status = "❌ TOO LATE"
        
        print(f"  {test_time.strftime('%H:%M')} - {status}")

if __name__ == "__main__":
    print("Next Day Check Window Logic Test")
    print("=" * 50)
    
    # Test with different stoploss_minutes values
    test_cases = [5, 15, 30]
    
    for stoploss_minutes in test_cases:
        test_next_day_window_logic(stoploss_minutes)
    
    print(f"\n{'='*50}")
    print("Key Benefits:")
    print("✅ Simple time-based window logic")
    print("✅ Scales with stoploss_minutes configuration") 
    print("✅ No complex database tracking needed")
    print("✅ Clear start and end boundaries")
    print("✅ Handles late script starts gracefully")
