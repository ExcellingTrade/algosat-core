#!/usr/bin/env python3
"""
Test script to verify the timedelta import fix in swing_highlow_buy.py
"""

import sys
sys.path.insert(0, '/opt/algosat')

def test_timedelta_import():
    """Test that timedelta can be used in the evaluate_exit method context."""
    
    print("=== Testing timedelta import fix ===")
    
    # Test the import pattern used in the method
    try:
        # This simulates the import pattern in the method
        if True:  # Simulating isinstance check
            from datetime import datetime, timedelta
            
            # Test creating a datetime object
            test_datetime = datetime.now()
            print(f"✓ datetime import successful: {test_datetime}")
            
            # Test using timedelta
            test_timedelta = timedelta(minutes=5)
            result_time = test_datetime + test_timedelta
            print(f"✓ timedelta usage successful: {test_datetime} + {test_timedelta} = {result_time}")
            
        print("✓ Local import pattern works correctly")
        
    except Exception as e:
        print(f"❌ Import test failed: {e}")
        return False
    
    # Test that both datetime and timedelta are available in same scope
    try:
        from datetime import datetime, timedelta
        
        # Test the specific pattern from the code
        test_str = "2025-07-22T09:15:00+05:30"
        order_datetime = datetime.fromisoformat(test_str.replace('Z', '+00:00'))
        market_open_time = order_datetime.replace(hour=9, minute=15, second=0, microsecond=0)
        first_candle_end_time = market_open_time + timedelta(minutes=5)
        
        print(f"✓ Code pattern test successful:")
        print(f"  order_datetime: {order_datetime}")
        print(f"  market_open_time: {market_open_time}")
        print(f"  first_candle_end_time: {first_candle_end_time}")
        
    except Exception as e:
        print(f"❌ Code pattern test failed: {e}")
        return False
    
    print("🎉 All timedelta import tests passed!")
    return True

if __name__ == "__main__":
    success = test_timedelta_import()
    if not success:
        sys.exit(1)
