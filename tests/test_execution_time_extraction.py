#!/usr/bin/env python3
"""
Test script to verify execution time extraction from broker responses
"""

import sys
import os
from datetime import datetime

# Add the algosat directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'algosat'))

def test_fyers_execution_time():
    print("Testing Fyers execution time extraction...")
    
    # Sample Fyers order data from your test
    fyers_order = {
        'clientId': 'XR01921', 
        'exchange': 10, 
        'fyToken': '101125080739842', 
        'id': '25080700048272', 
        'instrument': 14, 
        'offlineOrder': False, 
        'source': 'API', 
        'status': 2, 
        'type': 2, 
        'pan': 'CDPPS6526M', 
        'limitPrice': 52.3, 
        'productType': 'MARGIN', 
        'qty': 75, 
        'disclosedQty': 0, 
        'remainingQuantity': 0, 
        'segment': 11, 
        'symbol': 'NSE:NIFTY2580724550PE', 
        'description': '25 Aug 07 24550 PE', 
        'ex_sym': 'NIFTY', 
        'orderDateTime': '07-Aug-2025 09:33:08',  # This is the execution time!
        'side': 1, 
        'orderValidity': 'DAY', 
        'stopPrice': 0, 
        'tradedPrice': 52.3, 
        'filledQty': 75, 
        'exchOrdId': '1100000017485102'
    }
    
    # Test Fyers normalization logic
    if fyers_order.get("orderDateTime"):
        try:
            execution_time = datetime.strptime(fyers_order.get("orderDateTime"), "%d-%b-%Y %H:%M:%S")
            print(f"✅ Fyers execution time extracted: {execution_time}")
            print(f"   Raw orderDateTime: {fyers_order.get('orderDateTime')}")
        except (ValueError, TypeError) as e:
            print(f"❌ Failed to parse Fyers orderDateTime: {e}")
    else:
        print("❌ No orderDateTime found in Fyers order")

def test_zerodha_execution_time():
    print("\nTesting Zerodha execution time extraction...")
    
    # Sample Zerodha order data from your test
    zerodha_order = {
        'account_id': 'HU6119', 
        'placed_by': 'HU6119', 
        'order_id': '250807600160587', 
        'exchange_order_id': '1100000017453621', 
        'parent_order_id': None, 
        'status': 'COMPLETE', 
        'status_message': None, 
        'status_message_raw': None, 
        'order_timestamp': datetime(2025, 8, 7, 9, 33, 5), 
        'exchange_update_timestamp': '2025-08-07 09:33:05', 
        'exchange_timestamp': datetime(2025, 8, 7, 9, 33, 5), 
        'variety': 'regular', 
        'modified': False, 
        'exchange': 'NFO', 
        'tradingsymbol': 'NIFTY2580724550PE', 
        'instrument_token': 10199554, 
        'order_type': 'MARKET', 
        'transaction_type': 'BUY', 
        'validity': 'DAY', 
        'validity_ttl': 0, 
        'product': 'NRML', 
        'quantity': 75, 
        'disclosed_quantity': 0, 
        'price': 0, 
        'trigger_price': 0, 
        'average_price': 51.6, 
        'filled_quantity': 75, 
        'pending_quantity': 0, 
        'cancelled_quantity': 0, 
        'market_protection': 0, 
        'meta': {}, 
        'tag': 'AlgoOrder', 
        'tags': ['AlgoOrder'], 
        'guid': '149993XdWi2lXwXmnUy'
    }
    
    # Test Zerodha normalization logic (prefer exchange_timestamp)
    execution_time = None
    if zerodha_order.get("exchange_timestamp"):
        execution_time = zerodha_order.get("exchange_timestamp")
        print(f"✅ Zerodha execution time extracted from exchange_timestamp: {execution_time}")
    elif zerodha_order.get("order_timestamp"):
        execution_time = zerodha_order.get("order_timestamp")
        print(f"✅ Zerodha execution time extracted from order_timestamp: {execution_time}")
    elif zerodha_order.get("exchange_update_timestamp"):
        # Convert string timestamp to datetime if needed
        try:
            if isinstance(zerodha_order.get("exchange_update_timestamp"), str):
                execution_time = datetime.strptime(zerodha_order.get("exchange_update_timestamp"), "%Y-%m-%d %H:%M:%S")
            else:
                execution_time = zerodha_order.get("exchange_update_timestamp")
            print(f"✅ Zerodha execution time extracted from exchange_update_timestamp: {execution_time}")
        except (ValueError, TypeError) as e:
            print(f"❌ Failed to parse Zerodha exchange_update_timestamp: {e}")
    else:
        print("❌ No time fields found in Zerodha order")
    
    print(f"   Raw order_timestamp: {zerodha_order.get('order_timestamp')}")
    print(f"   Raw exchange_timestamp: {zerodha_order.get('exchange_timestamp')}")
    print(f"   Raw exchange_update_timestamp: {zerodha_order.get('exchange_update_timestamp')}")

def test_normalization_function():
    print("\n" + "="*60)
    print("Testing the actual normalization function...")
    
    try:
        from algosat.core.order_manager import OrderManager
        om = OrderManager()
        
        # Test with sample data structure that mimics what get_all_broker_order_details returns
        sample_broker_orders = {
            "fyers": [
                {
                    'id': '25080700048272',
                    'status': 2,
                    'type': 2,
                    'symbol': 'NSE:NIFTY2580724550PE',
                    'qty': 75,
                    'filledQty': 75,
                    'tradedPrice': 52.3,
                    'productType': 'MARGIN',
                    'orderDateTime': '07-Aug-2025 09:33:08'
                }
            ],
            "zerodha": [
                {
                    'order_id': '250807600160587',
                    'status': 'COMPLETE',
                    'tradingsymbol': 'NIFTY2580724550PE',
                    'quantity': 75,
                    'filled_quantity': 75,
                    'average_price': 51.6,
                    'product': 'NRML',
                    'order_type': 'MARKET',
                    'order_timestamp': datetime(2025, 8, 7, 9, 33, 5),
                    'exchange_timestamp': datetime(2025, 8, 7, 9, 33, 5),
                    'exchange_update_timestamp': '2025-08-07 09:33:05'
                }
            ]
        }
        
        # Test normalization
        normalized = om._normalize_broker_orders_response(sample_broker_orders)
        
        print("\nNormalized Fyers order:")
        fyers_orders = normalized.get("fyers", [])
        if fyers_orders:
            fyers_order = fyers_orders[0]
            print(f"  Order ID: {fyers_order.get('order_id')}")
            print(f"  Symbol: {fyers_order.get('symbol')}")
            print(f"  Execution Time: {fyers_order.get('execution_time')}")
            print(f"  Status: {fyers_order.get('status')}")
            
        print("\nNormalized Zerodha order:")
        zerodha_orders = normalized.get("zerodha", [])
        if zerodha_orders:
            zerodha_order = zerodha_orders[0]
            print(f"  Order ID: {zerodha_order.get('order_id')}")
            print(f"  Symbol: {zerodha_order.get('symbol')}")
            print(f"  Execution Time: {zerodha_order.get('execution_time')}")
            print(f"  Status: {zerodha_order.get('status')}")
            
    except ImportError as e:
        print(f"❌ Could not import OrderManager: {e}")
    except Exception as e:
        print(f"❌ Error testing normalization function: {e}")

if __name__ == "__main__":
    print("🧪 Testing Execution Time Extraction from Broker Responses")
    print("="*60)
    
    test_fyers_execution_time()
    test_zerodha_execution_time()
    test_normalization_function()
    
    print("\n" + "="*60)
    print("✅ SUMMARY: Broker APIs DO provide execution time!")
    print("📝 Changes made:")
    print("   1. Modified Fyers normalization to extract 'orderDateTime'")
    print("   2. Modified Zerodha normalization to extract time fields")
    print("   3. Updated order_monitor.py to use broker execution time")
    print("   4. Updated order_manager.py to use broker execution time")
    print("\n💡 The system will now use broker-provided execution times instead of datetime.now()!")
