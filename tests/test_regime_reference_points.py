#!/usr/bin/env python3
"""
Test script to test get_regime_reference_points method with proper DataManager initialization.
Replicates the exact same initialization pattern as main.py and strategy_manager.py
"""

import asyncio
import sys
import os
from datetime import datetime, time

# Add the project root to the path
sys.path.insert(0, '/opt/algosat')

from algosat.core.data_manager import DataManager
from algosat.core.broker_manager import BrokerManager
from algosat.core.db import init_db, seed_default_strategies_and_configs
from algosat.common.strategy_utils import get_regime_reference_points, wait_for_first_candle_completion
from algosat.common.broker_utils import get_ist_datetime
from algosat.common.logger import get_logger

logger = get_logger("test_regime_reference")

async def test_regime_reference_points():
    """Test the get_regime_reference_points method with proper DataManager setup (exact replication of main.py pattern)."""
    
    try:
        logger.info("🚀 Starting regime reference points test...")
        
        # Initialize exactly like main.py
        logger.info("🔄 Initializing BrokerManager...")
        broker_manager = BrokerManager()
        await broker_manager.setup()
        
        logger.info("🔄 Initializing DataManager with BrokerManager...")
        data_manager = DataManager(broker_manager=broker_manager)
        await data_manager.ensure_broker() 
        
        # Initialize database and seed data (like main.py)
        logger.info("🔄 Initializing database schema...")
        await init_db()
        
        logger.info("🔄 Seeding default strategies and configs...")
        await seed_default_strategies_and_configs()
        
        # Setup broker manager (like main.py)
        logger.info("🔄 Setting up BrokerManager...")
        await broker_manager.setup()
        
        logger.info("✅ DataManager and BrokerManager initialized successfully (main.py pattern)")
        
        # Test with different symbol formats to see which one works
        symbols_to_try = [
            # "NIFTY50",           # Simple format
            # "NSE:NIFTY50",       # Exchange prefix
            # "NIFTY 50",          # Space format
            # "NIFTY50-INDEX",     # Index suffix
            "NSE:NIFTY50-INDEX"  # Full format
        ]
        
        current_dt = get_ist_datetime()
        first_candle_time = "09:15"
        entry_minutes = 5
        
        logger.info(f"📊 Test Parameters:")
        logger.info(f"    First Candle Time: {first_candle_time}")
        logger.info(f"    Entry Minutes: {entry_minutes}")
        logger.info(f"    Current DateTime: {current_dt}")
        
        successful_result = None
        successful_symbol = None
        
        # Try different symbol formats
        for symbol in symbols_to_try:
            try:
                logger.info(f"🔄 Trying symbol format: {symbol}")
                
                regime_reference = await get_regime_reference_points(
                    data_manager,
                    symbol,
                    first_candle_time,
                    entry_minutes,
                    current_dt
                )
                
                if regime_reference:
                    logger.info(f"✅ Success with symbol: {symbol}")
                    successful_result = regime_reference
                    successful_symbol = symbol
                    break
                else:
                    logger.warning(f"⚠️ No data for symbol: {symbol}")
                    
            except Exception as e:
                logger.warning(f"❌ Error with symbol {symbol}: {e}")
        
        # Use the successful result for validation
        regime_reference = successful_result
        
        # Display results
        if regime_reference and successful_symbol:
            logger.info(f"✅ Regime reference points retrieved successfully for symbol: {successful_symbol}!")
            logger.info(f"📋 Regime Reference Points:")
            logger.info(f"    Previous Day High: {regime_reference.get('prev_day_high')}")
            logger.info(f"    Previous Day Low: {regime_reference.get('prev_day_low')}")
            logger.info(f"    First Candle High: {regime_reference.get('first_candle_high')}")
            logger.info(f"    First Candle Low: {regime_reference.get('first_candle_low')}")
            logger.info(f"    First Candle Time: {regime_reference.get('first_candle_time')}")
            logger.info(f"    First Candle Interval: {regime_reference.get('first_candle_interval')}")
            logger.info(f"    Trade Day: {regime_reference.get('trade_day')}")
            
            # Validate data types and values
            validation_passed = True
            
            for key in ['prev_day_high', 'prev_day_low', 'first_candle_high', 'first_candle_low']:
                value = regime_reference.get(key)
                if value is None or not isinstance(value, (int, float)) or value <= 0:
                    logger.error(f"❌ Invalid {key}: {value}")
                    validation_passed = False
                else:
                    logger.debug(f"✅ {key} validation passed: {value}")
            
            if validation_passed:
                logger.info("✅ All regime reference point validations passed!")
                
                # Calculate ranges for additional insight
                prev_day_range = regime_reference['prev_day_high'] - regime_reference['prev_day_low']
                first_candle_range = regime_reference['first_candle_high'] - regime_reference['first_candle_low']
                
                logger.info(f"📊 Additional Insights:")
                logger.info(f"    Previous Day Range: {prev_day_range:.2f}")
                logger.info(f"    First Candle Range: {first_candle_range:.2f}")
                
                # Return both success status and the working symbol
                return True, successful_symbol
            else:
                logger.error("❌ Regime reference point validation failed")
                return False, None
        else:
            logger.error("❌ get_regime_reference_points failed for all symbol formats")
            logger.info("💡 This might be due to:")
            logger.info("   - Market being closed")
            logger.info("   - No historical data available for the date")
            logger.info("   - Broker connection issues")
            logger.info("   - Symbol format not supported by the data provider")
            return False, None
            
    except Exception as e:
        logger.error(f"❌ Test failed with error: {e}", exc_info=True)
        return False, None

async def test_with_different_symbols():
    """Test with different symbols to verify robustness (exact replication of main.py pattern)."""
    
    symbols_to_test = [
        "NSE:NIFTY50-INDEX",
        # "BANKNIFTY",
        # "RELIANCE"
    ]
    
    # Initialize exactly like main.py
    broker_manager = BrokerManager()
    data_manager = DataManager(broker_manager=broker_manager)
    
    try:
        await broker_manager.setup()
        logger.info("✅ BrokerManager setup completed for multiple symbols test")
    except Exception as e:
        logger.warning(f"⚠️ Broker setup failed: {e}")
    await data_manager.ensure_broker() 
    
    successful_symbols = []
    
    for symbol in symbols_to_test:
        try:
            logger.info(f"🔄 Testing with symbol: {symbol}")
            
            regime_reference = await get_regime_reference_points(
                data_manager,
                symbol,
                "09:15",
                5,
                get_ist_datetime()
            )
            
            if regime_reference:
                logger.info(f"✅ {symbol}: Success - Prev Day H/L: {regime_reference['prev_day_high']:.2f}/{regime_reference['prev_day_low']:.2f}")
                successful_symbols.append(symbol)
            else:
                logger.warning(f"⚠️ {symbol}: No data retrieved")
                
        except Exception as e:
            logger.error(f"❌ {symbol}: Error - {e}")
    
    return successful_symbols

async def main():
    """Main test function."""
    
    logger.info("🚀 Starting Regime Reference Points Test Suite")
    logger.info("=" * 60)
    
    # Test 1: Basic functionality test
    logger.info("📋 Test 1: Basic Regime Reference Points Test")
    test1_result, working_symbol = await test_regime_reference_points()
    
    logger.info("=" * 60)
    
    # Test 2: Multiple symbols test
    logger.info("📋 Test 2: Multiple Symbols Test")
    successful_symbols = await test_with_different_symbols()
    
    logger.info("=" * 60)
    
    # Summary
    if test1_result:
        logger.info(f"✅ Test 1 PASSED with working symbol: {working_symbol}")
    else:
        logger.error("❌ Test 1 FAILED")
    
    if successful_symbols:
        logger.info(f"✅ Test 2 found {len(successful_symbols)} working symbols: {successful_symbols}")
    else:
        logger.warning("⚠️ Test 2: No symbols worked")
    
    if test1_result or successful_symbols:
        logger.info("✅ Overall test result: SUCCESS (at least one test passed)")
        logger.info("💡 The get_regime_reference_points method is working correctly!")
        return True
    else:
        logger.error("❌ Overall test result: FAILURE (all tests failed)")
        logger.info("💡 This might be due to market being closed or data provider issues")
        return False

async def test_with_different_symbols():
    """Test with different symbols to verify robustness."""
    
    symbols_to_test = [
        "NSE:NIFTY50-INDEX",
        # "NSE:BANKNIFTY-INDEX",
        # "NSE:RELIANCE-EQ"
    ]
    
    # data_manager = DataManager()
    broker_manager = BrokerManager()
    data_manager = DataManager(broker_manager=broker_manager)
    
    try:
        await broker_manager.setup()
        logger.info("✅ BrokerManager setup completed for different symbols test")
    except Exception as e:
        logger.warning(f"⚠️ Broker setup failed: {e}")
    
    for symbol in symbols_to_test:
        try:
            logger.info(f"🔄 Testing with symbol: {symbol}")
            
            regime_reference = await get_regime_reference_points(
                data_manager,
                symbol,
                "09:15",
                5,
                get_ist_datetime()
            )
            
            if regime_reference:
                logger.info(f"✅ {symbol}: Success - Prev Day H/L: {regime_reference['prev_day_high']:.2f}/{regime_reference['prev_day_low']:.2f}")
            else:
                logger.warning(f"⚠️ {symbol}: No data retrieved")
                
        except Exception as e:
            logger.error(f"❌ {symbol}: Error - {e}")

async def main():
    """Main test function."""
    
    logger.info("🚀 Starting Regime Reference Points Test Suite")
    logger.info("=" * 60)
    
    # Test 1: Basic functionality test
    logger.info("📋 Test 1: Basic Regime Reference Points Test")
    test1_result = await test_regime_reference_points()
    
    logger.info("=" * 60)
    
    # Test 2: Multiple symbols test
    logger.info("📋 Test 2: Multiple Symbols Test")
    await test_with_different_symbols()
    
    logger.info("=" * 60)
    
    if test1_result:
        logger.info("✅ All tests completed successfully!")
        return True
    else:
        logger.error("❌ Some tests failed!")
        return False

if __name__ == "__main__":
    async def run_tests():
        success = await main()
        sys.exit(0 if success else 1)
    
    # Run the test
    asyncio.run(run_tests())
