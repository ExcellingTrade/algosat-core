#!/usr/bin/env python3
"""
Check holiday file directory and creation
"""

import sys
import os

# Add the algosat directory to the Python path
sys.path.insert(0, '/opt/algosat')

def check_holiday_file():
    """Check holiday file directory and creation"""
    print('🔍 Checking holiday file directory and creation')
    print('=' * 60)
    
    try:
        # Import after path setup
        from algosat.common import constants
        
        print(f'CONFIG_DIR path: {constants.CONFIG_DIR}')
        print(f'CONFIG_DIR exists: {os.path.exists(constants.CONFIG_DIR)}')
        print(f'CONFIG_DIR is directory: {os.path.isdir(constants.CONFIG_DIR)}')
        
        # Check parent directory
        parent_dir = os.path.dirname(constants.CONFIG_DIR)
        print(f'Parent dir: {parent_dir}')
        print(f'Parent dir exists: {os.path.exists(parent_dir)}')
        
        # Check if holiday file exists
        holiday_file = os.path.join(constants.CONFIG_DIR, 'nse_holidays.json')
        print(f'Holiday file path: {holiday_file}')
        print(f'Holiday file exists: {os.path.exists(holiday_file)}')
        
        # Try to create the directory
        try:
            print(f'\n📁 Creating CONFIG_DIR: {constants.CONFIG_DIR}')
            os.makedirs(constants.CONFIG_DIR, exist_ok=True)
            print('✅ Successfully created CONFIG_DIR')
            
            # Verify creation
            print(f'CONFIG_DIR now exists: {os.path.exists(constants.CONFIG_DIR)}')
            print(f'CONFIG_DIR is directory: {os.path.isdir(constants.CONFIG_DIR)}')
            
        except Exception as e:
            print(f'❌ Error creating CONFIG_DIR: {e}')
            
        # Try to force holiday data fetch to create the file
        print(f'\n🏖️ Attempting to fetch holiday data to create file...')
        try:
            from algosat.common.broker_utils import get_nse_holiday_list
            holidays = get_nse_holiday_list()
            print(f'✅ Holiday data fetched: {len(holidays) if holidays else 0} holidays')
            
            # Check if file was created
            if os.path.exists(holiday_file):
                print(f'✅ Holiday file created: {holiday_file}')
                print(f'File size: {os.path.getsize(holiday_file)} bytes')
            else:
                print(f'❌ Holiday file not created: {holiday_file}')
                
        except Exception as e:
            print(f'❌ Error fetching holiday data: {e}')
            import traceback
            traceback.print_exc()
            
    except Exception as e:
        print(f'❌ Error in check: {e}')
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_holiday_file()
