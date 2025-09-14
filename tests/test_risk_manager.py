#!/usr/bin/env python3
"""
Test script for the new Risk Management system.
This script demonstrates the emergency stop functionality.
"""

import asyncio
import sys
import os

# Add the project root to the Python path
sys.path.insert(0, '/opt/algosat')

from algosat.core.db import disable_strategy
from algosat.core.strategy_manager import RiskManager
from algosat.core.order_manager import OrderManager
from algosat.core.data_manager import DataManager
from algosat.core.broker_manager import BrokerManager
from algosat.common.logger import get_logger

logger = get_logger("test_risk_manager")

async def test_risk_manager():
    """Test the risk management system."""
    
    logger.info("🧪 Testing Risk Management System")
    
    try:
        # Initialize required components in proper order
        broker_manager = BrokerManager()
        data_manager = DataManager()
        order_manager = OrderManager(broker_manager)
        
        # Initialize RiskManager
        risk_manager = RiskManager(order_manager)
        
        logger.info("✓ RiskManager initialized successfully")
        
        # Test 1: Check broker risk limits
        logger.info("📊 Testing broker risk limit check...")
        risk_exceeded = await risk_manager.check_broker_risk_limits()
        
        if risk_exceeded:
            logger.warning("⚠️ Risk limits exceeded - emergency stop would be triggered")
        else:
            logger.info("✓ All brokers within risk limits")
        
        # Test 2: Emergency stop status
        logger.info(f"🚨 Emergency stop status: {risk_manager.is_emergency_stop_active()}")
        
        # Test 3: Simulate emergency stop (commented out for safety)
        # logger.info("🧪 Testing emergency stop simulation (dry run)...")
        # await risk_manager.emergency_stop_all_strategies()
        
        # Test 4: Check what active strategies exist
        logger.info("📋 Checking current active strategies...")
        from algosat.core.db import get_active_strategy_symbols_with_configs, AsyncSessionLocal
        async with AsyncSessionLocal() as session:
            active_symbols = await get_active_strategy_symbols_with_configs(session)
            unique_strategy_ids = set(row.strategy_id for row in active_symbols)
            logger.info(f"📊 Found {len(active_symbols)} active symbols from {len(unique_strategy_ids)} strategies")
            if unique_strategy_ids:
                logger.info(f"📊 Strategy IDs: {list(unique_strategy_ids)}")
            logger.critical(f"🚨 Disabling {len(unique_strategy_ids)} strategies: {list(unique_strategy_ids)}")
                
            # 2. Disable all active strategies in database
            for strategy_id in unique_strategy_ids:
                try:
                    await disable_strategy(session, strategy_id)
                    logger.info(f"🚨 Disabled strategy ID: {strategy_id}")
                except Exception as e:
                    logger.error(f"Error disabling strategy {strategy_id}: {e}")
            
            # 3. Commit the strategy disables
            await session.commit()
        logger.info("✅ Risk Manager test completed successfully")
        
    except Exception as e:
        logger.error(f"❌ Test failed: {e}", exc_info=True)

async def test_broker_pnl_calculation():
    """Test the P&L calculation for brokers."""
    
    logger.info("💰 Testing broker P&L calculation")
    
    try:
        broker_manager = BrokerManager()
        order_manager = OrderManager(broker_manager)
        risk_manager = RiskManager(order_manager)
        
        from algosat.core.db import AsyncSessionLocal
        
        async with AsyncSessionLocal() as session:
            # Test P&L calculation for each broker
            brokers = ['fyers', 'angel', 'zerodha']
            
            for broker in brokers:
                pnl = await risk_manager._calculate_broker_pnl(session, broker)
                logger.info(f"📈 Broker {broker} P&L: {pnl}")
        
        logger.info("✅ P&L calculation test completed")
        
    except Exception as e:
        logger.error(f"❌ P&L calculation test failed: {e}", exc_info=True)

async def main():
    """Main test function."""
    
    logger.info("🚀 Starting Risk Manager Tests")
    
    await test_risk_manager()
    await test_broker_pnl_calculation()
    
    logger.info("🏁 All tests completed")

if __name__ == "__main__":
    asyncio.run(main())
