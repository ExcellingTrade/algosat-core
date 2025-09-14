#!/usr/bin/env python3

"""
Test script for the enhanced exit_all_orders functionality with strategy filtering.
This script tests:
1. Exit all orders without strategy filter (existing functionality)
2. Exit all orders with strategy filter (new functionality)
3. Error handling for invalid strategy IDs
4. Edge cases like empty results
"""

import sys
import asyncio
import json
from typing import Dict, Any, List, Optional

# Add the project root to the Python path
sys.path.insert(0, '/opt/algosat')

from algosat.core.db import AsyncSessionLocal, get_orders_by_strategy_id
from algosat.core.dbschema import orders, strategies, strategy_symbols
from algosat.core.order_manager import OrderManager
from algosat.common.logger import get_logger
from sqlalchemy import select, insert, update, delete

logger = get_logger("test_exit_orders_strategy_filter")

class ExitOrdersStrategyTester:
    def __init__(self):
        self.order_manager = OrderManager()
    
    async def setup_test_data(self):
        """Create test data for the strategy filtering test"""
        logger.info("Setting up test data...")
        
        async with AsyncSessionLocal() as session:
            # Clean up existing test data
            await self.cleanup_test_data(session)
            
            # Create test strategies
            strategy1_stmt = insert(strategies).values(
                key="TestStrategy1",
                name="Test Strategy 1",
                description="Test strategy for exit filtering",
                order_type="MARKET",
                product_type="INTRADAY",
                enabled=True
            )
            result1 = await session.execute(strategy1_stmt)
            strategy1_id = result1.inserted_primary_key[0]
            
            strategy2_stmt = insert(strategies).values(
                key="TestStrategy2",
                name="Test Strategy 2",
                description="Another test strategy",
                order_type="MARKET",
                product_type="INTRADAY",
                enabled=True
            )
            result2 = await session.execute(strategy2_stmt)
            strategy2_id = result2.inserted_primary_key[0]
            
            # Create strategy symbols
            symbol1_stmt = insert(strategy_symbols).values(
                strategy_id=strategy1_id,
                symbol="NIFTY50",
                config_id=1,  # Assuming config exists
                status="active"
            )
            result_symbol1 = await session.execute(symbol1_stmt)
            symbol1_id = result_symbol1.inserted_primary_key[0]
            
            symbol2_stmt = insert(strategy_symbols).values(
                strategy_id=strategy2_id,
                symbol="BANKNIFTY",
                config_id=1,  # Assuming config exists
                status="active"
            )
            result_symbol2 = await session.execute(symbol2_stmt)
            symbol2_id = result_symbol2.inserted_primary_key[0]
            
            # Create test orders for both strategies
            # Strategy 1 orders
            order1_stmt = insert(orders).values(
                strategy_symbol_id=symbol1_id,
                strike_symbol="NSE:NIFTY50-TEST1",
                status="FILLED",
                entry_price=100.0,
                qty=50,
                executed_quantity=50,
                side="BUY",
                reason="Test order 1"
            )
            result_order1 = await session.execute(order1_stmt)
            order1_id = result_order1.inserted_primary_key[0]
            
            order2_stmt = insert(orders).values(
                strategy_symbol_id=symbol1_id,
                strike_symbol="NSE:NIFTY50-TEST2",
                status="AWAITING_ENTRY",
                entry_price=200.0,
                qty=25,
                executed_quantity=0,
                side="SELL",
                reason="Test order 2"
            )
            result_order2 = await session.execute(order2_stmt)
            order2_id = result_order2.inserted_primary_key[0]
            
            # Strategy 2 orders
            order3_stmt = insert(orders).values(
                strategy_symbol_id=symbol2_id,
                strike_symbol="NSE:BANKNIFTY-TEST1",
                status="FILLED",
                entry_price=300.0,
                qty=30,
                executed_quantity=30,
                side="BUY",
                reason="Test order 3"
            )
            result_order3 = await session.execute(order3_stmt)
            order3_id = result_order3.inserted_primary_key[0]
            
            await session.commit()
            
            logger.info(f"Created test data:")
            logger.info(f"  Strategy 1 ID: {strategy1_id} with orders: {order1_id}, {order2_id}")
            logger.info(f"  Strategy 2 ID: {strategy2_id} with orders: {order3_id}")
            
            return {
                "strategy1_id": strategy1_id,
                "strategy2_id": strategy2_id,
                "order1_id": order1_id,
                "order2_id": order2_id,
                "order3_id": order3_id
            }
    
    async def cleanup_test_data(self, session):
        """Clean up test data"""
        # Delete test orders
        await session.execute(
            delete(orders).where(orders.c.strike_symbol.like('%TEST%'))
        )
        
        # Delete test strategy symbols
        await session.execute(
            delete(strategy_symbols).where(strategy_symbols.c.symbol.in_(["NIFTY50", "BANKNIFTY"]))
        )
        
        # Delete test strategies
        await session.execute(
            delete(strategies).where(strategies.c.key.like('TestStrategy%'))
        )
        
        await session.commit()
    
    async def test_get_orders_by_strategy_id(self, test_data):
        """Test the new get_orders_by_strategy_id function"""
        logger.info("Testing get_orders_by_strategy_id function...")
        
        async with AsyncSessionLocal() as session:
            # Test getting orders for strategy 1
            strategy1_orders = await get_orders_by_strategy_id(
                session=session,
                strategy_id=test_data["strategy1_id"]
            )
            
            logger.info(f"Strategy 1 orders: {len(strategy1_orders)}")
            for order in strategy1_orders:
                logger.info(f"  Order {order['id']}: {order['strike_symbol']} - {order['status']}")
            
            # Test getting orders for strategy 2
            strategy2_orders = await get_orders_by_strategy_id(
                session=session,
                strategy_id=test_data["strategy2_id"]
            )
            
            logger.info(f"Strategy 2 orders: {len(strategy2_orders)}")
            for order in strategy2_orders:
                logger.info(f"  Order {order['id']}: {order['strike_symbol']} - {order['status']}")
            
            # Test with status filter
            filled_orders = await get_orders_by_strategy_id(
                session=session,
                strategy_id=test_data["strategy1_id"],
                status_filter=["FILLED"]
            )
            
            logger.info(f"Strategy 1 FILLED orders: {len(filled_orders)}")
            
            # Test with non-existent strategy
            empty_orders = await get_orders_by_strategy_id(
                session=session,
                strategy_id=99999
            )
            
            logger.info(f"Non-existent strategy orders: {len(empty_orders)}")
            
            assert len(strategy1_orders) == 2, f"Expected 2 orders for strategy 1, got {len(strategy1_orders)}"
            assert len(strategy2_orders) == 1, f"Expected 1 order for strategy 2, got {len(strategy2_orders)}"
            assert len(filled_orders) == 1, f"Expected 1 filled order, got {len(filled_orders)}"
            assert len(empty_orders) == 0, f"Expected 0 orders for non-existent strategy, got {len(empty_orders)}"
            
            logger.info("✓ get_orders_by_strategy_id function tests passed")
    
    async def test_exit_all_orders_without_filter(self, test_data):
        """Test exit_all_orders without strategy filter (original functionality)"""
        logger.info("Testing exit_all_orders without strategy filter...")
        
        try:
            await self.order_manager.exit_all_orders(
                exit_reason="Test exit all orders without filter"
            )
            logger.info("✓ exit_all_orders without filter completed successfully")
        except Exception as e:
            logger.error(f"✗ exit_all_orders without filter failed: {e}")
            raise
    
    async def test_exit_all_orders_with_strategy_filter(self, test_data):
        """Test exit_all_orders with strategy filter (new functionality)"""
        logger.info("Testing exit_all_orders with strategy filter...")
        
        try:
            # Test with strategy 1
            await self.order_manager.exit_all_orders(
                exit_reason="Test exit orders for strategy 1",
                strategy_id=test_data["strategy1_id"]
            )
            logger.info("✓ exit_all_orders with strategy 1 filter completed successfully")
            
            # Test with strategy 2
            await self.order_manager.exit_all_orders(
                exit_reason="Test exit orders for strategy 2",
                strategy_id=test_data["strategy2_id"]
            )
            logger.info("✓ exit_all_orders with strategy 2 filter completed successfully")
            
        except Exception as e:
            logger.error(f"✗ exit_all_orders with strategy filter failed: {e}")
            raise
    
    async def test_exit_all_orders_with_invalid_strategy(self):
        """Test exit_all_orders with invalid strategy ID"""
        logger.info("Testing exit_all_orders with invalid strategy ID...")
        
        try:
            await self.order_manager.exit_all_orders(
                exit_reason="Test with invalid strategy",
                strategy_id=99999
            )
            logger.info("✓ exit_all_orders with invalid strategy ID completed successfully (no orders to exit)")
        except Exception as e:
            logger.error(f"✗ exit_all_orders with invalid strategy ID failed: {e}")
            raise
    
    async def test_api_endpoint_strategy_filter(self, test_data):
        """Test the API endpoint with strategy filter"""
        logger.info("Testing API endpoint with strategy filter...")
        
        # This is a basic test of the method call structure
        # In a real scenario, you would make HTTP requests to the API
        
        try:
            # Simulate API call with strategy filter
            result = await self.order_manager.exit_all_orders(
                exit_reason="API test with strategy filter",
                strategy_id=test_data["strategy1_id"]
            )
            
            logger.info("✓ API endpoint with strategy filter simulation completed successfully")
            
        except Exception as e:
            logger.error(f"✗ API endpoint with strategy filter failed: {e}")
            raise
    
    async def run_all_tests(self):
        """Run all tests"""
        logger.info("Starting comprehensive exit orders strategy filter tests...")
        
        try:
            # Setup test data
            test_data = await self.setup_test_data()
            
            # Run tests
            await self.test_get_orders_by_strategy_id(test_data)
            await self.test_exit_all_orders_without_filter(test_data)
            await self.test_exit_all_orders_with_strategy_filter(test_data)
            await self.test_exit_all_orders_with_invalid_strategy()
            await self.test_api_endpoint_strategy_filter(test_data)
            
            logger.info("✓ All tests passed successfully!")
            
        except Exception as e:
            logger.error(f"✗ Test failed: {e}")
            raise
        
        finally:
            # Cleanup
            async with AsyncSessionLocal() as session:
                await self.cleanup_test_data(session)
            logger.info("Test data cleaned up")

async def main():
    """Main test runner"""
    tester = ExitOrdersStrategyTester()
    await tester.run_all_tests()

if __name__ == "__main__":
    asyncio.run(main())
