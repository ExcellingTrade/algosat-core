#!/usr/bin/env python3

"""
Test script to verify that Fyers order normalization includes parent_id field
"""

import sys
import os
sys.path.append('/opt/algosat')

from algosat.core.order_manager import OrderManager
from algosat.core.broker_manager import BrokerManager

# Sample Fyers orders with and without parentId
sample_fyers_orders = [
    # BO Entry order (no parentId)
    {
        'clientId': 'XR01921', 'exchange': 10, 'fyToken': '101125082147221', 
        'id': '25081900198179-BO-1', 'instrument': 14, 'offlineOrder': False, 
        'source': 'API', 'status': 2, 'type': 1, 'pan': 'CDPPS6526M', 
        'limitPrice': 102.5, 'productType': 'BO', 'qty': 75, 'disclosedQty': 0, 
        'remainingQuantity': 0, 'segment': 11, 'symbol': 'NSE:NIFTY2582124950CE', 
        'description': '25 Aug 21 24950 CE', 'ex_sym': 'NIFTY', 
        'orderDateTime': '19-Aug-2025 12:02:04', 'side': 1, 'orderValidity': 'DAY', 
        'stopPrice': 102.3, 'tradedPrice': 102.3, 'filledQty': 75, 
        'exchOrdId': '1200000074559631', 'message': '', 'ch': 5.85, 
        'chp': 5.7073170731707314, 'lp': 108.35, 
        'orderNumStatus': '25081900198179-BO-1:2', 'slNo': 31, 'orderTag': '2:Untagged'
    },
    # BO Exit order (with parentId)
    {
        'clientId': 'XR01921', 'exchange': 10, 'fyToken': '101125082147221', 
        'id': '25081900212943-BO-3', 'instrument': 14, 'offlineOrder': False, 
        'source': 'SNO', 'status': 2, 'type': 2, 'pan': 'CDPPS6526M', 
        'limitPrice': 116.85, 'productType': 'BO', 'qty': 75, 'disclosedQty': 0, 
        'remainingQuantity': 0, 'segment': 11, 'symbol': 'NSE:NIFTY2582124950CE', 
        'description': '25 Aug 21 24950 CE', 'ex_sym': 'NIFTY', 
        'orderDateTime': '19-Aug-2025 12:18:25', 'side': -1, 'orderValidity': 'DAY', 
        'stopPrice': 0, 'tradedPrice': 116.85, 'filledQty': 75, 
        'exchOrdId': '1200000081538500', 'message': '', 'ch': 5.85, 
        'chp': 5.7073170731707314, 'lp': 108.35, 
        'orderNumStatus': '25081900212943-BO-3:2', 'slNo': 32, 
        'parentId': '25081900198179-BO-1', 'orderTag': ''
    },
    # Regular MARGIN order (no parentId)
    {
        'clientId': 'XR01921', 'exchange': 10, 'fyToken': '101125082147221', 
        'id': '25081900117706', 'instrument': 14, 'offlineOrder': False, 
        'source': 'API', 'status': 2, 'type': 2, 'pan': 'CDPPS6526M', 
        'limitPrice': 82.95, 'productType': 'MARGIN', 'qty': 75, 'disclosedQty': 0, 
        'remainingQuantity': 0, 'segment': 11, 'symbol': 'NSE:NIFTY2582124950CE', 
        'description': '25 Aug 21 24950 CE', 'ex_sym': 'NIFTY', 
        'orderDateTime': '19-Aug-2025 10:21:04', 'side': 1, 'orderValidity': 'DAY', 
        'stopPrice': 0, 'tradedPrice': 82.95, 'filledQty': 75, 
        'exchOrdId': '1200000040362579', 'message': '', 'ch': 5.85, 
        'chp': 5.7073170731707314, 'lp': 108.35, 
        'orderNumStatus': '25081900117706:2', 'slNo': 6, 'orderTag': '1:AlgoOrder'
    }
]

def test_fyers_normalization():
    """Test the Fyers order normalization to check parent_id field"""
    
    # Create OrderManager instance (without dependencies)
    order_manager = OrderManager(None, None)  # broker_manager and db can be None for this test
    
    print("🧪 Testing Fyers order normalization...")
    print("=" * 60)
    
    # Test normalization
    try:
        normalized_orders = order_manager._normalize_broker_orders_response(
            sample_fyers_orders, "fyers", 1
        )
        
        print(f"✅ Normalized {len(normalized_orders)} orders")
        print()
        
        for i, order in enumerate(normalized_orders, 1):
            print(f"📋 Order {i}:")
            print(f"   order_id: {order['order_id']}")
            print(f"   product_type: {order['product_type']}")
            print(f"   parent_id: {order.get('parent_id', 'MISSING!')}")
            print(f"   Has parent_id field: {'parent_id' in order}")
            print()
            
        # Check specific cases
        bo_entry = next((o for o in normalized_orders if o['order_id'] == '25081900198179-BO-1'), None)
        bo_exit = next((o for o in normalized_orders if o['order_id'] == '25081900212943-BO-3'), None)
        margin_order = next((o for o in normalized_orders if o['order_id'] == '25081900117706'), None)
        
        print("🔍 Specific Test Results:")
        print("-" * 30)
        
        if bo_entry:
            print(f"✅ BO Entry Order: parent_id = {bo_entry.get('parent_id')} (should be None)")
        else:
            print("❌ BO Entry Order not found!")
            
        if bo_exit:
            print(f"✅ BO Exit Order: parent_id = {bo_exit.get('parent_id')} (should be '25081900198179-BO-1')")
        else:
            print("❌ BO Exit Order not found!")
            
        if margin_order:
            print(f"✅ MARGIN Order: parent_id = {margin_order.get('parent_id')} (should be None)")
        else:
            print("❌ MARGIN Order not found!")
            
        # Check if all orders have parent_id field
        missing_parent_id = [o for o in normalized_orders if 'parent_id' not in o]
        if missing_parent_id:
            print(f"\n❌ {len(missing_parent_id)} orders missing parent_id field!")
            for order in missing_parent_id:
                print(f"   - {order['order_id']}")
        else:
            print(f"\n✅ All {len(normalized_orders)} orders have parent_id field")
            
    except Exception as e:
        print(f"❌ Error during normalization: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_fyers_normalization()
