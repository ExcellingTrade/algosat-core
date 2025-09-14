#!/usr/bin/env python3
"""
Test Angel broker place_order functionality.
"""

import asyncio
import sys
import os

# Add the project root to the path
sys.path.insert(0, '/opt/algosat')

async def test_angel_place_order():
    """Test Angel broker place_order method."""
    try:
        print("🚀 Testing Angel Broker Place Order")
        print("=" * 60)
        
        # Import required modules
        from algosat.brokers.angel import AngelWrapper
        from algosat.core.order_request import OrderRequest, Side, OrderType, ProductType
        
        # Create Angel broker instance
        angel_broker = AngelWrapper()
        await angel_broker.login()  # Initialize with credentials from DB
        
        print("✅ Angel broker authenticated successfully")
        
        # Test symbol and token (from previous tests)
        symbol = 'NIFTY16SEP2524950CE'
        instrument_token = '44662'
        
        print(f"\n🔄 Testing Place Order for:")
        print(f"Symbol: {symbol}")
        print(f"Token: {instrument_token}")
        print("-" * 60)
        
        # Create test order request (using more realistic strategy-based values)
        # Mimicking what build_order_request() in broker_manager would set for OPTION_STRATEGY
        entry_price = 220.0
        trigger_price_diff = 5.0  # Typical trigger price difference from config
        trigger_price = entry_price - trigger_price_diff  # For BUY orders: entry_price - diff
        
        order_request = OrderRequest(
            symbol=symbol,
            side=Side.BUY,
            quantity=150,
            order_type=OrderType.MARKET,  # Maps to SL in Angel
            product_type=ProductType.OPTION_STRATEGY,  # Strategy-specific product type
            price=entry_price,  # Entry price
            trigger_price=trigger_price,  # Calculated trigger price (145.0)
            exchange="NFO",
            extra={
                'instrument_token': instrument_token,
                'strategy_name': 'OptionBuy',  # Typical strategy
                'trigger_price_diff': trigger_price_diff,
                'entry_price': entry_price,
                'lot_size': 25,  # Typical NIFTY lot size
                'lot_qty': 6  # 6 lots = 150 quantity
            }
        )
        
        print(f"📋 Order Request Details:")
        print(f"  Symbol: {order_request.symbol}")
        print(f"  Side: {order_request.side.value}")
        print(f"  Quantity: {order_request.quantity}")
        print(f"  Order Type: {order_request.order_type.value}")
        print(f"  Product Type: {order_request.product_type.value}")
        print(f"  Price (Entry): {order_request.price}")
        print(f"  Trigger Price: {order_request.trigger_price}")
        print(f"  Exchange: {order_request.exchange}")
        print(f"  Instrument Token: {order_request.extra.get('instrument_token')}")
        print(f"  Strategy Name: {order_request.extra.get('strategy_name')}")
        print(f"  Trigger Price Diff: {order_request.extra.get('trigger_price_diff')}")
        
        # Test to_angel_dict conversion
        print(f"\n🔄 Testing Angel format conversion...")
        angel_dict = order_request.to_angel_dict()
        print(f"📊 Angel Format:")
        for key, value in angel_dict.items():
            print(f"  {key}: {value}")
        
        # Test place_order (Today is holiday, so safe to test)
        print(f"\n💰 Testing place_order...")
        print("📝 Holiday today - safe to test order placement")
        
        response = await angel_broker.place_order(order_request)
        print(f"Type of response: {type(response)}")
        print(f"\n📊 Place Order Response:")
        print(f"  Status: {response.get('status')}")
        print(f"  Order ID: {response.get('order_id')}")
        print(f"  Message: {response.get('order_message')}")
        print(f"  Broker: {response.get('broker')}")
        if response.get('raw_response'):
            print(f"  Raw Response: {response.get('raw_response')}")
        else:
            print(f"  Raw Response: None")
        
        print("\n✅ Angel place_order test completed!")
        
    except Exception as e:
        print(f"❌ Error during place_order test: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_angel_place_order())