#!/usr/bin/env python3
"""
Direct database test for orders with smart_level_enabled field.
This script tests the database functions and schema without requiring API server.
"""

import asyncio
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from algosat.core.db import AsyncSessionLocal, get_all_orders, get_orders_by_broker, get_orders_by_strategy_symbol_id
from algosat.api.schemas import OrderListResponse


async def test_database_functions():
    """Test database functions include smart_level_enabled field."""
    
    print("🧪 Testing database functions for smart_level_enabled field...")
    
    try:
        async with AsyncSessionLocal() as session:
            print("\n1️⃣ Testing get_all_orders()...")
            orders_data = await get_all_orders(session)
            
            if not orders_data:
                print("ℹ️  No orders found in database")
            else:
                print(f"📊 Found {len(orders_data)} orders in database")
                
                # Check first order
                first_order = orders_data[0]
                print(f"📋 Available fields: {list(first_order.keys())}")
                
                # Check for new field
                has_smart_level_enabled = 'smart_level_enabled' in first_order
                print(f"📊 smart_level_enabled field present: {has_smart_level_enabled}")
                
                if has_smart_level_enabled:
                    smart_level_value = first_order['smart_level_enabled']
                    print(f"📊 smart_level_enabled value: {smart_level_value} (type: {type(smart_level_value)})")
                else:
                    print("❌ smart_level_enabled field missing!")
                    return False
                
                # Test schema validation
                print("\n2️⃣ Testing schema validation...")
                first_order['order_id'] = first_order['id']  # Add required alias
                
                try:
                    order_response = OrderListResponse(**first_order)
                    print("✅ Schema validation passed")
                    print(f"📊 Schema smart_level_enabled: {order_response.smart_level_enabled}")
                except Exception as e:
                    print(f"❌ Schema validation failed: {e}")
                    return False
            
            # Test other functions
            print("\n3️⃣ Testing get_orders_by_broker()...")
            try:
                broker_orders = await get_orders_by_broker(session, "zerodha")
                print(f"📊 Found {len(broker_orders)} orders for broker 'zerodha'")
                
                if broker_orders:
                    has_field = 'smart_level_enabled' in broker_orders[0]
                    print(f"📊 smart_level_enabled in broker orders: {has_field}")
                    if has_field:
                        print(f"📊 Value: {broker_orders[0]['smart_level_enabled']}")
            except Exception as e:
                print(f"⚠️  Broker test failed (may be expected): {e}")
            
            # Test strategy symbol orders
            print("\n4️⃣ Testing get_orders_by_strategy_symbol_id()...")
            if orders_data:
                # Get a strategy_symbol_id from existing orders
                strategy_symbol_id = orders_data[0].get('strategy_symbol_id')
                if strategy_symbol_id:
                    symbol_orders = await get_orders_by_strategy_symbol_id(session, strategy_symbol_id)
                    print(f"📊 Found {len(symbol_orders)} orders for strategy_symbol_id {strategy_symbol_id}")
                    
                    if symbol_orders:
                        has_field = 'smart_level_enabled' in symbol_orders[0]
                        print(f"📊 smart_level_enabled in symbol orders: {has_field}")
                        if has_field:
                            print(f"📊 Value: {symbol_orders[0]['smart_level_enabled']}")
                        
                        # Test order_id alias
                        symbol_orders[0]['order_id'] = symbol_orders[0]['id']
                        try:
                            OrderListResponse(**symbol_orders[0])
                            print("✅ Symbol orders schema validation passed")
                        except Exception as e:
                            print(f"❌ Symbol orders schema validation failed: {e}")
                            return False
                else:
                    print("ℹ️  No strategy_symbol_id found in orders")
            
        print("\n✅ All database tests completed successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Database test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_sample_data_creation():
    """Test creating sample data with smart_level_enabled field."""
    
    print("\n🧪 Testing sample data creation...")
    
    # Sample order data
    sample_orders = [
        {
            'id': 1,
            'order_id': 1,
            'strategy_symbol_id': 1,
            'strategy_name': 'SwingHighLowBuy',
            'symbol': 'NIFTY50',
            'strike_symbol': 'NIFTY50-CE-23000',
            'status': 'OPEN',
            'smart_level_enabled': True,
            'pnl': 150.0,
            'entry_price': 200.0,
            'lot_qty': 50,
            'broker_executions': []
        },
        {
            'id': 2,
            'order_id': 2,
            'strategy_symbol_id': 2,
            'strategy_name': 'OptionBuy',
            'symbol': 'BANKNIFTY',
            'strike_symbol': 'BANKNIFTY-PE-45000',
            'status': 'CLOSED',
            'smart_level_enabled': False,
            'pnl': -50.0,
            'entry_price': 180.0,
            'exit_price': 130.0,
            'lot_qty': 25,
            'broker_executions': []
        }
    ]
    
    print(f"📊 Testing {len(sample_orders)} sample orders...")
    
    for i, order_data in enumerate(sample_orders, 1):
        try:
            order_response = OrderListResponse(**order_data)
            print(f"✅ Sample order {i}: Schema validation passed")
            print(f"   Symbol: {order_response.symbol}")
            print(f"   Strategy: {order_response.strategy_name}")
            print(f"   Smart Levels: {order_response.smart_level_enabled}")
        except Exception as e:
            print(f"❌ Sample order {i}: Schema validation failed - {e}")
            return False
    
    print("✅ All sample data tests passed!")
    return True


def print_schema_info():
    """Print information about the OrderListResponse schema."""
    
    print("📋 OrderListResponse Schema Information:")
    print("="*50)
    
    try:
        from algosat.api.schemas import OrderListResponse
        
        for field_name, field_info in OrderListResponse.model_fields.items():
            field_type = field_info.annotation if hasattr(field_info, 'annotation') else 'Unknown'
            default = field_info.default if hasattr(field_info, 'default') else 'No default'
            print(f"  {field_name}: {field_type} (default: {default})")
        
        print("="*50)
        
    except Exception as e:
        print(f"❌ Failed to load schema info: {e}")


async def main():
    """Main test runner."""
    print("🚀 Starting Direct Database Tests for Orders API with Smart Levels...")
    
    # Print schema information
    print_schema_info()
    
    # Run tests
    tests = [
        ("Database Functions", test_database_functions),
        ("Sample Data Creation", test_sample_data_creation),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            print(f"\n🔄 Running {test_name}...")
            result = await test_func()
            results.append((test_name, result))
            if result:
                print(f"✅ {test_name}: PASSED")
            else:
                print(f"❌ {test_name}: FAILED")
        except Exception as e:
            print(f"💥 {test_name}: EXCEPTION - {e}")
            results.append((test_name, False))
    
    # Summary
    print("\n" + "="*50)
    print("📊 TEST SUMMARY")
    print("="*50)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"{test_name}: {status}")
    
    print(f"\nOverall: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed!")
        return True
    else:
        print("⚠️  Some tests failed")
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    
    if success:
        print("\n🎯 All direct tests completed successfully!")
        exit(0)
    else:
        print("\n💥 Some direct tests failed!")
        exit(1)
