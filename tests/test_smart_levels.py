#!/usr/bin/env python3
"""
Test script to verify smart levels integration with SwingHighLowBuyStrategy
"""

import asyncio
import sys
import os

# Add the project root to Python path
sys.path.insert(0, '/opt/algosat')

from algosat.core.db import AsyncSessionLocal, get_smart_levels_for_symbol, get_smart_levels_for_strategy_symbol_id
from algosat.common.logger import get_logger

logger = get_logger("test_smart_levels")

async def test_smart_levels_db_methods():
    """Test the database methods for smart levels"""
    
    print("🧪 Testing Smart Levels Database Methods")
    print("=" * 50)
    
    try:
        async with AsyncSessionLocal() as session:
            
            # Test 1: Get smart levels by symbol name
            print("\n📊 Test 1: Get smart levels by symbol name")
            nifty_levels = await get_smart_levels_for_symbol(session, "NIFTY50")
            print(f"Found {len(nifty_levels)} smart levels for NIFTY50:")
            for level in nifty_levels:
                print(f"  - {level['name']}: entry={level['entry_level']}, strategy_id={level['strategy_id']}")
            
            banknifty_levels = await get_smart_levels_for_symbol(session, "NIFTYBANK")
            print(f"Found {len(banknifty_levels)} smart levels for NIFTYBANK:")
            for level in banknifty_levels:
                print(f"  - {level['name']}: entry={level['entry_level']}, strategy_id={level['strategy_id']}")
            
            # Test 2: Get smart levels by strategy_symbol_id
            print("\n📊 Test 2: Get smart levels by strategy_symbol_id")
            
            # Test with known strategy_symbol_ids from our database query
            test_symbol_ids = [14, 10]  # NIFTY50 and NIFTYBANK from earlier query
            
            for symbol_id in test_symbol_ids:
                levels = await get_smart_levels_for_strategy_symbol_id(session, symbol_id)
                print(f"Found {len(levels)} smart levels for strategy_symbol_id={symbol_id}:")
                for level in levels:
                    print(f"  - {level['name']}: entry={level['entry_level']}")
            
            # Test 3: Get smart levels with strategy_id filter
            print("\n📊 Test 3: Get smart levels with strategy_id filter")
            swing_strategy_id = 3  # SwingHighLowBuy strategy ID
            
            nifty_swing_levels = await get_smart_levels_for_symbol(session, "NIFTY50", swing_strategy_id)
            print(f"Found {len(nifty_swing_levels)} smart levels for NIFTY50 with strategy_id={swing_strategy_id}:")
            for level in nifty_swing_levels:
                print(f"  - {level['name']}: entry={level['entry_level']}")
                print(f"    CE lots: {level['remaining_lot_ce']}, PE lots: {level['remaining_lot_pe']}")
                print(f"    CE buy enabled: {level['ce_buy_enabled']}, PE buy enabled: {level['pe_buy_enabled']}")
            
    except Exception as e:
        logger.error(f"Error in test: {e}", exc_info=True)
        return False
    
    print("\n✅ Smart Levels Database Methods Test Completed Successfully!")
    return True

async def test_strategy_config_integration():
    """Test if the StrategyConfig has the enable_smart_levels field"""
    
    print("\n🧪 Testing Strategy Config Integration")
    print("=" * 50)
    
    try:
        from algosat.models.strategy_config import StrategyConfig
        
        # Test StrategyConfig creation with enable_smart_levels
        config_data = {
            'id': 1,
            'strategy_id': 3,
            'name': 'Test Config',
            'exchange': 'NSE',
            'trade': {},
            'indicators': {},
            'symbol': 'NIFTY50',
            'symbol_id': 14,
            'enable_smart_levels': True,
            'strategy_key': 'SwingHighLowBuy'
        }
        
        config = StrategyConfig(**config_data)
        print(f"✅ StrategyConfig created successfully")
        print(f"   - enable_smart_levels: {config.enable_smart_levels}")
        print(f"   - symbol_id: {config.symbol_id}")
        print(f"   - symbol: {config.symbol}")
        
        return True
        
    except Exception as e:
        logger.error(f"Error in strategy config test: {e}", exc_info=True)
        return False

async def main():
    """Run all tests"""
    
    print("🚀 Starting Smart Levels Integration Tests")
    print("=" * 60)
    
    # Test 1: Database methods
    db_test_passed = await test_smart_levels_db_methods()
    
    # Test 2: Strategy config integration
    config_test_passed = await test_strategy_config_integration()
    
    print("\n" + "=" * 60)
    print("📋 Test Results Summary:")
    print(f"   Database Methods: {'✅ PASSED' if db_test_passed else '❌ FAILED'}")
    print(f"   Strategy Config: {'✅ PASSED' if config_test_passed else '❌ FAILED'}")
    
    if db_test_passed and config_test_passed:
        print("\n🎉 All tests passed! Smart Levels integration is ready.")
        return 0
    else:
        print("\n💥 Some tests failed. Please check the errors above.")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
