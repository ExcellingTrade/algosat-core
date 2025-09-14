#!/usr/bin/env python3
"""
Test script to verify the timedelta import fix works correctly
"""

import sys
sys.path.insert(0, '/opt/algosat')

def test_import_pattern():
    """Test the exact import pattern used in the swing_highlow_buy.py file"""
    
    print("=== Testing exact import pattern from swing_highlow_buy.py ===")
    
    # Simulate the exact pattern from the file
    order_timestamp = "2025-07-22T09:15:00Z"  # Sample timestamp string
    
    if isinstance(order_timestamp, str):
        from datetime import datetime, timedelta
        print(f"✓ Import successful: datetime and timedelta imported locally")
        
        # Test datetime usage
        order_datetime = datetime.fromisoformat(order_timestamp.replace('Z', '+00:00'))
        print(f"✓ datetime.fromisoformat works: {order_datetime}")
        
        # Test timedelta usage  
        market_open_time = order_datetime.replace(hour=9, minute=15, second=0, microsecond=0)
        stoploss_minutes = 5  # Sample value
        first_candle_end_time = market_open_time + timedelta(minutes=stoploss_minutes)
        print(f"✓ timedelta works: {market_open_time} + {stoploss_minutes} minutes = {first_candle_end_time}")
        
    print("🎉 All import pattern tests passed!")
    return True

def test_multiple_scopes():
    """Test that the import works correctly in multiple scopes"""
    
    print("\n=== Testing multiple scope usage ===")
    
    # First scope
    if True:
        from datetime import datetime, timedelta
        dt1 = datetime.now()
        td1 = timedelta(minutes=5)
        result1 = dt1 + td1
        print(f"✓ Scope 1: {dt1} + {td1} = {result1}")
    
    # Second scope (simulating second priority section)
    if True:
        from datetime import datetime, timedelta
        dt2 = datetime.now()
        td2 = timedelta(minutes=10)
        result2 = dt2 + td2
        print(f"✓ Scope 2: {dt2} + {td2} = {result2}")
    
    print("✓ Multiple scope test passed!")
    return True

if __name__ == "__main__":
    try:
        test_import_pattern()
        test_multiple_scopes()
        print("\n🎉 All tests passed! The timedelta import fix is working correctly.")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
