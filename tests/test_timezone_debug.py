#!/usr/bin/env python3
"""
Debug the exact timezone issue in holiday detection
"""

import sys
import os
from datetime import datetime, timedelta

# Add the algosat directory to the Python path
sys.path.insert(0, '/opt/algosat')

def debug_timezone_issue():
    """Debug the timezone issue step by step"""
    print('🔍 Debugging timezone issue in holiday detection')
    print('=' * 60)
    
    try:
        from algosat.core.time_utils import get_ist_datetime
        from algosat.common.broker_utils import get_nse_holiday_list
        import unittest.mock
        
        # Mock Aug 26, 2025 as current time
        test_date_26 = datetime(2025, 8, 26, 14, 0, 0)  # 2:00 PM on Aug 26
        
        print(f'🕒 Mocked current time: {test_date_26}')
        print(f'   Type: {type(test_date_26)}')
        print(f'   Timezone: {test_date_26.tzinfo}')
        
        with unittest.mock.patch('algosat.core.time_utils.get_ist_datetime', return_value=test_date_26):
            # Step 1: Get current datetime
            current_datetime = get_ist_datetime()
            print(f'\n1️⃣ current_datetime = get_ist_datetime()')
            print(f'   Value: {current_datetime}')
            print(f'   Type: {type(current_datetime)}')
            print(f'   Timezone: {current_datetime.tzinfo}')
            
            # Step 2: Add timedelta
            tomorrow = current_datetime + timedelta(days=1)
            print(f'\n2️⃣ tomorrow = current_datetime + timedelta(days=1)')
            print(f'   Value: {tomorrow}')
            print(f'   Type: {type(tomorrow)}')
            print(f'   Timezone: {tomorrow.tzinfo}')
            
            # Step 3: Remove timezone
            if tomorrow.tzinfo is not None:
                tomorrow_naive = tomorrow.replace(tzinfo=None)
                print(f'\n3️⃣ tomorrow_naive = tomorrow.replace(tzinfo=None)')
                print(f'   Value: {tomorrow_naive}')
                print(f'   Type: {type(tomorrow_naive)}')
                print(f'   Timezone: {tomorrow_naive.tzinfo}')
                tomorrow = tomorrow_naive
            
            # Step 4: Check weekend
            print(f'\n4️⃣ Weekend check: tomorrow.weekday() = {tomorrow.weekday()}')
            if tomorrow.weekday() >= 5:
                print('   → IS WEEKEND')
                return
            else:
                print('   → NOT WEEKEND')
            
            # Step 5: Get holiday list
            print(f'\n5️⃣ Getting holiday list...')
            holidays = get_nse_holiday_list()
            print(f'   Got {len(holidays) if holidays else 0} holidays')
            
            # Step 6: Format date
            print(f'\n6️⃣ Formatting tomorrow date...')
            try:
                check_date_str = tomorrow.strftime("%d-%b-%Y")
                print(f'   Formatted: {check_date_str}')
                
                # Step 7: Check if in holiday list
                is_holiday = check_date_str in holidays
                print(f'\n7️⃣ Holiday check: {check_date_str} in holidays = {is_holiday}')
                
                if is_holiday:
                    print('   ✅ SUCCESS: Tomorrow is detected as holiday!')
                else:
                    print('   ❌ FAILURE: Tomorrow not detected as holiday')
                    
            except Exception as e:
                print(f'   ❌ ERROR in strftime: {e}')
                import traceback
                traceback.print_exc()
                
    except Exception as e:
        print(f'❌ Error in debug: {e}')
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    debug_timezone_issue()
