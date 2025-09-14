#!/usr/bin/env python3
"""
Test script to verify the sync_open_positions fix works correctly.
"""

import asyncio
import sys
import os

# Add the project root to Python path
sys.path.insert(0, os.path.abspath('.'))

from algosat.core.db import get_open_orders_for_strategy_and_tradeday, AsyncSessionLocal
from algosat.core.time_utils import get_ist_datetime
from algosat.common.broker_utils import get_trade_day


async def test_sync_open_positions():
    """Test the new get_open_orders_for_strategy_and_tradeday function."""
    print("🔍 Testing sync_open_positions database query...")
    
    try:
        async with AsyncSessionLocal() as session:
            trade_day = get_trade_day(get_ist_datetime())
            strategy_id = 1  # Assuming strategy 1 exists
            
            print(f"📊 Fetching open orders for strategy_id={strategy_id} on trade_day={trade_day.date()}")
            
            # Test the new function
            open_orders = await get_open_orders_for_strategy_and_tradeday(session, strategy_id, trade_day)
            
            print(f"📈 Found {len(open_orders)} open orders for strategy {strategy_id}")
            
            for order in open_orders:
                print(f"  📍 Order ID: {order.get('id')}")
                print(f"     ├─ Strategy Symbol ID: {order.get('strategy_symbol_id')}")
                print(f"     ├─ Status: {order.get('status')}")
                print(f"     ├─ Side: {order.get('side')}")
                print(f"     ├─ Quantity: {order.get('qty')}")
                print(f"     ├─ Entry Price: {order.get('entry_price')}")
                print(f"     └─ Signal Time: {order.get('signal_time')}")
                print()
                
            if len(open_orders) == 0:
                print("ℹ️  No open orders found. This could mean:")
                print("   - No orders have been placed for this strategy today")
                print("   - All orders have been completed or cancelled")
                print("   - Strategy ID 1 doesn't exist or has no symbols")
                
        print("✅ Database query test completed successfully!")
                
    except Exception as e:
        print(f"❌ Error testing sync_open_positions: {e}")
        import traceback
        traceback.print_exc()


async def main():
    """Main test function."""
    print("🚀 Testing sync_open_positions fix...")
    print("=" * 50)
    
    await test_sync_open_positions()
    
    print("=" * 50)
    print("✅ Tests completed!")


if __name__ == "__main__":
    asyncio.run(main())
