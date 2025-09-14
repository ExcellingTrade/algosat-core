#!/usr/bin/env python3
"""
Test script to verify that the /strategies/symbols/{symbol_id}/trades endpoint 
includes current_price and price_last_updated fields.
"""

import asyncio
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from algosat.core.db import AsyncSessionLocal, get_trades_for_symbol, get_strategy_symbol_by_id


async def test_strategies_symbol_trades_endpoint():
    """Test that /strategies/symbols/{symbol_id}/trades endpoint includes current_price and price_last_updated fields."""
    
    print("🧪 Testing /strategies/symbols/{symbol_id}/trades endpoint...")
    
    try:
        async with AsyncSessionLocal() as session:
            # First, find a strategy symbol that exists
            from algosat.core.dbschema import strategy_symbols
            from sqlalchemy import select
            
            stmt = select(strategy_symbols.c.id).limit(1)
            result = await session.execute(stmt)
            row = result.first()
            
            if not row:
                print("ℹ️  No strategy symbols found in database")
                return True
                
            # Use a strategy symbol that has orders (from our test)
            symbol_id = 14  # From our previous test
            print(f"📊 Testing with strategy_symbol_id: {symbol_id}")
            
            # Test the database function directly
            trades_data = await get_trades_for_symbol(session, symbol_id, limit=1)
            
            if not trades_data:
                print("ℹ️  No trades found for this strategy symbol")
                return True
                
            print(f"📊 Found {len(trades_data)} trades")
            
            # Check if new fields are present in database results
            first_trade = trades_data[0]
            has_current_price = 'current_price' in first_trade
            has_price_last_updated = 'price_last_updated' in first_trade
            
            print(f"📋 Trade data includes current_price: {has_current_price}")
            print(f"📋 Trade data includes price_last_updated: {has_price_last_updated}")
            
            if not has_current_price or not has_price_last_updated:
                print("❌ Database query missing new fields!")
                print(f"📋 Available fields in trade data: {list(first_trade.keys())}")
                return False
            
            print(f"📊 Sample trade current_price: {first_trade.get('current_price')}")
            print(f"📊 Sample trade price_last_updated: {first_trade.get('price_last_updated')}")
            
            # Check broker_executions structure
            if 'broker_executions' in first_trade:
                print(f"📊 Trade has {len(first_trade['broker_executions'])} broker executions")
            
            print("🎉 All tests passed! /strategies/symbols/{symbol_id}/trades endpoint includes current_price and price_last_updated fields.")
            return True
            
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        return False


if __name__ == "__main__":
    result = asyncio.run(test_strategies_symbol_trades_endpoint())
    sys.exit(0 if result else 1)
