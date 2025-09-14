#!/usr/bin/env python3
"""
Test script to debug holiday detection on Aug 26/27, 2025
"""

import sys
import os
from datetime import datetime, timedelta

# Add the algosat directory to the Python path
sys.path.insert(0, '/opt/algosat')

def test_holiday_detection():
    """Test holiday detection for Aug 26/27, 2025"""
    print('Testing holiday detection on Aug 26, 2025')
    print('=' * 60)
    
    try:
        from algosat.common.broker_utils import get_nse_holiday_list
        from algosat.strategies.swing_highlow_buy import is_holiday_or_weekend, is_tomorrow_holiday
        from algosat.core.time_utils import get_ist_datetime
        import unittest.mock
        
        # Test Aug 26, 2025 (Tuesday) checking if Aug 27, 2025 (Wednesday) is holiday
        test_date_26 = datetime(2025, 8, 26, 14, 0, 0)  # 2:00 PM on Aug 26
        test_date_27 = datetime(2025, 8, 27, 9, 0, 0)   # 9:00 AM on Aug 27
        
        print(f'Test date (Aug 26): {test_date_26}')
        print(f'Next day (Aug 27): {test_date_27}')
        print(f'Aug 27 weekday: {test_date_27.weekday()} (0=Monday, 6=Sunday)')
        
        # Get holiday list
        print('\n🏖️ Fetching NSE holiday list...')
        holidays = get_nse_holiday_list()
        print(f'Holiday list type: {type(holidays)}')
        print(f'Holiday list length: {len(holidays) if holidays else 0}')
        
        if holidays:
            print('\n📅 All holidays in the list:')
            for i, holiday in enumerate(holidays):
                print(f'  {i+1:2d}. {holiday}')
                
            # Check if Aug 27 appears in any format
            print('\n🔍 Checking Aug 27 in different formats:')
            aug_27_formats = [
                '27-Aug-2025',
                '27-AUG-2025', 
                '2025-08-27',
                '08-27-2025',
                '27/08/2025',
                '27-08-2025'
            ]
            
            for fmt in aug_27_formats:
                is_in_list = fmt in holidays
                print(f'  {fmt}: {"✅ FOUND" if is_in_list else "❌ NOT FOUND"}')
                
            # Check nearby dates around Aug 27
            print('\n🔍 Checking dates around Aug 27:')
            for day in range(25, 30):
                test_date = datetime(2025, 8, day)
                date_str = test_date.strftime('%d-%b-%Y')
                is_in_list = date_str in holidays
                weekday = test_date.strftime('%A')
                print(f'  Aug {day:2d} ({weekday}): {date_str} -> {"✅ HOLIDAY" if is_in_list else "❌ NOT HOLIDAY"}')
        else:
            print('❌ No holidays found or holiday data unavailable')
            
        # Test our holiday detection function
        print(f'\n🧪 Testing is_holiday_or_weekend(Aug 27):')
        is_holiday_27 = is_holiday_or_weekend(test_date_27)
        print(f'Aug 27 is holiday/weekend: {"✅ YES" if is_holiday_27 else "❌ NO"}')
        
        print(f'\n🧪 Testing is_tomorrow_holiday() from Aug 26 context:')
        # Mock the current time to Aug 26
        with unittest.mock.patch('algosat.core.time_utils.get_ist_datetime', return_value=test_date_26):
            with unittest.mock.patch('algosat.strategies.swing_highlow_buy.get_ist_datetime', return_value=test_date_26):
                tomorrow_is_holiday = is_tomorrow_holiday()
                print(f'Tomorrow (Aug 27) is holiday: {"✅ YES" if tomorrow_is_holiday else "❌ NO"}')
                
        # Test what the actual date format looks like for Aug 27
        print(f'\n🔍 Aug 27 date format analysis:')
        aug_27_actual_format = test_date_27.strftime('%d-%b-%Y')
        print(f'Aug 27 formatted as: {aug_27_actual_format}')
        if holidays:
            is_match = aug_27_actual_format in holidays
            print(f'Is {aug_27_actual_format} in holiday list: {"✅ YES" if is_match else "❌ NO"}')
            
    except Exception as e:
        print(f'❌ Error in holiday detection test: {e}')
        import traceback
        traceback.print_exc()
        
def check_log_analysis():
    """Check what should have happened in the logs"""
    print('\n📋 Log Analysis - What should have happened on Aug 26:')
    print('=' * 60)
    
    print('1. Strategy should be running normally on Aug 26 (Tuesday)')
    print('2. During evaluate_exit calls on Aug 26, holiday_exit logic should check:')
    print('   - holiday_exit_config.get("enabled", False) -> Should be True if enabled')
    print('   - is_tomorrow_holiday() -> Should return True if Aug 27 is holiday')
    print('   - If both true, should trigger holiday exit after square_off_time')
    print('3. If holiday exit was NOT triggered, one of these was false:')
    print('   - holiday_exit not enabled in trade config')
    print('   - Aug 27 not detected as holiday')
    print('   - Time not reached square_off_time yet')
    
if __name__ == "__main__":
    try:
        test_holiday_detection()
        check_log_analysis()
        print('\n✅ Holiday detection test completed!')
        
    except Exception as e:
        print(f'❌ Test failed with error: {e}')
        import traceback
        traceback.print_exc()
