#!/usr/bin/env python3
"""
Test script for Angel cancel_order and exit_order methods.
"""

import sys
import os
sys.path.append('/opt/algosat')

import asyncio
from algosat.brokers.angel import AngelWrapper
from algosat.core.order_request import OrderRequest, OrderType, Side

async def test_angel_cancel_and_exit():
    """Test Angel cancel_order and exit_order methods."""
    
    print("🔍 Testing Angel Cancel Order and Exit Order Methods")
    print("=" * 60)
    
    # Initialize Angel broker
    angel = AngelWrapper("angel")
    
    # Test login first
    print("🔐 Testing Angel login...")
    try:
        login_result = await angel.login()
        if login_result:
            print("✅ Angel login successful")
        else:
            print("❌ Angel login failed")
            return
    except Exception as e:
        print(f"❌ Angel login error: {e}")
        return
    
    print("\n📋 Testing cancel_order method...")
    print("-" * 40)
    
    # Test cancel_order with a mock order ID
    test_order_id = "test_order_123"
    try:
        cancel_result = await angel.cancel_order(
            broker_order_id=test_order_id,
            symbol="NIFTY16SEP2524950CE",
            product_type="INTRADAY",
            variety="NORMAL"
        )
        print(f"📤 Cancel order result: {cancel_result}")
        
        if cancel_result.get("status"):
            print("✅ Cancel order method executed successfully")
        else:
            print(f"⚠️  Cancel order returned false status: {cancel_result.get('message', 'Unknown error')}")
            
    except Exception as e:
        print(f"❌ Cancel order test failed: {e}")
    
    print("\n📋 Testing exit_order method...")
    print("-" * 40)
    
    # Test exit_order - this will check positions and try to place opposite order
    try:
        # First, let's get positions to see if there are any
        positions = await angel.get_positions()
        print(f"📊 Current positions count: {len(positions) if positions else 0}")
        
        if positions:
            print("🔍 Sample positions:")
            for i, pos in enumerate(positions[:3]):  # Show first 3 positions
                symbol = pos.get('tradingsymbol', 'N/A')
                netqty = pos.get('netqty', '0')
                product = pos.get('producttype', 'N/A')
                print(f"  {i+1}. Symbol: {symbol}, NetQty: {netqty}, Product: {product}")
        
        # Test exit_order with a mock scenario
        exit_result = await angel.exit_order(
            broker_order_id="test_order_456",
            symbol="NIFTY16SEP2524950CE",  # Use one of the symbols from real data
            product_type="INTRADAY",
            exit_reason="Test exit",
            side="BUY"  # Original side was BUY, so exit will be SELL
        )
        
        print(f"📤 Exit order result: {exit_result}")
        
        if exit_result.get("status"):
            print("✅ Exit order method executed successfully")
        else:
            print(f"⚠️  Exit order returned false status: {exit_result.get('message', 'Unknown error')}")
            
    except Exception as e:
        print(f"❌ Exit order test failed: {e}")
    
    print("\n" + "=" * 60)
    print("🎯 Angel cancel_order and exit_order methods testing completed!")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(test_angel_cancel_and_exit())