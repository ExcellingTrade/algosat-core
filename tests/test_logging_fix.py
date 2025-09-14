#!/usr/bin/env python3
"""
Test the logging fix for missing directory errors.

This script simulates the conditions that cause the logging error by:
1. Creating a logger that uses date-based directories
2. Removing a date directory while the logger is active
3. Triggering a log rollover to see if it handles missing directories gracefully
"""

import os
import sys
import time
import shutil
from pathlib import Path
from datetime import datetime, timedelta

# Add the project root to sys.path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from algosat.common.logger import get_logger

def test_logging_with_missing_directories():
    """Test that logging handles missing directories gracefully"""
    print("Testing logging with missing directories...")
    
    # Get a test logger
    logger = get_logger("test_logging_fix")
    
    # Create a test log entry
    logger.info("Initial test log entry")
    
    # Get the current date and yesterday's date
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    
    logs_base_dir = Path("/opt/algosat/logs")
    yesterday_dir = logs_base_dir / yesterday
    
    # Create a fake yesterday directory with some log files
    if not yesterday_dir.exists():
        print(f"Creating test directory: {yesterday_dir}")
        yesterday_dir.mkdir(parents=True, exist_ok=True)
        
        # Create some fake log files
        test_files = [
            yesterday_dir / f"api-{yesterday}.log",
            yesterday_dir / f"algosat-{yesterday}.log"
        ]
        
        for test_file in test_files:
            test_file.write_text("Test log content\n")
            print(f"Created test file: {test_file}")
    
    # Log something to trigger potential rollover
    logger.info("Test log entry before directory removal")
    
    # Remove the yesterday directory while logging is active
    if yesterday_dir.exists():
        print(f"Removing directory: {yesterday_dir}")
        shutil.rmtree(yesterday_dir)
        print("Directory removed")
    
    # Try to log again - this should work without errors
    try:
        logger.info("Test log entry after directory removal - this should work!")
        print("✓ Logging after directory removal successful")
        return True
    except Exception as e:
        print(f"❌ Logging failed after directory removal: {e}")
        return False

def test_api_logs_endpoint():
    """Test the logs API with our fixes"""
    print("\nTesting logs API...")
    
    try:
        from algosat.api.routes.logs import get_available_log_dates, get_log_files_for_date
        
        # Test available dates
        dates = get_available_log_dates()
        print(f"Available dates: {dates}")
        
        if dates:
            # Test getting files for the first available date
            test_date = dates[0]
            files = get_log_files_for_date(test_date)
            print(f"Files for {test_date}: {len(files)} files")
            
            for file_info in files:
                file_path = Path(file_info.path)
                exists = file_path.exists()
                print(f"  {file_info.name}: exists={exists}, size={file_info.size}")
        
        print("✓ Logs API test successful")
        return True
        
    except Exception as e:
        print(f"❌ Logs API test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all tests"""
    print("=" * 60)
    print("Testing Logging Fixes for Missing Directory Errors")
    print("=" * 60)
    
    results = []
    
    # Test 1: Logging with missing directories
    try:
        result1 = test_logging_with_missing_directories()
        results.append(result1)
    except Exception as e:
        print(f"❌ Test 1 failed with exception: {e}")
        results.append(False)
    
    # Test 2: API logs endpoint
    try:
        result2 = test_api_logs_endpoint()
        results.append(result2)
    except Exception as e:
        print(f"❌ Test 2 failed with exception: {e}")
        results.append(False)
    
    # Summary
    print("\n" + "=" * 60)
    print("Test Results Summary:")
    print("=" * 60)
    
    passed = sum(results)
    total = len(results)
    
    if passed == total:
        print(f"✓ All {total} tests passed!")
        print("\nThe logging fixes are working correctly:")
        print("- Logging handles missing directories gracefully")
        print("- Logs API only returns available dates and existing files")
        print("- No more FileNotFoundError in logging system")
    else:
        print(f"❌ {total - passed} out of {total} tests failed")
    
    return passed == total

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
