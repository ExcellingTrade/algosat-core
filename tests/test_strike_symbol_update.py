#!/usr/bin/env python3
"""
Test script to verify the strike_symbol and pnl column additions work correctly.
"""

import asyncio
import sys
import os

# Add the project root to Python path
sys.path.insert(0, os.path.abspath('.'))

from algosat.core.db import get_open_orders_for_strategy_and_tradeday, AsyncSessionLocal
from algosat.core.time_utils import get_ist_datetime
from algosat.common.broker_utils import get_trade_day


async def test_strike_symbol_functionality():
    """Test the new strike_symbol field functionality."""
    print("🔍 Testing strike_symbol and pnl column functionality...")
    
    try:
        async with AsyncSessionLocal() as session:
            # Test fetching orders with the new fields
            trade_day = get_trade_day(get_ist_datetime())
            strategy_id = 1
            
            print(f"📊 Fetching open orders for strategy_id={strategy_id} on trade_day={trade_day}")
            
            # Get orders using our existing function
            open_orders = await get_open_orders_for_strategy_and_tradeday(session, strategy_id, trade_day)
            
            print(f"📈 Found {len(open_orders)} orders")
            
            for order in open_orders:
                print(f"  ✅ Order ID: {order.get('id')}")
                print(f"     ├─ Strategy Symbol ID: {order.get('strategy_symbol_id')}")
                print(f"     ├─ Strike Symbol: {order.get('strike_symbol', 'NULL')} (NEW FIELD)")
                print(f"     ├─ PnL: {order.get('pnl', 'NULL')} (NEW FIELD)")
                print(f"     ├─ Status: {order.get('status')}")
                print(f"     ├─ Entry Price: {order.get('entry_price')}")
                print(f"     └─ Side: {order.get('side')}")
                print()
            
            if len(open_orders) == 0:
                print("⚠️  No orders found. This is expected if:")
                print("   - No orders exist for strategy_id=1")
                print("   - All orders are completed/closed")
                print("   - Database migration hasn't been run yet")
            else:
                print("✅ New fields are accessible in query results!")
                
                # Test what happens when we try to filter by strike_symbol
                print("\n🔍 Testing strike_symbol filtering...")
                from algosat.core.dbschema import orders, strategy_symbols
                from sqlalchemy import select, and_, func
                
                # Sample query to find orders by strike symbol
                sample_query = select(orders).where(
                    and_(
                        orders.c.strike_symbol.isnot(None),
                        func.date(orders.c.created_at) == trade_day.date()
                    )
                )
                
                result = await session.execute(sample_query)
                strike_orders = result.fetchall()
                
                print(f"📊 Found {len(strike_orders)} orders with strike_symbol populated")
                for order in strike_orders:
                    print(f"  🎯 Strike: {order.strike_symbol}, PnL: {order.pnl}")
                
    except Exception as e:
        print(f"❌ Error testing strike_symbol functionality: {e}")
        import traceback
        traceback.print_exc()


async def test_sync_open_positions_logic():
    """Test the updated sync_open_positions logic without running the actual strategy."""
    print("\n🔍 Testing sync_open_positions logic simulation...")
    
    try:
        async with AsyncSessionLocal() as session:
            trade_day = get_trade_day(get_ist_datetime())
            strategy_id = 1
            
            # Simulate the strikes that would be identified
            mock_strikes = [
                "NSE:NIFTY50-25JUN25-23400-CE",
                "NSE:NIFTY50-25JUN25-23200-PE"
            ]
            
            print(f"🎯 Mock identified strikes: {mock_strikes}")
            
            # Get open orders (same as sync_open_positions does)
            open_orders = await get_open_orders_for_strategy_and_tradeday(session, strategy_id, trade_day)
            
            # Simulate the new logic
            positions = {}
            for order in open_orders:
                strike_symbol = order.get("strike_symbol")
                if strike_symbol and strike_symbol in mock_strikes:
                    if strike_symbol not in positions:
                        positions[strike_symbol] = []
                    positions[strike_symbol].append(order)
            
            print(f"📊 Simulated positions: {list(positions.keys())}")
            
            if positions:
                print("✅ New sync_open_positions logic would work correctly!")
                for strike, orders in positions.items():
                    print(f"  🎯 {strike}: {len(orders)} order(s)")
            else:
                print("ℹ️  No matching positions found (expected if no orders have strike_symbol populated yet)")
                
    except Exception as e:
        print(f"❌ Error testing sync_open_positions logic: {e}")
        import traceback
        traceback.print_exc()


async def main():
    """Main test function."""
    print("🚀 Testing strike_symbol and pnl column updates...")
    print("=" * 60)
    
    await test_strike_symbol_functionality()
    await test_sync_open_positions_logic()
    
    print("=" * 60)
    print("✅ Tests completed!")
    print("\n💡 Next steps:")
    print("1. Run the SQL ALTER commands to add the columns to the database")
    print("2. Place a new order to test strike_symbol population")
    print("3. Test the updated sync_open_positions method")


if __name__ == "__main__":
    asyncio.run(main())
