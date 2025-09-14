#!/usr/bin/env python3
"""
Test Angel broker get_order_details method with mock data and normalization.
"""

import asyncio
import sys
import os

# Add the project root to the path
sys.path.insert(0, '/opt/algosat')

# Mock Angel order data from user
MOCK_ANGEL_ORDERS = [
    {'algoID': '99999', 'variety': 'AMO', 'ordertype': 'LIMIT', 'producttype': 'INTRADAY', 'duration': 'DAY', 'price': 150.0, 'triggerprice': 0.0, 'quantity': '150', 'disclosedquantity': '0', 'squareoff': 0.0, 'stoploss': 0.0, 'trailingstoploss': 0.0, 'tradingsymbol': 'NIFTY16SEP2524950CE', 'transactiontype': 'BUY', 'exchange': 'NFO', 'symboltoken': '44662', 'ordertag': '', 'instrumenttype': 'OPTIDX', 'strikeprice': 24950.0, 'optiontype': 'CE', 'expirydate': '16SEP2025', 'lotsize': '75', 'cancelsize': '0', 'averageprice': 0.0, 'filledshares': '0', 'unfilledshares': '150', 'orderid': '091389e428f2AO', 'text': '', 'status': 'open', 'orderstatus': 'open', 'updatetime': '13-Sep-2025 11:30:51', 'exchtime': '', 'exchorderupdatetime': '', 'fillid': '', 'filltime': '', 'parentorderid': '', 'uniqueorderid': '4abfa579-a1ee-4a1e-ba93-4f747f40a80e', 'exchangeorderid': ''},
    {'algoID': '99999', 'variety': 'AMO', 'ordertype': 'STOPLOSS_LIMIT', 'producttype': 'INTRADAY', 'duration': 'DAY', 'price': 220.0, 'triggerprice': 215.0, 'quantity': '150', 'disclosedquantity': '0', 'squareoff': 0.0, 'stoploss': 0.0, 'trailingstoploss': 0.0, 'tradingsymbol': 'NIFTY16SEP2524950CE', 'transactiontype': 'BUY', 'exchange': 'NFO', 'symboltoken': '44662', 'ordertag': '', 'instrumenttype': 'OPTIDX', 'strikeprice': 24950.0, 'optiontype': 'CE', 'expirydate': '16SEP2025', 'lotsize': '75', 'cancelsize': '0', 'averageprice': 0.0, 'filledshares': '0', 'unfilledshares': '150', 'orderid': '0913c74c7aa8AO', 'text': '', 'status': 'open', 'orderstatus': 'open', 'updatetime': '13-Sep-2025 12:57:43', 'exchtime': '', 'exchorderupdatetime': '', 'fillid': '', 'filltime': '', 'parentorderid': '', 'uniqueorderid': 'bdfe4e36-3cba-414c-b49f-54c4c5ef1857', 'exchangeorderid': ''},
    {'algoID': '99999', 'variety': 'AMO', 'ordertype': 'MARKET', 'producttype': 'CARRYFORWARD', 'duration': 'DAY', 'price': 210.6, 'triggerprice': 215.0, 'quantity': '150', 'disclosedquantity': '0', 'squareoff': 0.0, 'stoploss': 0.0, 'trailingstoploss': 0.0, 'tradingsymbol': 'NIFTY16SEP2524950CE', 'transactiontype': 'BUY', 'exchange': 'NFO', 'symboltoken': '44662', 'ordertag': '', 'instrumenttype': 'OPTIDX', 'strikeprice': 24950.0, 'optiontype': 'CE', 'expirydate': '16SEP2025', 'lotsize': '75', 'cancelsize': '0', 'averageprice': 0.0, 'filledshares': '0', 'unfilledshares': '150', 'orderid': '0913187204d0AO', 'text': '', 'status': 'open', 'orderstatus': 'open', 'updatetime': '13-Sep-2025 13:02:26', 'exchtime': '', 'exchorderupdatetime': '', 'fillid': '', 'filltime': '', 'parentorderid': '', 'uniqueorderid': 'a763df7c-80be-4733-9a44-4f88530efd13', 'exchangeorderid': ''}
]

class MockOrderManager:
    """Mock OrderManager with Angel normalization logic for testing."""
    
    def __init__(self):
        # Import Angel mappings from order_manager
        from algosat.core.order_manager import (
            ANGEL_STATUS_MAP, 
            ANGEL_ORDER_TYPE_MAP, 
            ANGEL_PRODUCT_TYPE_MAP, 
            ANGEL_TRANSACTION_TYPE_MAP
        )
        
        self.ANGEL_STATUS_MAP = ANGEL_STATUS_MAP
        self.ANGEL_ORDER_TYPE_MAP = ANGEL_ORDER_TYPE_MAP
        self.ANGEL_PRODUCT_TYPE_MAP = ANGEL_PRODUCT_TYPE_MAP
        self.ANGEL_TRANSACTION_TYPE_MAP = ANGEL_TRANSACTION_TYPE_MAP

    def normalize_angel_orders(self, orders_list: list) -> list:
        """
        Apply Angel One normalization logic to a list of orders.
        """
        normalized_orders = []
        broker_name = "angel"
        broker_id = 1  # Mock broker ID
        
        for o in orders_list:
            status = self.ANGEL_STATUS_MAP.get(o.get("status", "").lower(), o.get("status"))
            order_type = self.ANGEL_ORDER_TYPE_MAP.get(o.get("ordertype"), o.get("ordertype"))
            product_type = self.ANGEL_PRODUCT_TYPE_MAP.get(o.get("producttype"), o.get("producttype"))
            side = self.ANGEL_TRANSACTION_TYPE_MAP.get(o.get("transactiontype"), o.get("transactiontype"))
            
            # Extract execution time from Angel time fields
            execution_time = None
            if o.get("exchtime"):
                try:
                    from datetime import datetime
                    # Angel time format: "13-Sep-2025 11:30:51"
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
                # "raw": o
            }
            normalized_orders.append(normalized_order)
        
        return normalized_orders

async def test_angel_order_details():
    """Test Angel broker get_order_details and normalization."""
    try:
        print("🧪 Testing Angel Order Details & Normalization")
        print("=" * 70)
        
        # Test 1: Mock raw Angel orders
        print("📋 Mock Angel Raw Orders:")
        print(f"Total Orders: {len(MOCK_ANGEL_ORDERS)}")
        print("-" * 50)
        
        for i, order in enumerate(MOCK_ANGEL_ORDERS, 1):
            print(f"Order {i}:")
            print(f"  Order ID: {order['orderid']}")
            print(f"  Symbol: {order['tradingsymbol']}")
            print(f"  Status: {order['status']}")
            print(f"  Order Type: {order['ordertype']}")
            print(f"  Product Type: {order['producttype']}")
            print(f"  Side: {order['transactiontype']}")
            print(f"  Quantity: {order['quantity']}")
            print(f"  Price: {order['price']}")
            print(f"  Trigger Price: {order['triggerprice']}")
            print(f"  Update Time: {order['updatetime']}")
            print()
        
        # Test 2: Angel normalization
        print("🔄 Testing Angel Order Normalization:")
        print("-" * 50)
        
        mock_manager = MockOrderManager()
        normalized_orders = mock_manager.normalize_angel_orders(MOCK_ANGEL_ORDERS)
        
        print(f"Normalized Orders: {len(normalized_orders)}")
        print()
        
        for i, order in enumerate(normalized_orders, 1):
            print(f"Normalized Order {i}:")
            for key, value in order.items():
                print(f"  {key}: {value}")
            print()
        
        # Test 3: Test various Angel status mappings
        print("📊 Angel Status Mapping Test:")
        print("-" * 50)
        
        test_statuses = ["open", "cancelled", "complete", "filled", "rejected", "pending"]
        for status in test_statuses:
            normalized_status = mock_manager.ANGEL_STATUS_MAP.get(status.lower(), status)
            print(f"  '{status}' → {normalized_status}")
        
        print(f"\n✅ Angel order details and normalization test completed!")
        
    except Exception as e:
        print(f"❌ Error during Angel order test: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_angel_order_details())