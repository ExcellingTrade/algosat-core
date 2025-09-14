#!/usr/bin/env python3
"""
Test script for exit_order with order_id 207 using mock data in broker_manager.get_all_broker_order_details()
This script tests the updated approach where mock data is in broker_manager rather than individual broker files.
"""

import asyncio
import sys
import os
sys.path.insert(0, os.path.abspath('.'))

from algosat.core.order_manager import OrderManager
from algosat.core.broker_manager import BrokerManager
from algosat.core.db import AsyncSessionLocal, get_order_by_id
import logging

# Set up logging to see what's happening
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def test_exit_order_207():
    """Test exit_order for order_id 207 with mock broker data containing real order IDs"""
    
    print("="*60)
    print("Testing exit_order for order_id 207 with mock broker manager data")
    print("="*60)
    
    # Initialize managers
    broker_manager = BrokerManager()
    await broker_manager.setup()
    order_manager = OrderManager(broker_manager)
    
    # Test get_all_broker_order_details first to verify mock data
    print("\n1. Testing get_all_broker_order_details with mock data:")
    print("-" * 50)
    
    try:
        all_broker_orders = await broker_manager.get_all_broker_order_details()
        print(f"✅ Successfully fetched broker orders from {len(all_broker_orders)} brokers")
        
        for broker_name, orders in all_broker_orders.items():
            print(f"\n{broker_name.upper()} Orders: {len(orders)}")
            for order in orders[:2]:  # Show first 2 orders from each broker
                order_id = order.get('order_id') or order.get('id', 'N/A')
                symbol = order.get('tradingsymbol') or order.get('symbol', 'N/A')
                status = order.get('status', 'N/A')
                execution_time = order.get('execution_time', 'N/A')
                price = order.get('average_price') or order.get('tradedPrice', 'N/A')
                print(f"  - Order {order_id}: {symbol} | Status: {status} | Price: {price} | ExecTime: {execution_time}")
            
            if len(orders) > 2:
                print(f"  ... and {len(orders) - 2} more orders")
                
        # Check for target order IDs from order_id 207
        zerodha_orders = all_broker_orders.get('zerodha', [])
        fyers_orders = all_broker_orders.get('fyers', [])
        
        # # Look for target order IDs
        # zerodha_target = next((o for o in zerodha_orders if o.get('order_id') == '250808600582884'), None)
        # fyers_target = next((o for o in fyers_orders if o.get('order_id') == '25080800223154'), None)
        
        # if zerodha_target:
        #     print(f"\n✅ Found Zerodha target order: {zerodha_target['order_id']} - {zerodha_target['tradingsymbol']}")
        # if fyers_target:
        #     print(f"✅ Found Fyers target order: {fyers_target['id']} - {fyers_target['symbol']}")
            
    except Exception as e:
        print(f"❌ Error testing get_all_broker_order_details: {e}")
        return
    
    # Test database query for order_id 207
    print(f"\n2. Testing database query for order_id 207:")
    print("-" * 50)
    
    try:
        async with AsyncSessionLocal() as session:
            order_207 = await get_order_by_id(session, 207)
            if order_207:
                print(f"✅ Found order_id 207:")
                print(f"  - Order ID: {order_207['id']}")
                print(f"  - Symbol: {order_207['symbol']}")
                print(f"  - Status: {order_207['status']}")
                print(f"  - Entry Price: {order_207['entry_price']}")
                print(f"  - Stop Loss: {order_207['stop_loss']}")
                print(f"  - Target Price: {order_207['target_price']}")
            else:
                print("❌ Order_id 207 not found in database")
                return
    except Exception as e:
        print(f"❌ Error querying order_id 207: {e}")
        return
    
    # Test exit_order method
    print(f"\n3. Testing exit_order for order_id 207:")
    print("-" * 50)
    
    try:
        # Call the exit_order method
        print("📞 Calling order_manager.exit_order(order_id=207, exit_reason='testing_mock_data')")
        exit_result = await order_manager.exit_order(parent_order_id=207, exit_reason='testing_mock_data', check_live_status=True)
        
        print(f"✅ Exit order completed successfully!")
        print(f"  - Result: {exit_result}")
        
        # Verify broker_executions were created
        print(f"\n4. Verifying broker_executions were created:")
        print("-" * 50)
        
        from algosat.core.db import get_broker_executions_by_order_id
        async with AsyncSessionLocal() as session:
            broker_execs = await get_broker_executions_by_order_id(session, 207)
            
            print(f"Total broker_executions for order_id 207: {len(broker_execs)}")
            
            exit_execs = [be for be in broker_execs if be.get('action', '').upper() in ['EXIT', 'SELL', 'BUY']]
            print(f"EXIT broker_executions: {len(exit_execs)}")
            
            for exec_record in exit_execs:
                broker_id = exec_record.get('broker_id')
                broker_order_id = exec_record.get('broker_order_id')
                action = exec_record.get('action')
                status = exec_record.get('status')
                execution_price = exec_record.get('execution_price', 0.0)
                execution_time = exec_record.get('execution_time')
                symbol = exec_record.get('symbol')
                
                print(f"  - Broker {broker_id}: {action} | Status: {status} | Price: {execution_price} | Symbol: {symbol}")
                print(f"    Order ID: {broker_order_id} | ExecTime: {execution_time}")
                
        print(f"\n🎉 Test completed successfully!")
        
    except Exception as e:
        print(f"❌ Error in exit_order: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_exit_order_207())
