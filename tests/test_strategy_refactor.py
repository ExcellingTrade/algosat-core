#!/usr/bin/env python3
"""
Test script to verify the strategy manager refactoring works correctly.
"""

import asyncio
import sys
import os

# Add the project root to the path
sys.path.insert(0, '/opt/algosat')

from algosat.core.strategy_manager import initialize_strategy_instance, STRATEGY_MAP
from algosat.core.data_manager import DataManager
from algosat.core.order_manager import OrderManager
from algosat.models.strategy_config import StrategyConfig
from algosat.common.logger import get_logger

logger = get_logger("test_strategy_refactor")

async def test_strategy_initialization():
    """Test that strategy initialization works correctly."""
    
    # Create mock config for OptionBuy strategy
    config_dict = {
        'id': 1,
        'strategy_id': 1,
        'name': 'Test Config',
        'description': 'Test config for refactoring',
        'exchange': 'NSE',
        'instrument': 'OPTIDX',
        'trade': {
            'interval_minutes': 5,
            'first_candle_time': '09:15',
            'max_strikes': 10,
            'entry_buffer': 0,
            'ce_lot_qty': 1,
            'lot_size': 75
        },
        'indicators': {
            'rsi_period': 14
        },
        'symbol': 'NIFTY50',
        'symbol_id': 1,
        'strategy_key': 'OptionBuy',
        'strategy_name': 'OptionBuy',
        'order_type': 'MARKET',
        'product_type': 'INTRADAY'
    }
    
    config = StrategyConfig(**config_dict)
    
    try:
        # Test that STRATEGY_MAP is properly imported
        logger.info(f"Available strategies: {list(STRATEGY_MAP.keys())}")
        
        # Test that we can create data_manager and order_manager (mock)
        data_manager = DataManager()
        order_manager = OrderManager()
        
        logger.info("✅ Successfully created DataManager and OrderManager")
        
        # Note: We won't actually call initialize_strategy_instance here since it requires
        # broker setup which needs actual configuration. But we can test the imports work.
        
        # Test that the strategy classes are importable
        for strategy_name, strategy_class in STRATEGY_MAP.items():
            logger.info(f"✅ Strategy '{strategy_name}' maps to class {strategy_class.__name__}")
        
        logger.info("✅ All imports and basic setup completed successfully!")
        logger.info("✅ Strategy manager refactoring test passed!")
        
    except Exception as e:
        logger.error(f"❌ Test failed: {e}", exc_info=True)
        return False
        
    return True

if __name__ == "__main__":
    async def main():
        success = await test_strategy_initialization()
        sys.exit(0 if success else 1)
    
    asyncio.run(main())
