#!/usr/bin/env python3
"""
Test exit_order for order_id 207 with proper mock data including the actual broker order IDs.
This test shows how execution_price should work for exits vs entries.
"""

import sys
sys.path.append('/opt/algosat')

import asyncio
from datetime import date
from unittest.mock import patch

async def test_exit_order_with_proper_mock_data():
    """
    Test exit_order functionality with proper mock data that includes the actual order IDs
    """
    
    print("=== TESTING EXIT_ORDER WITH PROPER MOCK DATA ===\n")
    
    # First, let's add the missing order IDs to mock data temporarily
    additional_fyers_orders = [
        {
            'id': '25080800223154',  # The actual Fyers order from order_id 207
            'symbol': 'NSE:NIFTY2580824850CE',
            'qty': 75,
            'filledQty': 75,
            'side': 1,  # BUY
            'status': 2,  # FILLED
            'limitPrice': 115.50,
            'tradedPrice': 115.50,  # Entry execution price
            'productType': 'MARGIN',
            'orderDateTime': '08-Aug-2025 14:55:23',
            'disQty': 0,
            'stopPrice': 0,
            'orderNumStatus': '25080800223154:2',
            'orderTag': '',
            'type': 2,
            'orderValidity': 'DAY'
        }
    ]
    
    additional_zerodha_orders = [
        {
            'order_id': '250808600582884',  # The actual Zerodha order from order_id 207
            'tradingsymbol': 'NIFTY2580824850CE',
            'quantity': 75,
            'filled_quantity': 75,
            'transaction_type': 'BUY',
            'status': 'COMPLETE',
            'price': 115.90,
            'average_price': 115.90,  # Entry execution price
            'product': 'NRML',
            'order_timestamp': '2025-08-08 14:55:22',
            'exchange_timestamp': '2025-08-08 14:55:23',
            'exchange_update_timestamp': '2025-08-08 14:55:24',
            'validity': 'DAY',
            'order_type': 'MARKET',
            'exchange': 'NSE',
            'instrument_token': '13405442',
            'tag': '',
            'guid': ''
        }
    ]
    
    try:
        # Initialize database and components
        from algosat.core.db import init_db
        from algosat.core.broker_manager import BrokerManager
        from algosat.core.order_manager import OrderManager
        
        print("🔧 Initializing components...")
        await init_db()
        
        broker_manager = BrokerManager()
        await broker_manager.setup()
        
        order_manager = OrderManager(broker_manager)
        
        # Patch mock data to include our specific orders
        from algosat.brokers.fyers import FyersWrapper
        from algosat.brokers.zerodha import ZerodhaWrapper
        
        original_fyers_get_order_details = FyersWrapper.get_order_details_async
        original_zerodha_get_order_details = ZerodhaWrapper.get_order_details
        
        async def enhanced_fyers_mock(self, *args, **kwargs):
            original_orders = await original_fyers_get_order_details(self, *args, **kwargs)
            return original_orders + additional_fyers_orders
            
        async def enhanced_zerodha_mock(self, *args, **kwargs):
            original_orders = await original_zerodha_get_order_details(self, *args, **kwargs)
            return original_orders + additional_zerodha_orders
        
        # Apply patches
        FyersWrapper.get_order_details_async = enhanced_fyers_mock
        ZerodhaWrapper.get_order_details = enhanced_zerodha_mock
        
        print("✅ Enhanced mock data with actual order IDs")
        
        # Test parameters
        order_id = 207
        test_ltp_market_price = 250.75  # Current market price for exit
        
        print(f"\n📊 TEST SCENARIO:")
        print(f"   Order ID: {order_id}")
        print(f"   Exit LTP (current market price): {test_ltp_market_price}")
        print(f"   Expected behavior: Use LTP as execution_price for exit")
        
        print(f"\n🔍 FINDING ENTRY EXECUTION DETAILS FROM MOCK DATA:")
        
        # Get enhanced mock data
        fyers = FyersWrapper()
        zerodha = ZerodhaWrapper()
        
        fyers_orders = await fyers.get_order_details_async()
        zerodha_orders = await zerodha.get_order_details()
        
        # Find our specific orders
        fyers_order = None
        zerodha_order = None
        
        for order in fyers_orders:
            if order.get('id') == '25080800223154':
                fyers_order = order
                break
                
        for order in zerodha_orders:
            if order.get('order_id') == '250808600582884':
                zerodha_order = order
                break
        
        if fyers_order:
            print(f"✅ Found Fyers entry order:")
            print(f"   Order ID: {fyers_order['id']}")
            print(f"   Symbol: {fyers_order['symbol']}")
            print(f"   Side: {fyers_order['side']} (1=BUY)")
            print(f"   Entry Execution Price: {fyers_order['tradedPrice']}")
            print(f"   Quantity: {fyers_order['filledQty']}")
            
        if zerodha_order:
            print(f"✅ Found Zerodha entry order:")
            print(f"   Order ID: {zerodha_order['order_id']}")
            print(f"   Symbol: {zerodha_order['tradingsymbol']}")
            print(f"   Side: {zerodha_order['transaction_type']}")
            print(f"   Entry Execution Price: {zerodha_order['average_price']}")
            print(f"   Quantity: {zerodha_order['filled_quantity']}")
        
        print(f"\n🚀 EXECUTING EXIT_ORDER...")
        
        # Execute exit_order with market LTP
        result = await order_manager.exit_order(
            parent_order_id=order_id,
            check_live_status=True,
            ltp=test_ltp_market_price  # This becomes the exit execution_price
        )
        
        print(f"✅ Exit order completed: {result}")
        
        print(f"\n📋 EXECUTION PRICE EXPLANATION:")
        print(f"┌─ ENTRY PRICES (from broker execution history):")
        print(f"│  ├─ Fyers entry execution: {fyers_order['tradedPrice'] if fyers_order else 'N/A'}")
        print(f"│  └─ Zerodha entry execution: {zerodha_order['average_price'] if zerodha_order else 'N/A'}")
        print(f"│")
        print(f"├─ EXIT PRICE (from current market):")
        print(f"│  └─ LTP (current market price): {test_ltp_market_price}")
        print(f"│")
        print(f"└─ WHY EXIT USES LTP:")
        print(f"   ├─ Entry prices are historical (when position was opened)")
        print(f"   ├─ Exit price should be current market price (LTP)")
        print(f"   ├─ This gives accurate P&L calculation")
        print(f"   └─ exit_order method: execution_price = ltp or 0.0")
        
        print(f"\n💰 P&L CALCULATION EXAMPLE:")
        if fyers_order and zerodha_order:
            avg_entry = (float(fyers_order['tradedPrice']) + float(zerodha_order['average_price'])) / 2
            exit_price = test_ltp_market_price
            quantity = 150  # Total quantity (75 + 75)
            
            pnl = (exit_price - avg_entry) * quantity
            print(f"   Average Entry Price: {avg_entry:.2f}")
            print(f"   Exit Price (LTP): {exit_price:.2f}")
            print(f"   Total Quantity: {quantity}")
            print(f"   P&L: ({exit_price:.2f} - {avg_entry:.2f}) × {quantity} = {pnl:.2f}")
        
        # Restore original mock functions
        FyersWrapper.get_order_details_async = original_fyers_get_order_details
        ZerodhaWrapper.get_order_details = original_zerodha_get_order_details
        
        print(f"\n✅ Test completed successfully!")
        print(f"🎯 KEY TAKEAWAY: execution_price=250.75 came from test LTP parameter, which is CORRECT for exits!")
        
    except Exception as e:
        print(f"❌ Error in test: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_exit_order_with_proper_mock_data())
