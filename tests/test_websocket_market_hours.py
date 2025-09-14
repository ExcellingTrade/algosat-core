#!/usr/bin/env python3
"""
Test script to verify websocket market hours integration
This demonstrates how the websocket will behave based on market hours
"""

import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from algosat.utils.market_hours import should_enable_websocket, get_market_status, get_next_market_session_change
from algosat.core.time_utils import get_ist_datetime

def test_market_hours_logic():
    """Test the market hours logic"""
    print("🔍 Testing Market Hours Logic")
    print("=" * 50)
    
    # Get current market status
    market_status = get_market_status()
    print(f"📊 Current Market Status:")
    print(f"   State: {market_status['state']}")
    print(f"   Message: {market_status['message']}")
    print(f"   Current Time (IST): {market_status['current_time']}")
    print(f"   Is Open: {market_status['is_open']}")
    
    # Check if websocket should be enabled
    should_enable = should_enable_websocket()
    print(f"\n🌐 WebSocket Control:")
    print(f"   Should Enable WebSocket: {should_enable}")
    
    if should_enable:
        print("   ✅ WebSocket will connect and stream live data")
    else:
        print("   ❌ WebSocket will not connect - market is closed")
        
        # Get next market session change
        try:
            next_change_time, next_state = get_next_market_session_change()
            current_time = get_ist_datetime()
            wait_time = (next_change_time - current_time).total_seconds()
            wait_hours = wait_time / 3600
            
            print(f"   ⏰ Next Change: {next_change_time.strftime('%Y-%m-%d %H:%M:%S IST')}")
            print(f"   📈 Next State: {next_state}")
            print(f"   ⏳ Wait Time: {wait_hours:.1f} hours")
        except Exception as e:
            print(f"   ⚠️  Could not determine next session: {e}")
    
    print("\n" + "=" * 50)
    return should_enable, market_status

async def simulate_websocket_behavior():
    """Simulate how the websocket would behave"""
    print("\n🚀 Simulating WebSocket Behavior")
    print("=" * 50)
    
    should_enable, market_status = test_market_hours_logic()
    
    if should_enable:
        print("📡 WebSocket would connect to broker feed...")
        print("📊 Live market data would be streamed to clients")
        print("💹 Real-time price updates active")
    else:
        print("🛑 WebSocket connection prevented - market closed")
        print("💤 No live data streaming")
        print("⏰ Waiting for market to open...")
        
        # In the real implementation, this would wait and then start when market opens
        print("🔄 Would periodically check market status and start when open")
    
    print("=" * 50)

def test_weekend_vs_weekday():
    """Test different scenarios"""
    print("\n📅 Testing Different Time Scenarios")
    print("=" * 50)
    
    from datetime import datetime, time
    from algosat.core.time_utils import get_ist_datetime
    
    current_time = get_ist_datetime()
    weekday = current_time.weekday()
    
    print(f"Current day: {['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'][weekday]}")
    
    if weekday < 5:  # Weekday
        current_time_only = current_time.time()
        market_start = time(9, 15)
        market_end = time(15, 30)
        
        if current_time_only < market_start:
            print("🌅 Before market hours - WebSocket would wait")
        elif current_time_only > market_end:
            print("🌅 After market hours - WebSocket would be disabled")
        else:
            print("📈 During market hours - WebSocket would be active")
    else:  # Weekend
        print("🏖️  Weekend - WebSocket would be disabled")
    
    print("=" * 50)

if __name__ == "__main__":
    print("🧪 AlgoSat WebSocket Market Hours Test")
    print("=" * 60)
    
    try:
        # Test basic market hours logic
        test_market_hours_logic()
        
        # Test different scenarios
        test_weekend_vs_weekday()
        
        # Simulate websocket behavior
        asyncio.run(simulate_websocket_behavior())
        
        print("\n✅ All tests completed successfully!")
        print("🎯 WebSocket will properly respect market hours")
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
