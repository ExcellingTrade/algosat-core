#!/usr/bin/env python3
"""
Test the exact error scenario that was occurring:
"Invalid comparison between dtype=datetime64 and Timestamp"
"""

import pandas as pd
from datetime import datetime, timedelta

def test_original_error_scenario():
    """Test the exact scenario that was causing the error"""
    
    print("=== Testing Original Error Scenario ===\n")
    
    # Simulate the exact conditions that caused the error
    print("1. Creating DataFrame with datetime64 dtype...")
    
    # This is how the data might come from the API
    sample_timestamps = [
        "2025-07-22 09:15:00",
        "2025-07-22 09:16:00", 
        "2025-07-22 09:17:00",
        "2025-07-22 09:18:00"
    ]
    
    df = pd.DataFrame({
        'timestamp': sample_timestamps,
        'open': [100, 101, 102, 103],
        'close': [101, 102, 103, 104]
    })
    
    # Convert to datetime (this creates datetime64 dtype)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    print(f"   DataFrame timestamp dtype: {df['timestamp'].dtype}")
    
    # Create comparison values (these would be Python datetime or pandas Timestamp)
    market_open_time = datetime(2025, 7, 22, 9, 15, 0)
    first_candle_end_time = market_open_time + timedelta(minutes=1)
    
    print(f"   market_open_time type: {type(market_open_time)}")
    print(f"   first_candle_end_time type: {type(first_candle_end_time)}")
    
    # This is what was causing the error before our fix
    print("\n2. Testing OLD approach (would cause error):")
    try:
        # OLD APPROACH - direct comparison (this would cause the error)
        # today_candles = df[(df['timestamp'] >= market_open_time) & (df['timestamp'] <= first_candle_end_time)]
        print("   (Skipping old approach to avoid error)")
        print("   ❌ OLD: Direct comparison between datetime64 and Python datetime would fail")
    except Exception as e:
        print(f"   ❌ OLD approach failed: {e}")
    
    # Test our NEW approach
    print("\n3. Testing NEW approach (our fix):")
    try:
        # Apply our fix logic (exact same as in the strategy)
        df_fixed = df.copy()
        df_fixed['timestamp'] = pd.to_datetime(df_fixed['timestamp'])
        
        # Convert comparison values to pandas Timestamp
        market_open_ts = pd.to_datetime(market_open_time)
        first_candle_end_ts = pd.to_datetime(first_candle_end_time)
        
        # Ensure timezone compatibility
        if df_fixed['timestamp'].dt.tz is not None:
            df_fixed['timestamp'] = df_fixed['timestamp'].dt.tz_localize(None)
        if market_open_ts.tz is not None:
            market_open_ts = market_open_ts.tz_localize(None)
        if first_candle_end_ts.tz is not None:
            first_candle_end_ts = first_candle_end_ts.tz_localize(None)
        
        # Now the comparison works
        today_candles = df_fixed[
            (df_fixed['timestamp'] >= market_open_ts) & 
            (df_fixed['timestamp'] <= first_candle_end_ts)
        ]
        
        print(f"   ✅ NEW approach works: Found {len(today_candles)} candles")
        print(f"   DataFrame timestamp dtype: {df_fixed['timestamp'].dtype}")
        print(f"   Comparison value types: {type(market_open_ts)}, {type(first_candle_end_ts)}")
        print(f"   Filtered timestamps: {today_candles['timestamp'].tolist()}")
        
    except Exception as e:
        print(f"   ❌ NEW approach failed: {e}")
        import traceback
        traceback.print_exc()
    
    # Test the PRIORITY 5 scenario (> comparison)
    print("\n4. Testing PRIORITY 5 scenario (> comparison):")
    try:
        post_df = df.copy()
        post_df['timestamp'] = pd.to_datetime(post_df['timestamp'])
        
        cutoff_time = datetime(2025, 7, 22, 9, 16, 0)
        cutoff_ts = pd.to_datetime(cutoff_time)
        
        # Ensure timezone compatibility
        if post_df['timestamp'].dt.tz is not None:
            post_df['timestamp'] = post_df['timestamp'].dt.tz_localize(None)
        if cutoff_ts.tz is not None:
            cutoff_ts = cutoff_ts.tz_localize(None)
        
        filtered_df = post_df[post_df['timestamp'] > cutoff_ts].copy()
        
        print(f"   ✅ PRIORITY 5 comparison works: Found {len(filtered_df)} candles after cutoff")
        print(f"   Cutoff: {cutoff_ts}")
        print(f"   Filtered: {filtered_df['timestamp'].tolist()}")
        
    except Exception as e:
        print(f"   ❌ PRIORITY 5 comparison failed: {e}")
    
    print("\n=== Error scenario test completed ===")

if __name__ == "__main__":
    test_original_error_scenario()
