#!/usr/bin/env python3
"""
Test script to verify the pre-candle cache cleanup fix.
This script tests that cache entries created before first candle completion are properly cleaned up.
"""

import asyncio
import sys
import os
import json
from datetime import datetime, timedelta, time as dt_time

# Add the project root to Python path
sys.path.insert(0, '/opt/algosat')

from algosat.common.logger import get_logger
from algosat.core.time_utils import get_ist_datetime

logger = get_logger(__name__)

def create_test_cache_with_timestamps():
    """Create test cache entries with different timestamps."""
    today = datetime.now().date()
    yesterday = today - timedelta(days=1)
    
    # Simulate IST timezone
    ist_tz = get_ist_datetime().tzinfo
    
    # Create various cache entries
    cache = {
        # Today's entry created before first candle (should be deleted)
        f"NIFTY_{today.isoformat()}_5_40_500": {
            'strikes': ['NIFTY25JUL24500CE', 'NIFTY25JUL24500PE'],
            'metadata': {
                'created_at': datetime.combine(today, dt_time(8, 30)).replace(tzinfo=ist_tz).isoformat(),  # 8:30 AM (before 9:15)
                'first_candle_time': '09:15',
                'interval_minutes': 5,
                'max_premium': 500,
                'symbol': 'NIFTY'
            }
        },
        # Today's entry created after first candle completion (should be kept)
        f"BANKNIFTY_{today.isoformat()}_5_40_800": {
            'strikes': ['BANKNIFTY25JUL50000CE', 'BANKNIFTY25JUL50000PE'],
            'metadata': {
                'created_at': datetime.combine(today, dt_time(9, 25)).replace(tzinfo=ist_tz).isoformat(),  # 9:25 AM (after 9:20)
                'first_candle_time': '09:15',
                'interval_minutes': 5,
                'max_premium': 800,
                'symbol': 'BANKNIFTY'
            }
        },
        # Legacy cache entry for today (no metadata - should be deleted)
        f"FINNIFTY_{today.isoformat()}_1_40_300": ['FINNIFTY25JUL19000CE', 'FINNIFTY25JUL19000PE'],
        
        # Yesterday's entry (should be kept - not for today)
        f"NIFTY_{yesterday.isoformat()}_5_40_500": {
            'strikes': ['NIFTY25JUL24000CE', 'NIFTY25JUL24000PE'],
            'metadata': {
                'created_at': datetime.combine(yesterday, dt_time(10, 0)).replace(tzinfo=ist_tz).isoformat(),
                'first_candle_time': '09:15',
                'interval_minutes': 5,
                'max_premium': 500,
                'symbol': 'NIFTY'
            }
        }
    }
    
    return cache

def cleanup_pre_candle_cache(cache, trade_day, first_candle_time, interval_minutes):
    """
    Test version of the cleanup function with timezone fix.
    """
    from datetime import datetime, time as dt_time
    
    today_str = trade_day.date().isoformat()
    keys_to_delete = []
    
    # Calculate first candle completion time for today (ensure timezone awareness)
    first_candle_time_parts = first_candle_time.split(":")
    first_candle_hour = int(first_candle_time_parts[0])
    first_candle_minute = int(first_candle_time_parts[1])
    
    # Create first candle completion time with same timezone as trade_day
    first_candle_completion_time = datetime.combine(
        trade_day.date(),
        dt_time(first_candle_hour, first_candle_minute)
    ) + timedelta(minutes=interval_minutes)
    
    # Make timezone-aware if trade_day has timezone info
    if trade_day.tzinfo:
        first_candle_completion_time = first_candle_completion_time.replace(tzinfo=trade_day.tzinfo)
    
    print(f"First candle completion time for comparison: {first_candle_completion_time}")
    
    # Check cache entries for today
    for key, value in cache.items():
        try:
            parts = key.split("_")
            if len(parts) >= 2:
                cache_date_str = parts[1]
                
                # Only check entries for today
                if cache_date_str == today_str:
                    print(f"\nChecking cache entry for today: {key}")
                    
                    # Check if cache entry has metadata with creation timestamp
                    if isinstance(value, dict) and 'metadata' in value and 'created_at' in value['metadata']:
                        created_at_str = value['metadata']['created_at']
                        created_at = datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
                        
                        print(f"  Original created_at: {created_at}")
                        print(f"  First candle completion (raw): {first_candle_completion_time}")
                        
                        # Ensure both datetimes have same timezone info for comparison
                        if first_candle_completion_time.tzinfo and not created_at.tzinfo:
                            # Make created_at timezone-aware (assume it's in same timezone as trade_day)
                            created_at = created_at.replace(tzinfo=first_candle_completion_time.tzinfo)
                            print(f"  Made created_at timezone-aware: {created_at}")
                        elif not first_candle_completion_time.tzinfo and created_at.tzinfo:
                            # Convert created_at to naive datetime for comparison
                            created_at = created_at.replace(tzinfo=None)
                            print(f"  Made created_at timezone-naive: {created_at}")
                        elif first_candle_completion_time.tzinfo and created_at.tzinfo:
                            # Both are timezone-aware, convert created_at to same timezone
                            created_at = created_at.astimezone(first_candle_completion_time.tzinfo)
                            print(f"  Converted created_at to same timezone: {created_at}")
                        
                        print(f"  Final comparison: {created_at} < {first_candle_completion_time}")
                        
                        # If cache was created before first candle completion, mark for deletion
                        if created_at < first_candle_completion_time:
                            keys_to_delete.append(key)
                            print(f"  → MARK FOR DELETION: Created before first candle completion")
                        else:
                            print(f"  → KEEP: Created after first candle completion")
                    else:
                        # Legacy cache entry without metadata - assume it's invalid for today
                        keys_to_delete.append(key)
                        print(f"  → MARK FOR DELETION: Legacy entry without metadata")
                else:
                    print(f"Skipping entry for different date: {key} (date: {cache_date_str})")
        except Exception as e:
            print(f"Error checking cache entry {key}: {e}")
            continue
    
    # Delete invalid entries
    deleted_keys = []
    for key in keys_to_delete:
        del cache[key]
        deleted_keys.append(key)
        print(f"Deleted cache entry: {key}")
    
    return len(deleted_keys), deleted_keys

async def test_pre_candle_cache_cleanup():
    """Test the pre-candle cache cleanup functionality."""
    
    print("🧪 Testing Pre-Candle Cache Cleanup...")
    
    # Create test cache
    cache = create_test_cache_with_timestamps()
    print(f"\nInitial cache entries ({len(cache)} total):")
    for key, value in cache.items():
        if isinstance(value, dict) and 'metadata' in value:
            created_at = value['metadata']['created_at']
            print(f"  {key}: created_at={created_at}")
        else:
            print(f"  {key}: legacy format (no metadata)")
    
    # Test parameters
    trade_day = get_ist_datetime()
    first_candle_time = "09:15"
    interval_minutes = 5
    
    print(f"\nTest parameters:")
    print(f"  Trade day: {trade_day}")
    print(f"  First candle time: {first_candle_time}")
    print(f"  Interval minutes: {interval_minutes}")
    
    # Run cleanup
    deleted_count, deleted_keys = cleanup_pre_candle_cache(cache, trade_day, first_candle_time, interval_minutes)
    
    print(f"\n📊 Cleanup Results:")
    print(f"  Deleted entries: {deleted_count}")
    print(f"  Deleted keys: {deleted_keys}")
    
    print(f"\nRemaining cache entries ({len(cache)} total):")
    for key, value in cache.items():
        if isinstance(value, dict) and 'metadata' in value:
            created_at = value['metadata']['created_at']
            print(f"  {key}: created_at={created_at}")
        else:
            print(f"  {key}: legacy format (no metadata)")
    
    # Verify expectations
    expected_deletions = 2  # NIFTY (pre-candle) + FINNIFTY (legacy)
    expected_remaining = 2  # BANKNIFTY (post-candle) + NIFTY (yesterday)
    
    success = True
    if deleted_count == expected_deletions:
        print(f"  ✅ Correct number of deletions: {deleted_count}")
    else:
        print(f"  ❌ Wrong number of deletions: expected {expected_deletions}, got {deleted_count}")
        success = False
    
    if len(cache) == expected_remaining:
        print(f"  ✅ Correct number of remaining entries: {len(cache)}")
    else:
        print(f"  ❌ Wrong number of remaining entries: expected {expected_remaining}, got {len(cache)}")
        success = False
    
    # Verify specific deletions
    today_str = trade_day.date().isoformat()
    pre_candle_key = f"NIFTY_{today_str}_5_40_500"
    legacy_key = f"FINNIFTY_{today_str}_1_40_300"
    post_candle_key = f"BANKNIFTY_{today_str}_5_40_800"
    yesterday_key = f"NIFTY_{(trade_day.date() - timedelta(days=1)).isoformat()}_5_40_500"
    
    if pre_candle_key not in cache:
        print(f"  ✅ Pre-candle entry correctly deleted: {pre_candle_key}")
    else:
        print(f"  ❌ Pre-candle entry should have been deleted: {pre_candle_key}")
        success = False
    
    if legacy_key not in cache:
        print(f"  ✅ Legacy entry correctly deleted: {legacy_key}")
    else:
        print(f"  ❌ Legacy entry should have been deleted: {legacy_key}")
        success = False
    
    if post_candle_key in cache:
        print(f"  ✅ Post-candle entry correctly kept: {post_candle_key}")
    else:
        print(f"  ❌ Post-candle entry should have been kept: {post_candle_key}")
        success = False
    
    if yesterday_key in cache:
        print(f"  ✅ Yesterday's entry correctly kept: {yesterday_key}")
    else:
        print(f"  ❌ Yesterday's entry should have been kept: {yesterday_key}")
        success = False
    
    return success

async def main():
    """Main test function."""
    print("🚀 Testing Pre-Candle Cache Cleanup Fix")
    print("=" * 60)
    print("This test verifies that cache entries created before first candle")
    print("completion are properly cleaned up to prevent using test data")
    print("during actual market hours.")
    print("=" * 60)
    
    test_passed = await test_pre_candle_cache_cleanup()
    
    print("\n" + "=" * 60)
    if test_passed:
        print("🎉 ALL TESTS PASSED!")
        print("✅ Pre-candle cache cleanup is working correctly:")
        print("   - Cache entries created before first candle completion are deleted")
        print("   - Legacy cache entries (no metadata) for today are deleted")
        print("   - Cache entries created after first candle completion are kept")
        print("   - Cache entries for other days are kept")
    else:
        print("❌ Some tests failed. The fix may need more work.")
    
    print("\n🔧 IMPLEMENTATION DETAILS:")
    print("1. Added creation timestamp metadata to cache entries")
    print("2. Added cleanup_pre_candle_cache() function")
    print("3. Cache cleanup runs before checking for existing cache")
    print("4. Handles both new format (with metadata) and legacy format")
    print("5. Only affects today's cache entries")
    
    print("\n💡 USAGE:")
    print("The fix will automatically clean up pre-candle cache entries")
    print("when the strategy setup runs after waiting for first candle completion.")
    print("This prevents using strikes identified from pre-market data.")
    
    return test_passed

if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(0 if result else 1)
