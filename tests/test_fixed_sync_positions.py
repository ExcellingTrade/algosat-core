#!/usr/bin/env python3
"""
Test the fixed sync_open_positions functionality
"""

import asyncio
import sys
import os

# Add the project root to Python path
sys.path.insert(0, os.path.abspath('.'))

from algosat.core.db import AsyncSessionLocal, get_open_orders_for_strategy_and_tradeday
from algosat.core.time_utils import get_ist_datetime
from algosat.common.broker_utils import get_trade_day

async def test_fixed_sync_positions():
    """Test the fixed sync_open_positions query."""
    print("🔍 Testing fixed sync_open_positions query...")
    
    strategy_id = 1
    trade_day = get_trade_day(get_ist_datetime())
    
    print(f"📊 Looking for strategy_id={strategy_id} on trade_day={trade_day} (date: {trade_day.date()})")
    print()
    
    async with AsyncSessionLocal() as session:
        # Test the fixed function
        print("🔍 Testing fixed get_open_orders_for_strategy_and_tradeday...")
        open_orders = await get_open_orders_for_strategy_and_tradeday(session, strategy_id, trade_day)
        
        print(f"📊 Found {len(open_orders)} orders using fixed query")
        
        if open_orders:
            for order in open_orders:
                print(f"  ✅ Order ID: {order['id']}")
                print(f"     ├─ Status: {order['status']}")
                print(f"     ├─ Strategy Symbol ID: {order['strategy_symbol_id']}")
                print(f"     ├─ Signal Time: {order['signal_time']}")
                print(f"     ├─ Entry Time: {order['entry_time']}")
                print(f"     └─ Created At: {order['created_at']}")
                print()
        else:
            print("ℹ️  Still no orders found. Let's check what statuses exist...")
            
            # Debug: Check what statuses exist for this strategy
            from algosat.core.dbschema import orders, strategy_symbols
            from sqlalchemy import select, join
            
            join_stmt = join(
                orders, 
                strategy_symbols, 
                orders.c.strategy_symbol_id == strategy_symbols.c.id
            )
            
            all_orders_query = (
                select(orders.c.id, orders.c.status, orders.c.signal_time, orders.c.created_at)
                .select_from(join_stmt)
                .where(strategy_symbols.c.strategy_id == strategy_id)
            )
            
            result = await session.execute(all_orders_query)
            all_orders = result.fetchall()
            
            print(f"📊 All orders for strategy {strategy_id} (any status, any date):")
            for order in all_orders:
                signal_date = order.signal_time.date() if order.signal_time else "None"
                created_date = order.created_at.date() if order.created_at else "None"
                print(f"  - ID: {order.id}, Status: {order.status}")
                print(f"    Signal Date: {signal_date}, Created Date: {created_date}")
                print(f"    Trade Day: {trade_day.date()}")

async def main():
    """Main test function."""
    print("🚀 Testing fixed sync_open_positions...")
    print("=" * 60)
    
    await test_fixed_sync_positions()
    
    print("=" * 60)
    print("✅ Tests completed!")

if __name__ == "__main__":
    asyncio.run(main())
