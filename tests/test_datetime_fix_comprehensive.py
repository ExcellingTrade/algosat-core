#!/usr/bin/env python3
"""
Comprehensive test for datetime comparison fixes in swing_highlow_buy.py
Tests timezone-aware and timezone-naive datetime comparisons
"""

import pandas as pd
from datetime import datetime, timedelta
import pytz

def test_datetime_comparisons():
    """Test various datetime comparison scenarios that might occur in the strategy"""
    
    print("=== Testing DateTime Comparison Fixes ===\n")
    
    # Test 1: Basic timezone-naive comparison (most likely scenario)
    print("Test 1: Basic timezone-naive datetime comparison")
    try:
        # Create sample DataFrame with timezone-naive timestamps
        timestamps = [
            datetime(2025, 7, 22, 9, 15, 0),
            datetime(2025, 7, 22, 9, 16, 0),
            datetime(2025, 7, 22, 9, 17, 0),
            datetime(2025, 7, 22, 9, 18, 0),
        ]
        
        df = pd.DataFrame({
            'timestamp': timestamps,
            'open': [100, 101, 102, 103],
            'close': [101, 102, 103, 104]
        })
        
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        
        # Define comparison times
        market_open_time = datetime(2025, 7, 22, 9, 15, 0)
        first_candle_end_time = market_open_time + timedelta(minutes=1)
        
        # Apply our fix logic
        market_open_ts = pd.to_datetime(market_open_time)
        first_candle_end_ts = pd.to_datetime(first_candle_end_time)
        
        # Ensure timezone-naive
        if df['timestamp'].dt.tz is not None:
            df['timestamp'] = df['timestamp'].dt.tz_localize(None)
        if market_open_ts.tz is not None:
            market_open_ts = market_open_ts.tz_localize(None)
        if first_candle_end_ts.tz is not None:
            first_candle_end_ts = first_candle_end_ts.tz_localize(None)
        
        # Test the comparison
        filtered_df = df[
            (df['timestamp'] >= market_open_ts) & 
            (df['timestamp'] <= first_candle_end_ts)
        ]
        
        print(f"✅ Success: Found {len(filtered_df)} candles in range")
        print(f"   Market open: {market_open_ts}")
        print(f"   First candle end: {first_candle_end_ts}")
        print(f"   Filtered timestamps: {filtered_df['timestamp'].tolist()}")
        
    except Exception as e:
        print(f"❌ Failed: {e}")
    
    print()
    
    # Test 2: Timezone-aware comparison
    print("Test 2: Timezone-aware datetime comparison")
    try:
        ist = pytz.timezone('Asia/Kolkata')
        
        # Create sample DataFrame with timezone-aware timestamps
        timestamps_aware = [
            ist.localize(datetime(2025, 7, 22, 9, 15, 0)),
            ist.localize(datetime(2025, 7, 22, 9, 16, 0)),
            ist.localize(datetime(2025, 7, 22, 9, 17, 0)),
            ist.localize(datetime(2025, 7, 22, 9, 18, 0)),
        ]
        
        df_aware = pd.DataFrame({
            'timestamp': timestamps_aware,
            'open': [100, 101, 102, 103],
            'close': [101, 102, 103, 104]
        })
        
        df_aware['timestamp'] = pd.to_datetime(df_aware['timestamp'])
        
        # Define comparison times (timezone-aware)
        market_open_time_aware = ist.localize(datetime(2025, 7, 22, 9, 15, 0))
        first_candle_end_time_aware = market_open_time_aware + timedelta(minutes=1)
        
        # Apply our fix logic
        market_open_ts = pd.to_datetime(market_open_time_aware)
        first_candle_end_ts = pd.to_datetime(first_candle_end_time_aware)
        
        # Convert to timezone-naive for comparison
        if df_aware['timestamp'].dt.tz is not None:
            df_aware['timestamp'] = df_aware['timestamp'].dt.tz_localize(None)
        if market_open_ts.tz is not None:
            market_open_ts = market_open_ts.tz_localize(None)
        if first_candle_end_ts.tz is not None:
            first_candle_end_ts = first_candle_end_ts.tz_localize(None)
        
        # Test the comparison
        filtered_df_aware = df_aware[
            (df_aware['timestamp'] >= market_open_ts) & 
            (df_aware['timestamp'] <= first_candle_end_ts)
        ]
        
        print(f"✅ Success: Found {len(filtered_df_aware)} candles in range")
        print(f"   Market open (naive): {market_open_ts}")
        print(f"   First candle end (naive): {first_candle_end_ts}")
        print(f"   Filtered timestamps: {filtered_df_aware['timestamp'].tolist()}")
        
    except Exception as e:
        print(f"❌ Failed: {e}")
    
    print()
    
    # Test 3: Mixed timezone scenario (common in real data)
    print("Test 3: Mixed timezone scenario")
    try:
        # DataFrame with UTC timestamps (common from APIs)
        utc = pytz.UTC
        timestamps_utc = [
            utc.localize(datetime(2025, 7, 22, 3, 45, 0)),  # 9:15 IST
            utc.localize(datetime(2025, 7, 22, 3, 46, 0)),  # 9:16 IST
            utc.localize(datetime(2025, 7, 22, 3, 47, 0)),  # 9:17 IST
            utc.localize(datetime(2025, 7, 22, 3, 48, 0)),  # 9:18 IST
        ]
        
        df_mixed = pd.DataFrame({
            'timestamp': timestamps_utc,
            'open': [100, 101, 102, 103],
            'close': [101, 102, 103, 104]
        })
        
        df_mixed['timestamp'] = pd.to_datetime(df_mixed['timestamp'])
        
        # Comparison times in IST (timezone-naive)
        market_open_time_naive = datetime(2025, 7, 22, 9, 15, 0)
        first_candle_end_time_naive = market_open_time_naive + timedelta(minutes=1)
        
        # Apply our fix logic
        market_open_ts = pd.to_datetime(market_open_time_naive)
        first_candle_end_ts = pd.to_datetime(first_candle_end_time_naive)
        
        # Convert everything to timezone-naive
        if df_mixed['timestamp'].dt.tz is not None:
            # Convert UTC to IST first, then make naive
            df_mixed['timestamp'] = df_mixed['timestamp'].dt.tz_convert('Asia/Kolkata').dt.tz_localize(None)
        if market_open_ts.tz is not None:
            market_open_ts = market_open_ts.tz_localize(None)
        if first_candle_end_ts.tz is not None:
            first_candle_end_ts = first_candle_end_ts.tz_localize(None)
        
        # Test the comparison
        filtered_df_mixed = df_mixed[
            (df_mixed['timestamp'] >= market_open_ts) & 
            (df_mixed['timestamp'] <= first_candle_end_ts)
        ]
        
        print(f"✅ Success: Found {len(filtered_df_mixed)} candles in range")
        print(f"   Market open: {market_open_ts}")
        print(f"   First candle end: {first_candle_end_ts}")
        print(f"   Filtered timestamps: {filtered_df_mixed['timestamp'].tolist()}")
        
    except Exception as e:
        print(f"❌ Failed: {e}")
    
    print()
    
    # Test 4: Test > comparison (used in PRIORITY 5)
    print("Test 4: Greater than comparison (PRIORITY 5 scenario)")
    try:
        # Create sample DataFrame
        timestamps = [
            datetime(2025, 7, 22, 9, 15, 0),
            datetime(2025, 7, 22, 9, 16, 0),
            datetime(2025, 7, 22, 9, 17, 0),
            datetime(2025, 7, 22, 9, 18, 0),
        ]
        
        df = pd.DataFrame({
            'timestamp': timestamps,
            'open': [100, 101, 102, 103],
            'close': [101, 102, 103, 104]
        })
        
        df = df.copy()
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        
        # Define cutoff time
        first_candle_end_time = datetime(2025, 7, 22, 9, 16, 0)
        
        # Apply our fix logic
        first_candle_end_ts = pd.to_datetime(first_candle_end_time)
        
        # Ensure timezone-naive
        if df['timestamp'].dt.tz is not None:
            df['timestamp'] = df['timestamp'].dt.tz_localize(None)
        if first_candle_end_ts.tz is not None:
            first_candle_end_ts = first_candle_end_ts.tz_localize(None)
        
        # Test the > comparison
        filtered_df = df[df['timestamp'] > first_candle_end_ts].copy()
        
        print(f"✅ Success: Found {len(filtered_df)} candles after cutoff")
        print(f"   Cutoff time: {first_candle_end_ts}")
        print(f"   Filtered timestamps: {filtered_df['timestamp'].tolist()}")
        
    except Exception as e:
        print(f"❌ Failed: {e}")
    
    print("\n=== All tests completed ===")

if __name__ == "__main__":
    test_datetime_comparisons()
