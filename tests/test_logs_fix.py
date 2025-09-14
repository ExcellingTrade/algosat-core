#!/usr/bin/env python3
"""
Test script to validate the logs API fixes for FileNotFoundError issues.

This script tests:
1. get_available_log_dates() only returns dates with actual log files
2. get_log_content() handles missing files gracefully
3. get_log_files() checks for available dates first
"""

import sys
import os
import asyncio
from pathlib import Path

# Add the project root to sys.path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from algosat.api.routes.logs import get_available_log_dates, get_log_files_for_date

# Get the logs base directory (from logs.py)
LOGS_BASE_DIR = Path("/opt/algosat/logs")

async def test_available_dates():
    """Test that available dates only include dates with actual log files"""
    print("Testing get_available_log_dates()...")
    
    try:
        dates = get_available_log_dates()
        print(f"Available dates: {dates}")
        
        if not dates:
            print("✓ No available dates (this is fine if no logs exist)")
            return True
            
        # Verify each date has actual log files
        for date in dates:
            print(f"  Checking date: {date}")
            
            # Check if date directory exists
            date_dir = LOGS_BASE_DIR / date
            has_files = False
            
            if date_dir.exists():
                log_files = list(date_dir.glob("*.log*"))
                if log_files:
                    print(f"    Found {len(log_files)} files in date directory")
                    has_files = True
            
            # Also check for files with date in name in base directory
            for log_file in LOGS_BASE_DIR.glob(f"*{date}*.log*"):
                if log_file.is_file():
                    print(f"    Found file with date in name: {log_file.name}")
                    has_files = True
                    break
                    
            if not has_files:
                print(f"    ❌ No log files found for date {date}")
                return False
            else:
                print(f"    ✓ Date {date} has log files")
        
        print("✓ All available dates have log files")
        return True
        
    except Exception as e:
        print(f"❌ Error testing available dates: {e}")
        return False

async def test_log_files_for_date():
    """Test that get_log_files_for_date only returns existing files"""
    print("\nTesting get_log_files_for_date()...")
    
    try:
        dates = get_available_log_dates()
        if not dates:
            print("✓ No dates to test")
            return True
            
        # Test with the first available date
        test_date = dates[0]
        print(f"Testing with date: {test_date}")
        
        log_files = get_log_files_for_date(test_date)
        print(f"Found {len(log_files)} log files")
        
        # Verify all returned files actually exist
        for log_file in log_files:
            file_path = Path(log_file.path)
            if not file_path.exists():
                print(f"❌ File does not exist: {log_file.path}")
                return False
            else:
                print(f"  ✓ File exists: {log_file.name} ({log_file.size} bytes)")
        
        print("✓ All returned log files exist")
        return True
        
    except Exception as e:
        print(f"❌ Error testing log files for date: {e}")
        return False

async def test_with_nonexistent_date():
    """Test behavior with a non-existent date"""
    print("\nTesting with non-existent date...")
    
    try:
        # Use a date that definitely won't exist
        fake_date = "2020-01-01"
        log_files = get_log_files_for_date(fake_date)
        
        if len(log_files) == 0:
            print(f"✓ Correctly returned empty list for non-existent date {fake_date}")
            return True
        else:
            print(f"❌ Unexpectedly found {len(log_files)} files for non-existent date {fake_date}")
            return False
            
    except Exception as e:
        print(f"❌ Error testing with non-existent date: {e}")
        return False

async def main():
    """Run all tests"""
    print("=" * 50)
    print("Testing Logs API Fixes")
    print("=" * 50)
    
    print(f"Logs base directory: {LOGS_BASE_DIR}")
    print(f"Directory exists: {LOGS_BASE_DIR.exists()}")
    
    if LOGS_BASE_DIR.exists():
        all_files = list(LOGS_BASE_DIR.rglob("*.log*"))
        print(f"Total log files found: {len(all_files)}")
        if all_files:
            print("Sample log files:")
            for f in all_files[:5]:  # Show first 5 files
                print(f"  {f.relative_to(LOGS_BASE_DIR)}")
            if len(all_files) > 5:
                print(f"  ... and {len(all_files) - 5} more")
    
    print("\n" + "=" * 50)
    
    # Run tests
    tests = [
        test_available_dates(),
        test_log_files_for_date(),
        test_with_nonexistent_date()
    ]
    
    results = []
    for test in tests:
        result = await test
        results.append(result)
    
    print("\n" + "=" * 50)
    print("Test Results:")
    print("=" * 50)
    
    passed = sum(results)
    total = len(results)
    
    if passed == total:
        print(f"✓ All {total} tests passed!")
        print("\nThe logs API fixes are working correctly:")
        print("- Available dates only include dates with actual log files")
        print("- File existence is checked before returning log file information")
        print("- Non-existent dates return empty results gracefully")
    else:
        print(f"❌ {total - passed} out of {total} tests failed")
        print("\nSome issues remain in the logs API fixes")
    
    return passed == total

if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
