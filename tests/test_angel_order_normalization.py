#!/usr/bin/env python3
"""
Test Angel One order normalization in OrderManager.
"""
import sys
import os

# Add the project root to the path
sys.path.insert(0, '/opt/algosat')

def test_angel_order_normalization():
    """Test Angel One order normalization logic."""
    try:
        print("🧪 Testing Angel One Order Normalization")
        print("=" * 60)
        
        # Import required modules
        from algosat.core.order_manager import (
            ANGEL_STATUS_MAP, 
            ANGEL_ORDER_TYPE_MAP, 
            ANGEL_PRODUCT_TYPE_MAP, 
            ANGEL_TRANSACTION_TYPE_MAP
        )
        from algosat.core.order_request import OrderStatus
        
        # Sample Angel order response (from user's message)
        sample_angel_order = {
            "variety": "NORMAL",
            "ordertype": "LIMIT",
            "producttype": "INTRADAY", 
            "duration": "DAY",
            "price": "194.00",
            "triggerprice": "0",
            "quantity": "1",
            "disclosedquantity": "0",
            "squareoff": "0",
            "stoploss": "0",
            "trailingstoploss": "0",
            "tradingsymbol": "SBIN-EQ",
            "transactiontype": "BUY",
            "exchange": "NSE",
            "symboltoken": None,
            "instrumenttype": "",
            "strikeprice": "-1",
            "optiontype": "",
            "expirydate": "",
            "lotsize": "1",
            "cancelsize": "1",
            "averageprice": "0",
            "filledshares": "0",
            "unfilledshares": "1",
            "orderid": "201020000000080",
            "text": "",
            "status": "cancelled",
            "orderstatus": "cancelled",
            "updatetime": "20-Oct-2020 13:10:59",
            "exchtime": "20-Oct-2020 13:10:59",
            "exchorderupdatetime": "20-Oct-2020 13:10:59",
            "fillid": "",
            "filltime": "",
            "parentorderid": "",
            "uniqueorderid": "34reqfachdfih",
            "exchangeorderid": "1100000000048358"
        }
        
        print("📋 Sample Angel Order:")
        print(f"  Order ID: {sample_angel_order['orderid']}")
        print(f"  Symbol: {sample_angel_order['tradingsymbol']}")
        print(f"  Status: {sample_angel_order['status']}")
        print(f"  Order Type: {sample_angel_order['ordertype']}")
        print(f"  Product Type: {sample_angel_order['producttype']}")
        print(f"  Transaction Type: {sample_angel_order['transactiontype']}")
        print(f"  Quantity: {sample_angel_order['quantity']}")
        print(f"  Filled Shares: {sample_angel_order['filledshares']}")
        print(f"  Average Price: {sample_angel_order['averageprice']}")
        print(f"  Update Time: {sample_angel_order['updatetime']}")
        
        print(f"\n🔄 Testing normalization mappings...")
        
        # Test status mapping
        raw_status = sample_angel_order.get("status", "").lower()
        normalized_status = ANGEL_STATUS_MAP.get(raw_status, sample_angel_order.get("status"))
        print(f"  Status: '{sample_angel_order['status']}' → {normalized_status}")
        
        # Test order type mapping
        raw_order_type = sample_angel_order.get("ordertype")
        normalized_order_type = ANGEL_ORDER_TYPE_MAP.get(raw_order_type, raw_order_type)
        print(f"  Order Type: '{raw_order_type}' → '{normalized_order_type}'")
        
        # Test product type mapping
        raw_product_type = sample_angel_order.get("producttype")
        normalized_product_type = ANGEL_PRODUCT_TYPE_MAP.get(raw_product_type, raw_product_type)
        print(f"  Product Type: '{raw_product_type}' → '{normalized_product_type}'")
        
        # Test transaction type mapping
        raw_transaction_type = sample_angel_order.get("transactiontype")
        normalized_side = ANGEL_TRANSACTION_TYPE_MAP.get(raw_transaction_type, raw_transaction_type)
        print(f"  Side: '{raw_transaction_type}' → '{normalized_side}'")
        
        # Test time parsing
        execution_time = None
        if sample_angel_order.get("exchtime"):
            try:
                from datetime import datetime
                execution_time = datetime.strptime(sample_angel_order.get("exchtime"), "%d-%b-%Y %H:%M:%S")
                print(f"  Execution Time: '{sample_angel_order['exchtime']}' → {execution_time}")
            except (ValueError, TypeError) as e:
                print(f"  Execution Time: Error parsing '{sample_angel_order['exchtime']}' - {e}")
        
        print(f"\n📊 Normalized Angel Order:")
        normalized_order = {
            "broker_name": "angel",
            "broker_id": 1,  # Mock broker ID
            "order_id": sample_angel_order.get("orderid"),
            "status": normalized_status,
            "symbol": sample_angel_order.get("tradingsymbol"),
            "quantity": int(sample_angel_order.get("quantity", 0)),
            "executed_quantity": int(sample_angel_order.get("filledshares", 0)),
            "exec_price": float(sample_angel_order.get("averageprice", 0)),
            "product_type": normalized_product_type,
            "order_type": normalized_order_type,
            "execution_time": execution_time,
            "side": normalized_side,
            "exchange_order_id": sample_angel_order.get("exchangeorderid"),
            "unique_order_id": sample_angel_order.get("uniqueorderid"),
        }
        
        for key, value in normalized_order.items():
            print(f"  {key}: {value}")
        
        print(f"\n✅ Angel Order normalization test completed!")
        print(f"Status correctly mapped: {normalized_status == OrderStatus.CANCELLED}")
        
    except Exception as e:
        print(f"❌ Error during normalization test: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_angel_order_normalization()