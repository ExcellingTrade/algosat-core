#!/usr/bin/env python3
"""
Test script to verify datetime serialization fix for JSON storage
"""
import sys
import os
sys.path.append('/opt/algosat')

from datetime import datetime
from enum import Enum
from algosat.core.order_manager import OrderManager
from algosat.core.broker_manager import BrokerManager

# Test data that mimics broker response with datetime objects
class OrderStatus(Enum):
    FILLED = 'FILLED'
    CANCELLED = 'CANCELLED'

test_broker_response = {
    'broker_name': 'fyers',
    'broker_id': 1,
    'order_id': '25081100241531',
    'status': OrderStatus.FILLED,
    'symbol': 'NSE:NIFTY2581424100PE',
    'qty': 75,
    'executed_quantity': 75,
    'exec_price': 17.2,
    'product_type': 'MARGIN',
    'order_type': 2,
    'execution_time': datetime(2025, 8, 11, 12, 46, 5),
    'side': 'BUY',
    'nested_data': {
        'order_timestamp': datetime(2025, 8, 11, 12, 46, 0),
        'update_time': datetime(2025, 8, 11, 12, 50, 0),
        'status_enum': OrderStatus.CANCELLED
    }
}

def test_datetime_serialization():
    # Create a dummy OrderManager instance
    broker_manager = BrokerManager()
    order_manager = OrderManager(broker_manager)
    
    # Test the serialization method
    serialized_data = order_manager._serialize_datetime_for_json(test_broker_response)
    
    print("Original data:")
    print(test_broker_response)
    print("\nSerialized data:")
    print(serialized_data)
    
    # Verify no datetime objects remain
    import json
    try:
        json_str = json.dumps(serialized_data)
        print(f"\n✅ JSON serialization successful! Length: {len(json_str)} characters")
        print("✅ No datetime serialization errors will occur")
        return True
    except Exception as e:
        print(f"\n❌ JSON serialization failed: {e}")
        return False

if __name__ == "__main__":
    success = test_datetime_serialization()
    sys.exit(0 if success else 1)
