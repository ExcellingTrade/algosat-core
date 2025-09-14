#!/usr/bin/env python3
"""
Test script to verify that the /strategies/symbols/{strategy_symbol_id}/trades endpoint 
includes current_price and price_last_updated fields.
"""

import asyncio
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from algosat.core.db import AsyncSessionLocal, get_orders_by_strategy_symbol_id
from algosat.api.schemas import OrderListResponse


async def test_strategy_symbol_trades_endpoint():
    """Test that the strategy symbol trades endpoint includes current_price and price_last_updated fields."""
    
    print("🧪 Testing current_price and price_last_updated in /strategy_symbol/{id}/trades endpoint...")
    
    try:
        # Test database query for a sample strategy_symbol_id (4 as mentioned in user request)
        test_strategy_symbol_id = 4
        
        async with AsyncSessionLocal() as session:
            orders_data = await get_orders_by_strategy_symbol_id(session, test_strategy_symbol_id)
            
        if not orders_data:
            print(f"ℹ️  No orders found for strategy_symbol_id={test_strategy_symbol_id}")
            # Try to find any orders with any strategy_symbol_id
            async with AsyncSessionLocal() as session:
                from algosat.core.db import get_all_orders
                all_orders = await get_all_orders(session)
                if all_orders:
                    test_order = all_orders[0]
                    test_strategy_symbol_id = test_order['strategy_symbol_id']
                    print(f"📋 Using strategy_symbol_id={test_strategy_symbol_id} from existing order")
                    orders_data = await get_orders_by_strategy_symbol_id(session, test_strategy_symbol_id)
                else:
                    print("❌ No orders found in database at all")
                    return False
            
        print(f"📊 Found {len(orders_data)} orders for strategy_symbol_id={test_strategy_symbol_id}")
        
        # Check if new fields are present in database results
        first_order = orders_data[0]
        has_current_price = 'current_price' in first_order
        has_price_last_updated = 'price_last_updated' in first_order
        
        print(f"📋 Database query includes current_price: {has_current_price}")
        print(f"📋 Database query includes price_last_updated: {has_price_last_updated}")
        
        if not has_current_price or not has_price_last_updated:
            print("❌ Database query missing new fields!")
            print(f"Available fields: {list(first_order.keys())}")
            return False
            
        # Test schema validation
        try:
            # Add order_id field for schema compatibility
            first_order['order_id'] = first_order['id']
            
            order_response = OrderListResponse(**first_order)
            print(f"✅ Schema validation passed")
            print(f"📊 Sample order current_price: {order_response.current_price}")
            print(f"📊 Sample order price_last_updated: {order_response.price_last_updated}")
            
        except Exception as schema_error:
            print(f"❌ Schema validation failed: {schema_error}")
            return False
            
        print("🎉 All tests passed! /strategy_symbol/{id}/trades endpoint now includes current_price and price_last_updated fields.")
        return True
        
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    result = asyncio.run(test_strategy_symbol_trades_endpoint())
    sys.exit(0 if result else 1)
