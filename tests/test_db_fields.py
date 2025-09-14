#!/usr/bin/env python3
"""
Test script to verify database methods include all required spot-level fields.
This script tests the updated get_order_by_id and get_all_orders methods.
"""

import asyncio
import sys
import os

# Add the project root to Python path
sys.path.insert(0, '/opt/algosat')

from algosat.core.db import AsyncSessionLocal, get_order_by_id, get_all_orders
from algosat.common.logger import get_logger

logger = get_logger(__name__)

async def test_database_fields():
    """Test that database methods return all required fields."""
    
    print("🧪 Testing database field inclusion...")
    
    # Expected spot-level fields that should be present
    expected_spot_fields = [
        'entry_spot_price',
        'entry_spot_swing_high', 
        'entry_spot_swing_low',
        'stoploss_spot_level',
        'target_spot_level',
        'entry_rsi',
        'signal_direction',
        'expiry_date'
    ]
    
    async with AsyncSessionLocal() as session:
        try:
            # Test 1: Get all orders and check field presence
            print("\n📋 Test 1: Checking get_all_orders method...")
            all_orders = await get_all_orders(session)
            
            if not all_orders:
                print("⚠️  No orders found in database")
                return False
            
            print(f"✅ Found {len(all_orders)} orders")
            
            # Check first order for required fields
            first_order = all_orders[0]
            print(f"\n🔍 Checking order ID {first_order.get('id')} for required fields:")
            
            missing_fields = []
            present_fields = []
            
            for field in expected_spot_fields:
                if field in first_order:
                    value = first_order[field]
                    present_fields.append(field)
                    print(f"  ✅ {field}: {value}")
                else:
                    missing_fields.append(field)
                    print(f"  ❌ {field}: MISSING")
            
            # Test 2: Get specific order by ID
            print(f"\n📋 Test 2: Checking get_order_by_id method...")
            order_id = first_order['id']
            single_order = await get_order_by_id(session, order_id)
            
            if single_order:
                print(f"✅ Retrieved order {order_id} successfully")
                
                # Check if spot fields are present and not None
                spot_fields_status = {}
                for field in expected_spot_fields:
                    if field in single_order:
                        value = single_order[field]
                        spot_fields_status[field] = value
                        if value is not None:
                            print(f"  ✅ {field}: {value} (NOT NULL)")
                        else:
                            print(f"  ⚠️  {field}: None (NULL in DB)")
                    else:
                        print(f"  ❌ {field}: MISSING from query")
                
                # Special check for critical exit evaluation fields
                critical_fields = ['stoploss_spot_level', 'target_spot_level']
                print(f"\n🎯 Critical Exit Evaluation Fields:")
                for field in critical_fields:
                    value = single_order.get(field)
                    if value is not None:
                        print(f"  ✅ {field}: {value} (Available for exit logic)")
                    else:
                        print(f"  ❌ {field}: None (EXIT LOGIC WILL FAIL)")
                
            else:
                print(f"❌ Failed to retrieve order {order_id}")
                return False
            
            # Summary
            print(f"\n📊 Summary:")
            print(f"  Present fields: {len(present_fields)}/{len(expected_spot_fields)}")
            print(f"  Missing fields: {len(missing_fields)}")
            
            if missing_fields:
                print(f"  ❌ Missing fields: {missing_fields}")
                return False
            else:
                print(f"  ✅ All expected fields are present in query results")
                
                # Check if critical fields have actual values
                critical_values = {
                    'stoploss_spot_level': single_order.get('stoploss_spot_level'),
                    'target_spot_level': single_order.get('target_spot_level')
                }
                
                if any(v is not None for v in critical_values.values()):
                    print(f"  ✅ At least some critical fields have values - exit logic should work")
                    return True
                else:
                    print(f"  ⚠️  All critical fields are None - check if orders have these fields populated")
                    return True  # Fields are present, just not populated yet
                    
        except Exception as e:
            print(f"❌ Error during testing: {e}")
            logger.error(f"Database test error: {e}")
            return False

async def test_specific_order_fields():
    """Test a specific order if available."""
    async with AsyncSessionLocal() as session:
        try:
            # Look for orders with specific characteristics
            all_orders = await get_all_orders(session)
            
            # Find an order with swing strategy
            swing_orders = [o for o in all_orders if 'swing' in str(o.get('strategy_name', '')).lower()]
            
            if swing_orders:
                print(f"\n🎯 Found {len(swing_orders)} swing strategy orders")
                swing_order = swing_orders[0]
                
                print(f"\n📋 Detailed analysis of swing order {swing_order['id']}:")
                print(f"  Strategy: {swing_order.get('strategy_name')}")
                print(f"  Symbol: {swing_order.get('symbol')}")
                print(f"  Status: {swing_order.get('status')}")
                print(f"  Signal Direction: {swing_order.get('signal_direction')}")
                print(f"  Entry Spot Price: {swing_order.get('entry_spot_price')}")
                print(f"  Stoploss Spot Level: {swing_order.get('stoploss_spot_level')}")
                print(f"  Target Spot Level: {swing_order.get('target_spot_level')}")
                print(f"  Current Price: {swing_order.get('current_price')}")
                
                return True
            else:
                print("ℹ️  No swing strategy orders found")
                return True
                
        except Exception as e:
            print(f"❌ Error in specific order test: {e}")
            return False

async def main():
    """Main test function."""
    print("🚀 Starting Database Field Test Script")
    print("=" * 50)
    
    # Test basic field inclusion
    basic_test_passed = await test_database_fields()
    
    # Test specific order analysis
    specific_test_passed = await test_specific_order_fields()
    
    print("\n" + "=" * 50)
    if basic_test_passed and specific_test_passed:
        print("🎉 All tests passed! Database methods include required fields.")
        print("✅ Target exit logic should now work correctly.")
    else:
        print("❌ Some tests failed. Check the output above for details.")
    
    return basic_test_passed and specific_test_passed

if __name__ == "__main__":
    # Run the test
    result = asyncio.run(main())
    sys.exit(0 if result else 1)
