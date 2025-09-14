#!/usr/bin/env python3
"""
Test script to verify the new strategy manager functionality 
that fetches active symbols with their configs.
"""

import asyncio
import sys
import os

# Add the project root to Python path
sys.path.insert(0, os.path.abspath('.'))

from algosat.core.db import get_active_strategy_symbols_with_configs, AsyncSessionLocal
from algosat.core.dbschema import strategies, strategy_configs, strategy_symbols
from algosat.models.strategy_config import StrategyConfig


async def test_fetch_active_symbols():
    """Test fetching active symbols with their strategy and config information."""
    print("🔍 Testing get_active_strategy_symbols_with_configs...")
    
    try:
        async with AsyncSessionLocal() as session:
            # Fetch active symbols
            active_symbols = await get_active_strategy_symbols_with_configs(session)
            
            print(f"📊 Found {len(active_symbols)} active symbols:")
            
            for row in active_symbols:
                print(f"  📍 Symbol: {row.symbol}")
                print(f"     ├─ Symbol ID: {row.symbol_id}")
                print(f"     ├─ Strategy: {row.strategy_name} (ID: {row.strategy_id}, Key: {row.strategy_key})")
                print(f"     ├─ Config: {row.config_name} (ID: {row.config_id})")
                print(f"     ├─ Exchange: {row.exchange}")
                print(f"     ├─ Product Type: {row.product_type}")
                print(f"     ├─ Order Type: {row.order_type}")
                print(f"     ├─ Status: {row.symbol_status}")
                print(f"     ├─ Trade Config: {row.trade_config}")
                print(f"     └─ Indicators: {row.indicators_config}")
                print()
                
                # Test creating StrategyConfig from the row data
                try:
                    config_dict = {
                        'id': row.config_id,
                        'strategy_id': row.strategy_id,
                        'name': row.config_name,
                        'description': row.config_description,
                        'exchange': row.exchange,
                        'instrument': row.instrument,
                        'trade': row.trade_config,
                        'indicators': row.indicators_config,
                        'symbol': row.symbol,
                        'symbol_id': row.symbol_id,
                        'strategy_key': row.strategy_key,
                        'strategy_name': row.strategy_name,
                        'order_type': row.order_type,
                        'product_type': row.product_type
                    }
                    config = StrategyConfig(**config_dict)
                    print(f"     ✅ Successfully created StrategyConfig for {row.symbol}")
                except Exception as e:
                    print(f"     ❌ Failed to create StrategyConfig for {row.symbol}: {e}")
                    
            if len(active_symbols) == 0:
                print("⚠️  No active symbols found. This could mean:")
                print("   - No strategies are enabled")
                print("   - No symbols have been added to strategies")
                print("   - All symbols have status != 'active'")
                
    except Exception as e:
        print(f"❌ Error fetching active symbols: {e}")
        import traceback
        traceback.print_exc()


async def main():
    """Main test function."""
    print("🚀 Starting strategy manager tests...")
    print("=" * 50)
    
    await test_fetch_active_symbols()
    
    print("=" * 50)
    print("✅ Tests completed!")


if __name__ == "__main__":
    asyncio.run(main())
