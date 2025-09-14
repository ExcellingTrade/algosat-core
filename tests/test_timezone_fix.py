#!/usr/bin/env python3
"""
Test script to verify the timezone fix for today's P&L calculation.
"""

import asyncio
import sys
import os
from datetime import datetime, date

# Add the algosat module to the path
sys.path.insert(0, '/opt/algosat')

from algosat.core.db import AsyncSessionLocal, get_orders_pnl_stats_by_symbol_id
from algosat.core.time_utils import get_ist_today, get_ist_now, to_ist

async def test_timezone_fix():
    """Test the timezone fix for P&L calculation"""
    print("Testing timezone fix for today's P&L calculation...")
    
    # Show current time info
    print(f"Current IST time: {get_ist_now()}")
    print(f"Current IST date: {get_ist_today()}")
    
    # Test with a sample strategy_symbol_id (you can change this)
    strategy_symbol_id = 4
    
    try:
        async with AsyncSessionLocal() as session:
            # Test the fixed function
            stats = await get_orders_pnl_stats_by_symbol_id(session, strategy_symbol_id=strategy_symbol_id)
            
            print(f"\nP&L Stats for strategy_symbol_id {strategy_symbol_id}:")
            print(f"Overall P&L: ₹{stats['overall_pnl']}")
            print(f"Overall Trade Count: {stats['overall_trade_count']}")
            print(f"Today P&L: ₹{stats['today_pnl']}")
            print(f"Today Trade Count: {stats['today_trade_count']}")
            
            # Test with a specific date to ensure it works
            test_date = date(2025, 1, 7)  # Use a specific date
            stats_date = await get_orders_pnl_stats_by_symbol_id(session, strategy_symbol_id=strategy_symbol_id, date=test_date)
            
            print(f"\nP&L Stats for strategy_symbol_id {strategy_symbol_id} on {test_date}:")
            print(f"Overall P&L: ₹{stats_date['overall_pnl']}")
            print(f"Overall Trade Count: {stats_date['overall_trade_count']}")
            print(f"Date-specific P&L: ₹{stats_date['today_pnl']}")
            print(f"Date-specific Trade Count: {stats_date['today_trade_count']}")
            
            print("\n✅ Test completed successfully!")
            
    except Exception as e:
        print(f"❌ Error during test: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_timezone_fix())
