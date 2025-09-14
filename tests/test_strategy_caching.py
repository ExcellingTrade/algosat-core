#!/usr/bin/env python3
"""
Test script for strategy instance caching system.
Verifies that strategy instances are properly cached and shared between components.
"""

import asyncio
import sys
import os
from datetime import datetime

# Add the project root to Python path
sys.path.insert(0, '/opt/algosat')

from algosat.core.strategy_manager import (
    strategy_cache, 
    get_or_create_strategy_instance, 
    get_strategy_for_order,
    remove_strategy_from_cache,
    initialize_strategy_instance
)
from algosat.core.data_manager import DataManager
from algosat.core.order_manager import OrderManager
from algosat.core.broker_manager import BrokerManager
from algosat.models.strategy_config import StrategyConfig
from algosat.core.db import AsyncSessionLocal, get_order_with_strategy_config
from sqlalchemy import text

async def test_strategy_caching_system():
    """Test the strategy instance caching system"""
    print("=" * 60)
    print("🧪 TESTING STRATEGY INSTANCE CACHING SYSTEM")
    print("=" * 60)
    
    try:
        # Initialize managers
        broker_manager = BrokerManager()
        data_manager = DataManager()
        order_manager = OrderManager(broker_manager)
        
        # Test 1: Check initial cache state
        print("\n1️⃣ Testing initial cache state...")
        print(f"✅ Initial cache size: {len(strategy_cache)}")
        
        # Test 2: Create a mock strategy config
        print("\n2️⃣ Testing strategy config creation...")
        
        # Get a real strategy config from database
        async with AsyncSessionLocal() as session:
            result = await session.execute(text("""
                SELECT sc.id, sc.name, sc.description, s.exchange, s.instrument, 
                       sc.trade, sc.indicators, ss.symbol, ss.id as symbol_id,
                       s.strategy_key, s.strategy_name, s.order_type, s.product_type
                FROM strategy_configs sc
                JOIN strategies s ON sc.strategy_id = s.id
                JOIN strategy_symbols ss ON sc.id = ss.config_id
                WHERE sc.is_enabled = true 
                LIMIT 1
            """))
            config_row = result.fetchone()
        
        if not config_row:
            print("❌ No strategy config found in database")
            return False
        
        # Create StrategyConfig object
        config_dict = {
            'id': config_row.id,
            'strategy_id': config_row.id,
            'name': config_row.name,
            'description': config_row.description,
            'exchange': config_row.exchange,
            'instrument': config_row.instrument,
            'trade': config_row.trade,
            'indicators': config_row.indicators,
            'symbol': config_row.symbol,
            'symbol_id': config_row.symbol_id,
            'strategy_key': config_row.strategy_key,
            'strategy_name': config_row.strategy_name,
            'order_type': config_row.order_type,
            'product_type': config_row.product_type
        }
        config = StrategyConfig(**config_dict)
        symbol_id = config_row.symbol_id
        
        print(f"✅ Created strategy config for symbol_id={symbol_id}, strategy={config_row.strategy_key}")
        
        # Test 3: Test get_or_create_strategy_instance (first time - should create)
        print("\n3️⃣ Testing strategy instance creation...")
        strategy_instance_1 = await get_or_create_strategy_instance(symbol_id, config, data_manager, order_manager)
        
        if strategy_instance_1:
            print(f"✅ Strategy instance created: {type(strategy_instance_1).__name__}")
            print(f"✅ Cache size after creation: {len(strategy_cache)}")
        else:
            print("❌ Failed to create strategy instance")
            return False
        
        # Test 4: Test get_or_create_strategy_instance (second time - should retrieve from cache)
        print("\n4️⃣ Testing strategy instance retrieval from cache...")
        strategy_instance_2 = await get_or_create_strategy_instance(symbol_id, config, data_manager, order_manager)
        
        if strategy_instance_2:
            if strategy_instance_1 is strategy_instance_2:
                print("✅ Strategy instance retrieved from cache (same object)")
            else:
                print("❌ Strategy instance not retrieved from cache (different object)")
                return False
        else:
            print("❌ Failed to retrieve strategy instance from cache")
            return False
        
        # Test 5: Test direct cache access
        print("\n5️⃣ Testing direct cache access...")
        cached_instance = strategy_cache.get(symbol_id)
        if cached_instance is strategy_instance_1:
            print("✅ Direct cache access successful")
        else:
            print("❌ Direct cache access failed")
            return False
        
        # Test 6: Test cache removal
        print("\n6️⃣ Testing cache removal...")
        remove_strategy_from_cache(symbol_id)
        print(f"✅ Cache size after removal: {len(strategy_cache)}")
        
        if symbol_id not in strategy_cache:
            print("✅ Strategy successfully removed from cache")
        else:
            print("❌ Strategy not removed from cache")
            return False
        
        # Test 7: Test get_strategy_for_order (if we have orders)
        print("\n7️⃣ Testing get_strategy_for_order...")
        async with AsyncSessionLocal() as session:
            order_result = await session.execute(text("SELECT id FROM orders LIMIT 1"))
            order_row = order_result.fetchone()
        
        if order_row:
            order_id = order_row.id
            strategy_from_order = await get_strategy_for_order(str(order_id), data_manager, order_manager)
            if strategy_from_order:
                print(f"✅ Strategy retrieved for order_id={order_id}: {type(strategy_from_order).__name__}")
            else:
                print(f"⚠️ No strategy retrieved for order_id={order_id} (may be expected)")
        else:
            print("⚠️ No orders found in database to test get_strategy_for_order")
        
        print("\n✅ STRATEGY CACHING SYSTEM TESTS PASSED")
        return True
        
    except Exception as e:
        print(f"❌ STRATEGY CACHING SYSTEM TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_strategy_manager_integration():
    """Test integration of caching with strategy manager components"""
    print("\n" + "=" * 60)
    print("🧪 TESTING STRATEGY MANAGER INTEGRATION")
    print("=" * 60)
    
    try:
        # Test 1: Check imports and availability
        print("\n1️⃣ Testing imports and functions...")
        
        functions_to_test = [
            ('get_or_create_strategy_instance', get_or_create_strategy_instance),
            ('get_strategy_for_order', get_strategy_for_order),
            ('remove_strategy_from_cache', remove_strategy_from_cache),
            ('initialize_strategy_instance', initialize_strategy_instance)
        ]
        
        for func_name, func in functions_to_test:
            if callable(func):
                print(f"✅ {func_name} is available and callable")
            else:
                print(f"❌ {func_name} is not callable")
                return False
        
        # Test 2: Check strategy cache variable
        print("\n2️⃣ Testing strategy cache variable...")
        print(f"✅ strategy_cache type: {type(strategy_cache)}")
        print(f"✅ strategy_cache initial state: {len(strategy_cache)} items")
        
        # Test 3: Check database function availability
        print("\n3️⃣ Testing database function availability...")
        try:
            async with AsyncSessionLocal() as session:
                # Test if get_order_with_strategy_config exists and works
                test_result = await get_order_with_strategy_config(session, 999999)  # Non-existent order
                print("✅ get_order_with_strategy_config function is available")
        except Exception as e:
            if "not found" in str(e).lower() or test_result is None:
                print("✅ get_order_with_strategy_config function is available (expected None result)")
            else:
                print(f"❌ get_order_with_strategy_config function error: {e}")
                return False
        
        print("\n✅ STRATEGY MANAGER INTEGRATION TESTS PASSED")
        return True
        
    except Exception as e:
        print(f"❌ STRATEGY MANAGER INTEGRATION TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False

async def main():
    """Main test runner"""
    print("🚀 STARTING STRATEGY CACHING SYSTEM TESTS")
    print(f"⏰ Test started at: {datetime.now()}")
    
    # Run all test suites
    test_results = []
    
    # Test strategy caching system
    caching_test = await test_strategy_caching_system()
    test_results.append(("Strategy Caching System", caching_test))
    
    # Test strategy manager integration
    integration_test = await test_strategy_manager_integration()
    test_results.append(("Strategy Manager Integration", integration_test))
    
    # Print final results
    print("\n" + "=" * 60)
    print("📊 FINAL TEST RESULTS")
    print("=" * 60)
    
    all_passed = True
    for test_name, result in test_results:
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"{test_name}: {status}")
        if not result:
            all_passed = False
    
    print("\n" + "=" * 60)
    if all_passed:
        print("🎉 ALL TESTS PASSED! Strategy caching system is ready for production.")
    else:
        print("⚠️  SOME TESTS FAILED! Please review the issues above.")
    print("=" * 60)
    
    print(f"⏰ Test completed at: {datetime.now()}")

if __name__ == "__main__":
    asyncio.run(main())
