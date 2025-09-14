#!/usr/bin/env python3

import sys
import os
import asyncio
sys.path.append('/opt/algosat')

from algosat.core.db import get_trades_for_symbol, AsyncSessionLocal

async def test_trades_with_smart_levels():
    print("=== Testing get_trades_for_symbol with smart_level_enabled ===")
    
    async with AsyncSessionLocal() as session:
        try:
            # Test with a known strategy symbol ID - you can adjust this
            symbol_id = 14  # Use symbol ID 14 (NIFTY50 with Smart Levels: True and has orders)
            
            # Get trades for this symbol
            trades = await get_trades_for_symbol(session, symbol_id, limit=5)
            
            print(f"Found {len(trades)} trades for symbol_id {symbol_id}")
            
            for i, trade in enumerate(trades):
                print(f"\n--- Trade {i+1} ---")
                print(f"ID: {trade.get('id')}")
                print(f"Strike Symbol: {trade.get('strike_symbol')}")
                print(f"Status: {trade.get('status')}")
                print(f"Smart Level Enabled: {trade.get('smart_level_enabled')}")
                print(f"Entry Price: {trade.get('entry_price')}")
                print(f"PnL: {trade.get('pnl')}")
                print(f"Signal Time: {trade.get('signal_time')}")
                
                # Check if smart_level_enabled field exists
                if 'smart_level_enabled' in trade:
                    print(f"✅ smart_level_enabled field found: {trade['smart_level_enabled']}")
                else:
                    print("❌ smart_level_enabled field NOT found")
            
            return len(trades) > 0
            
        except Exception as e:
            print(f"Error testing trades: {e}")
            import traceback
            traceback.print_exc()
            return False

if __name__ == "__main__":
    success = asyncio.run(test_trades_with_smart_levels())
    if success:
        print("\n✅ Test completed successfully")
    else:
        print("\n❌ Test failed")
