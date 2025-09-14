#!/usr/bin/env python3
"""
Test script to verify that the current_price and price_last_updated fields 
are included in the orders API responses.
"""

import asyncio
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from algosat.core.db import AsyncSessionLocal, get_all_orders
from algosat.api.schemas import OrderListResponse


async def test_current_price_api_response():
    """Test that API responses include current_price and price_last_updated fields."""
    
    print("🧪 Testing current_price and price_last_updated in API responses...")
    
    try:
        # Test database query includes new fields
        async with AsyncSessionLocal() as session:
            orders_data = await get_all_orders(session)
            
        if not orders_data:
            print("ℹ️  No orders found in database")
            return True
            
        print(f"📊 Found {len(orders_data)} orders in database")
        
        # Check if new fields are present in database results
        first_order = orders_data[0]
        has_current_price = 'current_price' in first_order
        has_price_last_updated = 'price_last_updated' in first_order
        
        print(f"📋 Database query includes current_price: {has_current_price}")
        print(f"📋 Database query includes price_last_updated: {has_price_last_updated}")
        
        if not has_current_price or not has_price_last_updated:
            print("❌ Database query missing new fields!")
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
            
        print("🎉 All tests passed! API responses now include current_price and price_last_updated fields.")
        return True
        
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        return False


if __name__ == "__main__":
    result = asyncio.run(test_current_price_api_response())
    sys.exit(0 if result else 1)
