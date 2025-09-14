#!/usr/bin/env python3
"""
Test Angel broker margin check functionality.
"""

import asyncio
import sys
import os

# Add the project root to the path
sys.path.insert(0, '/opt/algosat')

async def test_angel_margin_check():
    """Test Angel broker margin check with the given symbol and token."""
    try:
        print("🚀 Testing Angel Broker Margin Check")
        print("=" * 60)
        
        # Import required modules
        from algosat.brokers.angel import AngelWrapper
        from algosat.core.order_request import OrderRequest, Side, OrderType
        
        # Create Angel broker instance
        angel_broker = AngelWrapper()
        await angel_broker.login()  # Initialize with credentials from DB
        
        print("✅ Angel broker authenticated successfully")
        
        # Test symbol and token (from previous conversion test)
        symbol = 'NIFTY16SEP2524950CE'
        instrument_token = '44662'
        
        print(f"\n🔄 Testing Margin Check for:")
        print(f"Symbol: {symbol}")
        print(f"Token: {instrument_token}")
        print("-" * 60)
        
        # Create test order request
        order_request = OrderRequest(
            symbol=symbol,
            side=Side.BUY,
            quantity=50000,
            order_type=OrderType.MARKET,
            price=0.0,
            extra={'instrument_token': instrument_token}
        )
        
        print(f"📋 Order Request Details:")
        print(f"  Symbol: {order_request.symbol}")
        print(f"  Side: {order_request.side.value}")
        print(f"  Quantity: {order_request.quantity}")
        print(f"  Order Type: {order_request.order_type.value}")
        print(f"  Instrument Token: {order_request.extra.get('instrument_token')}")
        
        # Test margin check
        print(f"\n💰 Checking margin availability...")
        
        margin_available = await angel_broker.check_margin_availability(order_request)
        
        print(f"\n📊 Margin Check Result:")
        if margin_available:
            print("✅ Sufficient margin available")
        else:
            print("❌ Insufficient margin")
        
        print(f"Result: {margin_available}")
        
        # Test with multiple orders
        print(f"\n🔄 Testing with multiple orders...")
        
        order_request_2 = OrderRequest(
            symbol=symbol,
            side=Side.SELL,
            quantity=25000,
            order_type=OrderType.LIMIT,
            price=100.0,
            extra={'instrument_token': instrument_token}
        )
        
        margin_available_multi = await angel_broker.check_margin_availability(order_request)
        
        print(f"📊 Multi-Order Margin Check Result:")
        if margin_available_multi:
            print("✅ Sufficient margin available for multiple orders")
        else:
            print("❌ Insufficient margin for multiple orders")
        
        print(f"Result: {margin_available_multi}")
        
    except Exception as e:
        print(f"❌ Error during margin check test: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_angel_margin_check())