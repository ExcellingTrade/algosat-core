#!/usr/bin/env python3
"""
Test script to verify the fixed holiday exit logic.
"""

import sys
import os
from datetime import datetime, timedelta

# Add the algosat directory to the Python path
sys.path.insert(0, '/opt/algosat')

from algosat.strategies.swing_highlow_buy import is_holiday_or_weekend
from algosat.common.broker_utils import get_nse_holiday_list
from algosat.core.time_utils import get_ist_datetime

def test_holiday_functions():
    """Test the holiday checking functions."""
    print("🧪 Testing Holiday Functions")
    print("=" * 50)
    
    # Test current date
    current_datetime = get_ist_datetime()
    print(f"📅 Current IST DateTime: {current_datetime}")
    print(f"📅 Current Date: {current_datetime.date()}")
    print(f"📅 Current Weekday: {current_datetime.weekday()} (0=Monday, 6=Sunday)")
    
    # Test weekend detection
    print("\n🔍 Weekend Detection:")
    for i in range(7):
        test_date = current_datetime + timedelta(days=i)
        is_weekend = test_date.weekday() >= 5
        print(f"  {test_date.strftime('%Y-%m-%d %A')}: Weekend = {is_weekend}")
    
    # Test holiday list
    print("\n🏖️ NSE Holiday List:")
    try:
        holidays = get_nse_holiday_list()
        print(holidays)
        if holidays:
            print(f"  Found {len(holidays)} holidays")
            # Show first few holidays
            for holiday in holidays[:5]:
                print(f"    - {holiday}")
            if len(holidays) > 5:
                print(f"    ... and {len(holidays) - 5} more")
        else:
            print("  No holidays found or holiday data unavailable")
    except Exception as e:
        print(f"  Error fetching holidays: {e}")
    
    # Test is_holiday_or_weekend function
    print("\n🔍 Holiday/Weekend Check for next 10 days:")
    current_datetime = current_datetime - timedelta(days=1)  # Start from yesterday to include today
    for i in range(10):
        test_date = current_datetime + timedelta(days=i)
        is_holiday = is_holiday_or_weekend(test_date)
        day_type = "Holiday/Weekend" if is_holiday else "Trading Day"
        print(f"  {test_date.strftime('%Y-%m-%d %A')}: {day_type}")
    
    # # Test next trading day holiday check
    # print("\n🔍 Next Trading Day Holiday Check:")
    # try:
    #     next_trading_day_is_holiday = is_next_trading_day_holiday()
    #     print(f"  Next trading day is holiday: {next_trading_day_is_holiday}")
        
    #     # Show which day that is
    #     for i in range(1, 5):
    #         next_date = current_datetime + timedelta(days=i)
    #         if next_date.weekday() < 5:  # Weekday
    #             print(f"  Next trading day: {next_date.strftime('%Y-%m-%d %A')}")
    #             print(f"  Is holiday: {is_holiday_or_weekend(next_date)}")
    #             break
                
    # except Exception as e:
    #     print(f"  Error checking next trading day: {e}")

def test_holiday_exit_logic():
    """Test the holiday exit logic."""
    print("\n🚪 Testing Holiday Exit Logic")
    print("=" * 50)
    
    current_datetime = get_ist_datetime()
    
    # Simulate holiday exit config
    holiday_exit_config = {
        "enabled": True,
        "exit_time": "14:30"
    }
    
    print(f"📅 Current time: {current_datetime.strftime('%H:%M')}")
    print(f"🕒 Exit time configured: {holiday_exit_config['exit_time']}")
    
    # Check if next trading day is holiday
    # next_trading_day_is_holiday = is_next_trading_day_holiday()
    # print(f"🏖️ Next trading day is holiday: {next_trading_day_is_holiday}")
    
    # if next_trading_day_is_holiday:
    #     # Parse exit time
    #     exit_time = holiday_exit_config.get("exit_time", "14:30")
    #     try:
    #         exit_hour, exit_minute = map(int, exit_time.split(":"))
    #         exit_datetime = current_datetime.replace(
    #             hour=exit_hour, minute=exit_minute, second=0, microsecond=0
    #         )
            
    #         print(f"🕒 Exit datetime: {exit_datetime}")
    #         print(f"⏰ Current >= Exit time: {current_datetime >= exit_datetime}")
            
    #         if current_datetime >= exit_datetime:
    #             print("✅ HOLIDAY EXIT would be triggered!")
    #         else:
    #             time_to_exit = exit_datetime - current_datetime
    #             print(f"⏳ Time until holiday exit: {time_to_exit}")
                
    #     except Exception as e:
    #         print(f"❌ Error parsing exit time: {e}")
    # else:
    #     print("ℹ️ No holiday exit needed - next trading day is normal")

if __name__ == "__main__":
    print("🔧 Holiday Exit Logic Test")
    print("=" * 60)
    
    try:
        test_holiday_functions()
        test_holiday_exit_logic()
        
        print("\n✅ Holiday test completed successfully!")
        
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
