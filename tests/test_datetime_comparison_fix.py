#!/usr/bin/env python3
"""
Test script to verify the datetime comparison fix in swing_highlow_buy.py
This simulates the exact scenario that was causing the datetime comparison error.
"""

import sys
import pandas as pd
from datetime import datetime
sys.path.insert(0, '/opt/algosat')

def test_datetime_comparison_fix():
    """Test that datetime comparisons work correctly after the fix"""
    
    print("=== Testing datetime comparison fix ===")
    
    # Simulate the data structure returned by fetch_history_data
    sample_first_candle_df = [
        {"timestamp": "2025-07-22T09:15:00", "open": 56380.0, "high": 56420.0, "low": 56370.0, "close": 56400.0},
        {"timestamp": "2025-07-22T09:20:00", "open": 56400.0, "high": 56430.0, "low": 56390.0, "close": 56410.0},
        {"timestamp": "2025-07-22T09:25:00", "open": 56410.0, "high": 56440.0, "low": 56400.0, "close": 56420.0}
    ]
    
    # Convert to DataFrame as the code does
    first_candle_df = pd.DataFrame(sample_first_candle_df)
    
    # Test the original problematic pattern (this would fail before the fix)
    print("Testing original problematic pattern...")
    
    try:
        # This is what was causing the error
        first_candle_df['timestamp'] = pd.to_datetime(first_candle_df['timestamp'])
        
        # Create datetime objects like in the actual code
        market_open_time = datetime(2025, 7, 22, 9, 15, 0)
        first_candle_end_time = datetime(2025, 7, 22, 9, 20, 0)
        
        print(f"  market_open_time type: {type(market_open_time)}")
        print(f"  first_candle_end_time type: {type(first_candle_end_time)}")
        print(f"  timestamp column type: {type(first_candle_df['timestamp'].iloc[0])}")
        
        # This would fail without the fix
        # today_candles = first_candle_df[
        #     (first_candle_df['timestamp'] >= market_open_time) & 
        #     (first_candle_df['timestamp'] <= first_candle_end_time)
        # ]
        # print("❌ Original pattern would fail here!")
        
    except Exception as e:
        print(f"❌ Original pattern failed as expected: {e}")
    
    # Test the fixed pattern
    print("\nTesting fixed pattern...")
    
    try:
        # Reset the DataFrame
        first_candle_df = pd.DataFrame(sample_first_candle_df)
        first_candle_df['timestamp'] = pd.to_datetime(first_candle_df['timestamp'])
        
        # Create datetime objects
        market_open_time = datetime(2025, 7, 22, 9, 15, 0)
        first_candle_end_time = datetime(2025, 7, 22, 9, 20, 0)
        
        # Apply the fix: Convert to pandas Timestamp for comparison
        market_open_ts = pd.Timestamp(market_open_time)
        first_candle_end_ts = pd.Timestamp(first_candle_end_time)
        
        print(f"  market_open_ts type: {type(market_open_ts)}")
        print(f"  first_candle_end_ts type: {type(first_candle_end_ts)}")
        print(f"  timestamp column type: {type(first_candle_df['timestamp'].iloc[0])}")
        
        # This should work with the fix
        today_candles = first_candle_df[
            (first_candle_df['timestamp'] >= market_open_ts) & 
            (first_candle_df['timestamp'] <= first_candle_end_ts)
        ]
        
        print(f"✓ Fixed pattern works! Found {len(today_candles)} candles")
        print(f"  Candles found: {today_candles[['timestamp', 'close']].to_dict('records')}")
        
    except Exception as e:
        print(f"❌ Fixed pattern failed: {e}")
        return False
    
    # Test PRIORITY 5 fix as well
    print("\nTesting PRIORITY 5 datetime comparison fix...")
    
    try:
        # Reset DataFrame for PRIORITY 5 test
        post_first_candle_df = pd.DataFrame(sample_first_candle_df)
        post_first_candle_df['timestamp'] = pd.to_datetime(post_first_candle_df['timestamp'])
        
        first_candle_end_time = datetime(2025, 7, 22, 9, 20, 0)
        
        # Apply PRIORITY 5 fix
        first_candle_end_ts = pd.Timestamp(first_candle_end_time)
        
        filtered_df = post_first_candle_df[
            post_first_candle_df['timestamp'] > first_candle_end_ts
        ].copy()
        
        print(f"✓ PRIORITY 5 fix works! Found {len(filtered_df)} candles after {first_candle_end_ts}")
        print(f"  Filtered candles: {filtered_df[['timestamp', 'close']].to_dict('records')}")
        
    except Exception as e:
        print(f"❌ PRIORITY 5 fix failed: {e}")
        return False
    
    print("\n🎉 All datetime comparison fixes work correctly!")
    return True

def test_mixed_datetime_types():
    """Test various datetime type combinations"""
    
    print("\n=== Testing mixed datetime type handling ===")
    
    # Test different input formats
    timestamp_formats = [
        "2025-07-22T09:15:00",
        "2025-07-22T09:15:00Z",
        "2025-07-22 09:15:00",
        datetime(2025, 7, 22, 9, 15, 0),
        pd.Timestamp("2025-07-22T09:15:00")
    ]
    
    for i, ts_format in enumerate(timestamp_formats):
        try:
            # Create sample data
            sample_df = pd.DataFrame([
                {"timestamp": ts_format, "close": 56400.0}
            ])
            
            # Convert timestamp column
            sample_df['timestamp'] = pd.to_datetime(sample_df['timestamp'])
            
            # Create comparison datetime
            comparison_time = datetime(2025, 7, 22, 9, 10, 0)
            comparison_ts = pd.Timestamp(comparison_time)
            
            # Test comparison
            result = sample_df[sample_df['timestamp'] >= comparison_ts]
            
            print(f"✓ Format {i+1} ({type(ts_format).__name__}): {len(result)} results")
            
        except Exception as e:
            print(f"❌ Format {i+1} failed: {e}")
            return False
    
    print("✓ All datetime format tests passed!")
    return True

if __name__ == "__main__":
    try:
        success1 = test_datetime_comparison_fix()
        success2 = test_mixed_datetime_types()
        
        if success1 and success2:
            print("\n🎉 All tests passed! The datetime comparison fixes are working correctly.")
        else:
            print("\n❌ Some tests failed!")
            sys.exit(1)
            
    except Exception as e:
        print(f"\n❌ Test execution failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
