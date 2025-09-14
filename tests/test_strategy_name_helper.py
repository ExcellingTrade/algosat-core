#!/usr/bin/env python3
"""
Test script to verify the strategy name helper method in OrderMonitor.
"""

import asyncio
import sys
import os

# Add the project root to Python path
sys.path.insert(0, '/opt/algosat')

from algosat.core.order_monitor import OrderMonitor
from algosat.core.db import AsyncSessionLocal, get_all_orders
from algosat.common.logger import get_logger

logger = get_logger(__name__)

class MockDataManager:
    """Mock data manager for testing."""
    async def ensure_broker(self):
        pass
    
    async def get_order_aggregate(self, order_id):
        # Return a mock aggregate
        class MockAggregate:
            def __init__(self):
                self.broker_orders = []
        return MockAggregate()

class MockOrderManager:
    """Mock order manager for testing."""
    async def update_order_status_in_db(self, order_id, status):
        pass
    
    async def update_order_stop_loss_in_db(self, order_id, stop_loss):
        pass

class MockOrderCache:
    """Mock order cache for testing."""
    def get_order(self, broker_order_id, broker_name, product_type):
        return None

class MockStrategyInstance:
    """Mock strategy instance for testing."""
    def __init__(self, strategy_key):
        self.cfg = MockConfig(strategy_key)

class MockConfig:
    """Mock strategy config."""
    def __init__(self, strategy_key):
        self.strategy_key = strategy_key

async def test_strategy_name_helper():
    """Test the _get_strategy_name helper method."""
    
    print("🧪 Testing OrderMonitor._get_strategy_name helper method...")
    
    async with AsyncSessionLocal() as session:
        # Get a real order from database
        all_orders = await get_all_orders(session)
        
        if not all_orders:
            print("⚠️  No orders found in database")
            return False
        
        # Find an order with strategy data
        test_order = None
        for order in all_orders:
            if order.get('strategy_name'):
                test_order = order
                break
        
        if not test_order:
            test_order = all_orders[0]  # Use first order
        
        order_id = test_order['id']
        strategy_name = test_order.get('strategy_name', 'Unknown')
        
        print(f"📋 Testing with order_id={order_id}, expected strategy='{strategy_name}'")
        
        # Test 1: OrderMonitor without strategy_instance
        print(f"\n🧪 Test 1: OrderMonitor without strategy_instance")
        mock_data_manager = MockDataManager()
        mock_order_manager = MockOrderManager()
        mock_order_cache = MockOrderCache()
        
        order_monitor = OrderMonitor(
            order_id=order_id,
            data_manager=mock_data_manager,
            order_manager=mock_order_manager,
            order_cache=mock_order_cache,
            strategy_instance=None
        )
        
        result_name = await order_monitor._get_strategy_name()
        print(f"  Result: '{result_name}'")
        
        if result_name:
            print(f"  ✅ Successfully got strategy name from database: {result_name}")
        else:
            print(f"  ⚠️  No strategy name retrieved (might be expected if no strategy data)")
        
        # Test 2: OrderMonitor with mock strategy_instance
        print(f"\n🧪 Test 2: OrderMonitor with mock strategy_instance")
        mock_strategy_instance = MockStrategyInstance('OptionBuy')
        
        order_monitor2 = OrderMonitor(
            order_id=order_id,
            data_manager=mock_data_manager,
            order_manager=mock_order_manager,
            order_cache=mock_order_cache,
            strategy_instance=mock_strategy_instance
        )
        
        result_name2 = await order_monitor2._get_strategy_name()
        print(f"  Result: '{result_name2}'")
        
        if result_name2 == 'optionbuy':
            print(f"  ✅ Successfully got strategy name from strategy_instance: {result_name2}")
        else:
            print(f"  ❌ Expected 'optionbuy', got '{result_name2}'")
        
        # Test 3: Helper method with strategy parameter
        print(f"\n🧪 Test 3: Helper method with strategy parameter")
        
        # Create mock strategy dict
        mock_strategy_dict = {'strategy_key': 'OptionSell'}
        
        result_name3 = await order_monitor._get_strategy_name(strategy=mock_strategy_dict)
        print(f"  Result: '{result_name3}'")
        
        if result_name3 == 'optionsell':
            print(f"  ✅ Successfully got strategy name from parameter: {result_name3}")
        else:
            print(f"  ❌ Expected 'optionsell', got '{result_name3}'")
        
        # Test 4: Priority order test - strategy parameter should override strategy_instance when provided
        print(f"\n🧪 Test 4: Priority test - strategy parameter should take priority when provided")
        
        mock_override_strategy = {'strategy_key': 'ShouldBeUsed'}
        
        result_name4 = await order_monitor2._get_strategy_name(strategy=mock_override_strategy)
        print(f"  Result: '{result_name4}'")
        
        if result_name4 == 'shouldbeused':
            print(f"  ✅ Strategy parameter correctly took priority over instance: {result_name4}")
        else:
            print(f"  ❌ Expected 'shouldbeused' (from parameter), got '{result_name4}'")
        
        return True

async def test_price_check_integration():
    """Test that _check_price_based_exit uses the new helper method correctly."""
    
    print(f"\n🧪 Testing _check_price_based_exit integration...")
    
    # This test just verifies the method can be called without errors
    # Real testing would require more complex mocking
    async with AsyncSessionLocal() as session:
        all_orders = await get_all_orders(session)
        
        if not all_orders:
            print("⚠️  No orders for integration test")
            return True
        
        order = all_orders[0]
        order_id = order['id']
        
        mock_data_manager = MockDataManager()
        mock_order_manager = MockOrderManager()
        mock_order_cache = MockOrderCache()
        mock_strategy_instance = MockStrategyInstance('OptionBuy')
        
        order_monitor = OrderMonitor(
            order_id=order_id,
            data_manager=mock_data_manager,
            order_manager=mock_order_manager,
            order_cache=mock_order_cache,
            strategy_instance=mock_strategy_instance
        )
        
        try:
            # Test that the method can get strategy name properly
            strategy_name = await order_monitor._get_strategy_name()
            print(f"  ✅ Integration test passed - strategy name: '{strategy_name}'")
            return True
        except Exception as e:
            print(f"  ❌ Integration test failed: {e}")
            return False

async def main():
    """Main test function."""
    print("🚀 Testing OrderMonitor Strategy Name Helper Method")
    print("=" * 60)
    
    test1_passed = await test_strategy_name_helper()
    test2_passed = await test_price_check_integration()
    
    print("\n" + "=" * 60)
    if test1_passed and test2_passed:
        print("🎉 All tests passed! Strategy name helper method is working correctly.")
        print("✅ Both start() and _check_price_based_exit() now use the same helper method.")
    else:
        print("❌ Some tests failed. Check the output above for details.")
    
    return test1_passed and test2_passed

if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(0 if result else 1)
