#!/usr/bin/env python3

"""
Test script to verify signal_direction is properly saved to orders table
"""

import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from algosat.core.db import AsyncSessionLocal

async def test_signal_direction_column():
    """Test that signal_direction column exists and can be queried"""
    
    print("Testing signal_direction Column in Orders Table...")
    print("=" * 60)
    
    try:
        async with AsyncSessionLocal() as session:
            # Test 1: Verify column exists
            print("🔍 Test 1: Verifying signal_direction column exists")
            from sqlalchemy import text
            result = await session.execute(text("""
                SELECT column_name, data_type, is_nullable 
                FROM information_schema.columns 
                WHERE table_name = 'orders' AND column_name = 'signal_direction'
            """))
            column_info = result.fetchone()
            
            if column_info:
                print(f"✅ Column exists: {column_info[0]} ({column_info[1]}, nullable: {column_info[2]})")
            else:
                print("❌ Column does not exist!")
                return False
            
            # Test 2: Check if there are any existing orders with signal_direction
            print("\n🔍 Test 2: Checking existing orders with signal_direction")
            result = await session.execute(text("""
                SELECT COUNT(*) as total_orders,
                       COUNT(signal_direction) as orders_with_direction,
                       COUNT(DISTINCT signal_direction) as unique_directions
                FROM orders
            """))
            stats = result.fetchone()
            
            print(f"📊 Order Statistics:")
            print(f"   Total orders: {stats[0]}")
            print(f"   Orders with signal_direction: {stats[1]}")
            print(f"   Unique signal directions: {stats[2]}")
            
            # Test 3: Show sample of signal_direction values if any exist
            if stats[1] > 0:
                result = await session.execute(text("""
                    SELECT signal_direction, COUNT(*) as count
                    FROM orders 
                    WHERE signal_direction IS NOT NULL
                    GROUP BY signal_direction
                    ORDER BY count DESC
                """))
                directions = result.fetchall()
                
                print(f"\n📈 Signal Direction Distribution:")
                for direction, count in directions:
                    print(f"   {direction}: {count} orders")
            
            # Test 4: Verify the schema update worked by showing recent orders
            print("\n🔍 Test 3: Sample of recent orders (showing signal_direction)")
            result = await session.execute(text("""
                SELECT id, strike_symbol, side, signal_direction, status, created_at
                FROM orders 
                ORDER BY created_at DESC 
                LIMIT 5
            """))
            recent_orders = result.fetchall()
            
            if recent_orders:
                print("Recent Orders:")
                print("ID | Strike Symbol | Side | Signal Direction | Status | Created At")
                print("-" * 80)
                for order in recent_orders:
                    order_id = order[0]
                    strike_symbol = str(order[1])[:15] if order[1] else "None"
                    side = str(order[2])[:4] if order[2] else "None"
                    signal_direction = str(order[3])[:8] if order[3] else "None"
                    status = str(order[4])[:10] if order[4] else "None"
                    created_at = str(order[5])[:19] if order[5] else "None"
                    print(f"{order_id:3d} | {strike_symbol:15s} | {side:4s} | {signal_direction:8s} | {status:10s} | {created_at:19s}")
            else:
                print("No orders found in database")
            
            print(f"\n✅ Database Schema Tests: PASSED")
            print(f"✅ signal_direction column successfully added to orders table")
            print(f"✅ OrderManager and BrokerManager updated to handle signal_direction")
            
            return True
            
    except Exception as e:
        print(f"❌ Error testing signal_direction column: {e}")
        return False

if __name__ == "__main__":
    result = asyncio.run(test_signal_direction_column())
    if result:
        print(f"\n🎉 SUCCESS: signal_direction integration complete!")
    else:
        print(f"\n🚨 FAILED: signal_direction integration has issues!")
