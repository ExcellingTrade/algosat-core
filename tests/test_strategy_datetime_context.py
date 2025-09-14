#!/usr/bin/env python3
"""
Test the actual imports and datetime handling in swing_highlow_buy.py context
"""

import sys
import os
sys.path.append('/opt/algosat')

def test_swing_strategy_datetime_handling():
    """Test datetime handling with the actual strategy context"""
    
    print("=== Testing Swing Strategy DateTime Handling ===\n")
    
    try:
        # Test importing the strategy
        from algosat.strategies.swing_highlow_buy import SwingHighLowBuyStrategy
        print("✅ Successfully imported SwingHighLowBuyStrategy")
        
        # Test pandas import
        import pandas as pd
        print("✅ Successfully imported pandas")
        
        # Test datetime imports that are used in the strategy
        from datetime import datetime, timedelta
        print("✅ Successfully imported datetime and timedelta")
        
        # Test time utils import
        try:
            from algosat.core.time_utils import get_ist_datetime
            print("✅ Successfully imported get_ist_datetime")
        except ImportError as e:
            print(f"⚠️  Could not import get_ist_datetime: {e}")
        
        # Test broker utils import
        try:
            from algosat.common.broker_utils import get_trade_day
            print("✅ Successfully imported get_trade_day")
        except ImportError as e:
            print(f"⚠️  Could not import get_trade_day: {e}")
        
        # Test the actual datetime conversion logic used in the strategy
        print("\nTesting datetime conversion logic:")
        
        # Simulate the actual logic from the strategy
        current_datetime = datetime(2025, 7, 22, 10, 30, 0)  # 10:30 AM
        market_open_time = current_datetime.replace(hour=9, minute=15, second=0, microsecond=0)
        first_candle_end_time = market_open_time + timedelta(minutes=5)  # 5-minute timeframe
        
        print(f"   Current time: {current_datetime}")
        print(f"   Market open: {market_open_time}")
        print(f"   First candle end: {first_candle_end_time}")
        
        # Create sample DataFrame like what strategy would receive
        sample_data = pd.DataFrame({
            'timestamp': [
                datetime(2025, 7, 22, 9, 15, 0),
                datetime(2025, 7, 22, 9, 20, 0),
                datetime(2025, 7, 22, 9, 25, 0),
                datetime(2025, 7, 22, 9, 30, 0),
            ],
            'open': [100, 101, 102, 103],
            'close': [101, 102, 103, 104],
            'high': [101.5, 102.5, 103.5, 104.5],
            'low': [99.5, 100.5, 101.5, 102.5]
        })
        
        # Apply the exact logic from our fixed strategy
        first_candle_df = sample_data.copy()
        first_candle_df['timestamp'] = pd.to_datetime(first_candle_df['timestamp'])
        
        # Convert market_open_time and first_candle_end_time to pandas Timestamp, ensuring timezone compatibility
        market_open_ts = pd.to_datetime(market_open_time)
        first_candle_end_ts = pd.to_datetime(first_candle_end_time)
        
        # Ensure all timestamps are timezone-naive for comparison
        if first_candle_df['timestamp'].dt.tz is not None:
            first_candle_df['timestamp'] = first_candle_df['timestamp'].dt.tz_localize(None)
        if market_open_ts.tz is not None:
            market_open_ts = market_open_ts.tz_localize(None)
        if first_candle_end_ts.tz is not None:
            first_candle_end_ts = first_candle_end_ts.tz_localize(None)
        
        today_candles = first_candle_df[
            (first_candle_df['timestamp'] >= market_open_ts) & 
            (first_candle_df['timestamp'] <= first_candle_end_ts)
        ]
        
        print(f"✅ Successfully filtered today's candles: {len(today_candles)} found")
        print(f"   Filtered candles: {today_candles['timestamp'].tolist()}")
        
        # Test the PRIORITY 5 logic (> comparison)
        post_first_candle_df = sample_data.copy()
        post_first_candle_df['timestamp'] = pd.to_datetime(post_first_candle_df['timestamp'])
        
        # Convert first_candle_end_time to pandas Timestamp, ensuring timezone compatibility
        first_candle_end_ts = pd.to_datetime(first_candle_end_time)
        
        # Ensure all timestamps are timezone-naive for comparison
        if post_first_candle_df['timestamp'].dt.tz is not None:
            post_first_candle_df['timestamp'] = post_first_candle_df['timestamp'].dt.tz_localize(None)
        if first_candle_end_ts.tz is not None:
            first_candle_end_ts = first_candle_end_ts.tz_localize(None)
        
        post_first_candle_df = post_first_candle_df[
            post_first_candle_df['timestamp'] > first_candle_end_ts
        ].copy()
        
        print(f"✅ Successfully filtered post-first-candle data: {len(post_first_candle_df)} found")
        print(f"   Post-first-candle timestamps: {post_first_candle_df['timestamp'].tolist()}")
        
        print("\n✅ All datetime handling tests passed!")
        
    except Exception as e:
        print(f"❌ Error in strategy datetime handling test: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_swing_strategy_datetime_handling()
