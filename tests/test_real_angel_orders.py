#!/usr/bin/env python3
"""
Test Angel broker get_order_details method with real broker response.
"""

import asyncio
import sys
import os
import pandas as pd

# Add the project root to the path
sys.path.insert(0, '/opt/algosat')

async def test_real_angel_order_details():
    """Test real Angel broker get_order_details and show normalized results."""
    try:
        print("🧪 Testing Real Angel Order Details")
        print("=" * 60)
        
        # Import required modules
        from algosat.brokers.angel import AngelWrapper
        from algosat.core.order_manager import OrderManager
        from algosat.core.broker_manager import BrokerManager
        
        # Create Angel broker instance
        print("🔐 Initializing Angel broker...")
        angel_broker = AngelWrapper()
        login_success = await angel_broker.login()
        
        if not login_success:
            print("❌ Failed to login to Angel broker")
            return
        
        print("✅ Angel broker authenticated successfully")
        
        # Test 1: Get raw order details from Angel
        print(f"\n📋 Fetching raw order details from Angel...")
        raw_orders = await angel_broker.get_order_details()
        
        print(f"📊 Raw Orders Retrieved: {len(raw_orders)}")
        
        if not raw_orders:
            print("ℹ️  No orders found in Angel account")
            return
        
        # Display raw orders as DataFrame
        print(f"\n📄 Raw Angel Orders DataFrame:")
        print("-" * 50)
        
        raw_df = pd.DataFrame(raw_orders)
        
        # Select key columns for display
        key_columns = [
            'orderid', 'tradingsymbol', 'status', 'ordertype', 'producttype',
            'transactiontype', 'quantity', 'price', 'triggerprice', 'filledshares',
            'averageprice', 'updatetime', 'uniqueorderid'
        ]
        
        # Filter columns that exist in the data
        display_columns = [col for col in key_columns if col in raw_df.columns]
        display_df = raw_df[display_columns]
        
        print(display_df.to_string(index=False, max_rows=20, max_cols=None))
        
        # Test 2: Test Angel normalization via OrderManager
        print(f"\n🔄 Testing Angel Order Normalization...")
        print("-" * 50)
        
        broker_manager = BrokerManager()
        order_manager = OrderManager(broker_manager)
        
        # Simulate what get_all_broker_order_details would do for Angel
        broker_orders_raw = {"angel": raw_orders}
        normalized_orders_by_broker = {}
        
        # Apply Angel normalization logic
        from algosat.core.order_manager import (
            ANGEL_STATUS_MAP, 
            ANGEL_ORDER_TYPE_MAP, 
            ANGEL_PRODUCT_TYPE_MAP, 
            ANGEL_TRANSACTION_TYPE_MAP
        )
        
        broker_name = "angel"
        broker_id = 1  # Mock broker ID
        normalized_orders = []
        
        for o in raw_orders:
            status = ANGEL_STATUS_MAP.get(o.get("status", "").lower(), o.get("status"))
            order_type = ANGEL_ORDER_TYPE_MAP.get(o.get("ordertype"), o.get("ordertype"))
            product_type = ANGEL_PRODUCT_TYPE_MAP.get(o.get("producttype"), o.get("producttype"))
            side = ANGEL_TRANSACTION_TYPE_MAP.get(o.get("transactiontype"), o.get("transactiontype"))
            
            # Extract execution time from Angel time fields
            execution_time = None
            if o.get("exchtime"):
                try:
                    from datetime import datetime
                    execution_time = datetime.strptime(o.get("exchtime"), "%d-%b-%Y %H:%M:%S")
                except (ValueError, TypeError):
                    execution_time = None
            elif o.get("updatetime"):
                try:
                    from datetime import datetime
                    execution_time = datetime.strptime(o.get("updatetime"), "%d-%b-%Y %H:%M:%S")
                except (ValueError, TypeError):
                    execution_time = None
            
            normalized_order = {
                "broker_name": broker_name,
                "broker_id": broker_id,
                "order_id": o.get("orderid"),
                "status": status,
                "symbol": o.get("tradingsymbol"),
                "quantity": int(o.get("quantity", 0)),
                "executed_quantity": int(o.get("filledshares", 0)),
                "exec_price": float(o.get("averageprice", 0)),
                "product_type": product_type,
                "order_type": order_type,
                "execution_time": execution_time,
                "side": side,
                "exchange_order_id": o.get("exchangeorderid"),
                "unique_order_id": o.get("uniqueorderid"),
                "variety": o.get("variety"),
                "trigger_price": float(o.get("triggerprice", 0)),
                "price": float(o.get("price", 0)),
            }
            normalized_orders.append(normalized_order)
        
        # Display normalized orders as DataFrame
        print(f"📊 Normalized Orders: {len(normalized_orders)}")
        
        if normalized_orders:
            normalized_df = pd.DataFrame(normalized_orders)
            
            # Select key columns for display
            norm_key_columns = [
                'order_id', 'symbol', 'status', 'order_type', 'product_type',
                'side', 'quantity', 'executed_quantity', 'price', 'trigger_price',
                'exec_price', 'execution_time', 'unique_order_id'
            ]
            
            # Filter columns that exist
            norm_display_columns = [col for col in norm_key_columns if col in normalized_df.columns]
            norm_display_df = normalized_df[norm_display_columns]
            
            print(f"\n📄 Normalized Angel Orders DataFrame:")
            print("-" * 50)
            print(norm_display_df.to_string(index=False, max_rows=20, max_cols=None))
            
            # Show mapping comparison for first order
            if len(raw_orders) > 0 and len(normalized_orders) > 0:
                print(f"\n🔄 Mapping Comparison (First Order):")
                print("-" * 50)
                
                raw_first = raw_orders[0]
                norm_first = normalized_orders[0]
                
                mappings = [
                    ("Status", raw_first.get("status"), norm_first.get("status")),
                    ("Order Type", raw_first.get("ordertype"), norm_first.get("order_type")),
                    ("Product Type", raw_first.get("producttype"), norm_first.get("product_type")),
                    ("Side", raw_first.get("transactiontype"), norm_first.get("side")),
                    ("Quantity", raw_first.get("quantity"), norm_first.get("quantity")),
                    ("Price", raw_first.get("price"), norm_first.get("price")),
                    ("Trigger Price", raw_first.get("triggerprice"), norm_first.get("trigger_price")),
                ]
                
                for field, raw_val, norm_val in mappings:
                    print(f"  {field:12}: '{raw_val}' → '{norm_val}'")
        
        print(f"\n✅ Real Angel order details test completed!")
        print(f"📈 Summary: {len(raw_orders)} orders fetched and normalized successfully")
        
    except Exception as e:
        print(f"❌ Error during real Angel order test: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_real_angel_order_details())