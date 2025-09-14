#!/usr/bin/env python3
"""
Test database connectivity and expiry_date column availability
"""

import sys
import os
sys.path.append('/opt/algosat')

import asyncio
from datetime import datetime

async def test_database_connectivity():
    """Test if database connection works and expiry_date column exists"""
    
    print("=== Database Connectivity Test ===")
    
    try:
        # Test database connection and schema
        from algosat.core.db import AsyncSessionLocal, get_order_by_id
        from algosat.core.dbschema import orders
        
        print("✅ Database imports successful")
        
        # Test connection
        async with AsyncSessionLocal() as session:
            print("✅ Database connection established")
            
            # Check if expiry_date column exists in orders table
            from sqlalchemy import inspect, text
            
            # Get table columns
            inspector = inspect(session.bind)
            columns = inspector.get_columns('orders')
            
            column_names = [col['name'] for col in columns]
            if 'expiry_date' in column_names:
                print("✅ expiry_date column exists in orders table")
            else:
                print("❌ expiry_date column missing from orders table")
                print(f"Available columns: {column_names}")
            
            # Test a simple query
            result = await session.execute(text("SELECT COUNT(*) FROM orders"))
            count = result.scalar()
            print(f"✅ Orders table accessible, contains {count} records")
            
    except Exception as e:
        print(f"❌ Database connectivity error: {e}")
        import traceback
        traceback.print_exc()

async def test_order_manager():
    """Test OrderManager functionality with expiry_date"""
    
    print("\n=== OrderManager Test ===")
    
    try:
        from algosat.core.order_manager import OrderManager
        from algosat.core.order_request import OrderPayload, Side, OrderType
        from algosat.core.signal import TradeSignal, SignalType
        
        print("✅ OrderManager imports successful")
        
        # Create a mock OrderPayload with expiry_date
        test_expiry = datetime(2025, 7, 24, 15, 30)
        
        signal = TradeSignal(
            symbol="NSE:NIFTY2572423400CE",
            side=Side.BUY,
            signal_type=SignalType.ENTRY,
            price=100.0,
            expiry_date=test_expiry.isoformat()
        )
        
        # Test the extra data structure
        extra_data = {
            "expiry_date": test_expiry,
            "lot_qty": 25,
            "entry_spot_price": 23400
        }
        
        print(f"✅ Extra data with expiry_date created: {extra_data['expiry_date']}")
        
    except Exception as e:
        print(f"❌ OrderManager test error: {e}")
        import traceback
        traceback.print_exc()

async def test_strategy_integration():
    """Test strategy integration with expiry functionality"""
    
    print("\n=== Strategy Integration Test ===")
    
    try:
        from algosat.strategies.swing_highlow_buy import SwingHighLowBuyStrategy
        from algosat.common.swing_utils import get_atm_strike_symbol
        
        print("✅ Strategy imports successful")
        
        # Test configuration
        test_config = {
            "entry": {
                "atm_strike_offset_CE": 0,
                "step_ce": 50
            },
            "expiry_exit": {
                "enabled": True,
                "expiry_exit_time": "15:15"
            }
        }
        
        # Test get_atm_strike_symbol
        symbol_str, expiry_date = get_atm_strike_symbol(
            "NIFTY50", 23400, "CE", test_config
        )
        
        print(f"✅ get_atm_strike_symbol working: {symbol_str}, {expiry_date}")
        
        # Test order row for evaluate_exit
        order_row = {
            "id": 123,
            "expiry_date": expiry_date.isoformat(),
            "strike_symbol": symbol_str
        }
        
        # Mock evaluate_exit logic (extracted from strategy)
        from algosat.core.time_utils import get_ist_datetime
        import pandas as pd
        
        current_datetime = get_ist_datetime()
        expiry_dt = pd.to_datetime(order_row["expiry_date"])
        
        print(f"✅ Exit logic test data prepared: current={current_datetime}, expiry={expiry_dt}")
        
    except Exception as e:
        print(f"❌ Strategy integration test error: {e}")
        import traceback
        traceback.print_exc()

async def main():
    await test_database_connectivity()
    await test_order_manager()
    await test_strategy_integration()
    print("\n=== All Tests Complete ===")

if __name__ == "__main__":
    asyncio.run(main())
