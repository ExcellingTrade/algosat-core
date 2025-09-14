#!/usr/bin/env python3

import sys
import os
sys.path.append('/opt/algosat')

from datetime import datetime, timedelta
from algosat.common.swing_utils import get_atm_strike_symbol

# Test configuration
config = {
    "expiry_exit": {
        "enabled": True,
        "days_before_expiry": 4,  # 4 days before Sep 9 = Sep 5
        "expiry_exit_time": "15:10"
    },
    "entry": {
        "atm_strike_offset_CE": 0,
        "atm_strike_offset_PE": 0,
        "step_ce": 50,
        "step_pe": 50
    }
}

# Test date: September 5, 2025 (Friday) - This should trigger the days_before_expiry logic
test_date = datetime(2025, 9, 5, 15, 30)  # 15:30 (3:30 PM) on September 5, 2025

print("="*60)
print("Testing get_atm_strike_symbol with days_before_expiry = 4")
print("="*60)
print(f"Test date: {test_date.strftime('%Y-%m-%d %H:%M')} ({test_date.strftime('%A')})")
print(f"Expiry exit time: {config['expiry_exit']['expiry_exit_time']}")
print(f"Days before expiry: {config['expiry_exit']['days_before_expiry']}")
print("Expected: Sep 9 - 4 days = Sep 5 threshold date")
print()

# Test cases
test_cases = [
    ("NIFTY", 24500, "CE"),
    ("NIFTY", 24500, "PE"),
    ("BANKNIFTY", 52000, "CE"),
    ("BANKNIFTY", 52000, "PE"),
]

for symbol, spot_price, option_type in test_cases:
    print(f"Symbol: {symbol}, Spot: {spot_price}, Type: {option_type}")
    result_symbol, expiry_date = get_atm_strike_symbol(symbol, spot_price, option_type, config, test_date)
    print(f"Result: {result_symbol}")
    print(f"Expiry Date: {expiry_date.strftime('%Y-%m-%d')} ({expiry_date.strftime('%A')})")
    print(f"Current Time (for comparison): {test_date.strftime('%Y-%m-%d %H:%M')} ({test_date.strftime('%A')})")
    print(f"Expiry Exit Time: {config['expiry_exit']['expiry_exit_time']}")
    
    # Check if it's the last Tuesday of the month
    import calendar
    last_day = calendar.monthrange(expiry_date.year, expiry_date.month)[1]
    last_date_of_month = datetime(expiry_date.year, expiry_date.month, last_day)
    while last_date_of_month.weekday() != 1:  # Tuesday = 1
        last_date_of_month -= timedelta(days=1)
    
    is_last_tuesday = expiry_date.date() == last_date_of_month.date()
    print(f"Is Last Tuesday of Month: {is_last_tuesday}")
    
    # Determine expected format
    if symbol == "NIFTY" and is_last_tuesday:
        print("Expected Format: Monthly (due to last Tuesday rule)")
    elif symbol == "NIFTY":
        print("Expected Format: Weekly")
    else:
        print("Expected Format: Monthly")
    
    print("-" * 40)

print("\nNote: September 5, 2025 + days_before_expiry=4 should trigger threshold logic.")
print("If current time (15:30) >= threshold time (Sep 5 15:10), expiry should advance to Sep 16.")
print("Since 15:30 > 15:10, NIFTY should advance to next expiry (Sep 16).")
print("\nExpiry format logic: NIFTY uses monthly format only when expiry falls on last Tuesday of month.")
