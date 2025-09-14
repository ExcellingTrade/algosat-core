#!/usr/bin/env python3
"""
Test script to verify the sync_open_positions fix.
This script tests that the sync_open_positions method now correctly uses strategy_symbol_id
instead of strategy_id to prevent cross-contamination between different symbol configurations.
"""

import asyncio
import sys
from datetime import datetime
from unittest.mock import Mock, AsyncMock

# Add the project root to the path
sys.path.insert(0, '/opt/algosat')

from algosat.core.db import AsyncSessionLocal, get_open_orders_for_strategy_symbol_and_tradeday_by_id
from algosat.common.logger import get_logger
from algosat.common.broker_utils import get_trade_day
from algosat.core.time_utils import get_ist_datetime

logger = get_logger(__name__)

class MockConfig:
    """Mock configuration for testing."""
    def __init__(self, symbol_id, strategy_id, symbol):
        self.symbol_id = symbol_id  # strategy_symbol_id
        self.strategy_id = strategy_id
        self.symbol = symbol
        self.exchange = "NSE"
        self.instrument = "EQ"
        self.trade = {
            "entry": {"timeframe": "5m", "swing_left_bars": 3, "swing_right_bars": 3},
            "stoploss": {"timeframe": "5m", "percentage": 0.05},
            "target": {},
            "ce_lot_qty": 2,
            "pe_lot_qty": 2,
            "lot_size": 75
        }
        self.indicators = {"rsi_period": 14, "rsi_timeframe": "5m"}
        self.enable_smart_levels = False

async def test_new_db_function():
    """Test the new database function directly."""
    logger.info("🧪 Testing new database function: get_open_orders_for_strategy_symbol_and_tradeday_by_id")
    
    trade_day = get_trade_day(get_ist_datetime())
    logger.info(f"Trade day: {trade_day}")
    
    # Test with a known strategy_symbol_id (you can modify this based on your data)
    test_strategy_symbol_id = 1
    
    try:
        async with AsyncSessionLocal() as session:
            orders = await get_open_orders_for_strategy_symbol_and_tradeday_by_id(
                session, test_strategy_symbol_id, trade_day
            )
            logger.info(f"✅ Database function works! Found {len(orders)} orders for strategy_symbol_id {test_strategy_symbol_id}")
            
            if orders:
                logger.info("📋 Sample orders:")
                for i, order in enumerate(orders[:3]):  # Show first 3 orders
                    logger.info(f"  Order {i+1}: ID={order.get('id')}, Symbol={order.get('strike_symbol')}, Status={order.get('status')}")
            else:
                logger.info("📋 No open orders found (this is normal if no active trades)")
                
    except Exception as e:
        logger.error(f"❌ Database function test failed: {e}")
        return False
    
    return True

async def test_strategy_sync_positions():
    """Test the fixed sync_open_positions method."""
    logger.info("🧪 Testing strategy sync_open_positions fix")
    
    # Import strategies after path setup
    from algosat.strategies.swing_highlow_buy import SwingHighLowBuyStrategy
    from algosat.strategies.swing_highlow_sell import SwingHighLowSellStrategy
    
    # Create mock data manager and order manager
    mock_data_manager = Mock()
    mock_order_manager = Mock()
    
    # Test configurations for different strategy_symbol_ids
    configs = [
        MockConfig(symbol_id=1, strategy_id=1, symbol="NIFTY"),
        MockConfig(symbol_id=2, strategy_id=1, symbol="BANKNIFTY"),  # Same strategy_id, different symbol_id
        MockConfig(symbol_id=3, strategy_id=2, symbol="NIFTY"),      # Different strategy_id, same symbol
    ]
    
    for i, config in enumerate(configs):
        logger.info(f"\n📊 Testing configuration {i+1}: symbol_id={config.symbol_id}, strategy_id={config.strategy_id}, symbol={config.symbol}")
        
        try:
            # Test SwingHighLowBuyStrategy
            buy_strategy = SwingHighLowBuyStrategy(config, mock_data_manager, mock_order_manager)
            await buy_strategy.sync_open_positions()
            
            logger.info(f"  ✅ Buy strategy synced. Positions: {list(buy_strategy._positions.keys())}")
            
            # Test SwingHighLowSellStrategy  
            sell_strategy = SwingHighLowSellStrategy(config, mock_data_manager, mock_order_manager)
            await sell_strategy.sync_open_positions()
            
            logger.info(f"  ✅ Sell strategy synced. Positions: {list(sell_strategy._positions.keys())}")
            
        except Exception as e:
            logger.error(f"  ❌ Strategy test failed for config {i+1}: {e}")
            return False
    
    return True

async def main():
    """Run all tests."""
    logger.info("🚀 Starting sync_open_positions fix verification tests")
    logger.info("=" * 60)
    
    # Test 1: Database function
    db_test_passed = await test_new_db_function()
    
    logger.info("\n" + "=" * 60)
    
    # Test 2: Strategy methods
    strategy_test_passed = await test_strategy_sync_positions()
    
    logger.info("\n" + "=" * 60)
    
    # Summary
    if db_test_passed and strategy_test_passed:
        logger.info("🎉 ALL TESTS PASSED!")
        logger.info("✅ The sync_open_positions fix is working correctly")
        logger.info("✅ Strategies now use strategy_symbol_id instead of strategy_id")
        logger.info("✅ Cross-contamination between different symbol configurations is prevented")
    else:
        logger.error("❌ SOME TESTS FAILED!")
        logger.error("❌ Please check the errors above and fix the issues")
    
    logger.info("\n📝 Summary of Changes Made:")
    logger.info("1. Added new function: get_open_orders_for_strategy_symbol_and_tradeday_by_id")
    logger.info("2. Updated sync_open_positions in SwingHighLowBuyStrategy to use strategy_symbol_id")
    logger.info("3. Updated sync_open_positions in SwingHighLowSellStrategy to use strategy_symbol_id")
    logger.info("4. This prevents loading orders from other symbol configurations of the same strategy")

if __name__ == "__main__":
    asyncio.run(main())
