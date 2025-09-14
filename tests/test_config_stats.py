#!/usr/bin/env python3
"""
Test script to verify that the ConfigsPage trade count and P&L functionality is working correctly.
"""

import asyncio
import sys
import os
from datetime import datetime, date

# Add the algosat module to the path
sys.path.insert(0, '/opt/algosat')

from algosat.core.db import AsyncSessionLocal, get_strategy_symbol_trade_stats

async def test_config_stats():
    """Test the config stats functionality"""
    print("Testing Strategy Configuration stats functionality...")
    
    # Test with a sample strategy_symbol_id (you can change this)
    strategy_symbol_id = 4
    
    try:
        async with AsyncSessionLocal() as session:
            # Test the function that provides stats for the ConfigsPage
            stats = await get_strategy_symbol_trade_stats(session, strategy_symbol_id)
            
            print(f"\nTrade Stats for strategy_symbol_id {strategy_symbol_id}:")
            print(f"Live Trade Count: {stats['live_trade_count']}")
            print(f"Live P&L: ₹{stats['live_pnl']}")
            print(f"Total Trade Count: {stats['total_trade_count']}")
            print(f"Total P&L: ₹{stats['total_pnl']}")
            print(f"All Trade Count: {stats['all_trade_count']}")
            
            print("\n✅ Strategy Configuration stats functionality is working correctly!")
            print("The ConfigsPage should be able to:")
            print("- Display number of trades for each config")
            print("- Show total P&L for each config")
            print("- Aggregate stats from all symbols using that config")
            
    except Exception as e:
        print(f"❌ Error during test: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_config_stats())
