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
        "days_before_expiry": 0,
        "expiry_exit_time": "15:15"
    },
    "entry": {
        "atm_strike_offset_CE": 0,
        "atm_strike_offset_PE": 0,
        "step_ce": 50,
        "step_pe": 50
    }
}

print("="*60)
print("Testing both last Thursday and regular weekly logic")
print("="*60)

# Test case 1: July 22, 2025 (Tuesday) - should give July 24th weekly expiry
test_date1 = datetime(2025, 7, 22, 10, 0)
print(f"Test 1 - Date: {test_date1.strftime('%Y-%m-%d %H:%M')} ({test_date1.strftime('%A')})")

symbol, spot_price, option_type = "NIFTY", 24500, "CE"
result_symbol1, expiry_date1 = get_atm_strike_symbol(symbol, spot_price, option_type, config, test_date1)
print(f"Result: {result_symbol1}")
print(f"Expiry Date: {expiry_date1.strftime('%Y-%m-%d')} ({expiry_date1.strftime('%A')})")

# Check if it's last Thursday
import calendar
last_day = calendar.monthrange(expiry_date1.year, expiry_date1.month)[1]
last_date_of_month = datetime(expiry_date1.year, expiry_date1.month, last_day)
while last_date_of_month.weekday() != 3:
    last_date_of_month -= timedelta(days=1)

is_last_thursday1 = expiry_date1.date() == last_date_of_month.date()
print(f"Is Last Thursday: {is_last_thursday1}")
print(f"Expected: Weekly format (NSE:NIFTY25724{spot_price}CE)")
print("-" * 40)

# Test case 2: July 29, 2025 (Tuesday) - should give July 31st monthly expiry
test_date2 = datetime(2025, 7, 29, 10, 0)
print(f"Test 2 - Date: {test_date2.strftime('%Y-%m-%d %H:%M')} ({test_date2.strftime('%A')})")

result_symbol2, expiry_date2 = get_atm_strike_symbol(symbol, spot_price, option_type, config, test_date2)
print(f"Result: {result_symbol2}")
print(f"Expiry Date: {expiry_date2.strftime('%Y-%m-%d')} ({expiry_date2.strftime('%A')})")

# Check if it's last Thursday
last_day = calendar.monthrange(expiry_date2.year, expiry_date2.month)[1]
last_date_of_month = datetime(expiry_date2.year, expiry_date2.month, last_day)
while last_date_of_month.weekday() != 3:
    last_date_of_month -= timedelta(days=1)

is_last_thursday2 = expiry_date2.date() == last_date_of_month.date()
print(f"Is Last Thursday: {is_last_thursday2}")
print(f"Expected: Monthly format (NSE:NIFTY25JUL{spot_price}CE)")
print("-" * 40)

print("\nSummary:")
print("- Regular weekly expiries use format: NSE:NIFTY{YY}{M}{DD}{STRIKE}{TYPE}")
print("- Last Thursday expiries use format: NSE:NIFTY{YY}{MMM}{STRIKE}{TYPE}")
print("- This ensures proper symbol mapping for both weekly and monthly contracts")
