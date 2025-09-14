#!/usr/bin/env python3
"""
Simple test script to test OrderManager.exit_order method.
Tests the exit_order functionality with proper component initialization.
"""

import sys
import asyncio
sys.path.insert(0, '/opt/algosat')

async def test_exit_order():
    """Test the exit_order method with proper initialization"""
    
    # Initialize database
    from algosat.core.db import init_db
    await init_db()
    
    # Initialize broker manager
    from algosat.core.broker_manager import BrokerManager
    broker_manager = BrokerManager()
    await broker_manager.setup()
    
    # Initialize order manager
    from algosat.core.order_manager import OrderManager
    order_manager = OrderManager(broker_manager)
    
    # Get a sample order ID from database
    from algosat.core.db import AsyncSessionLocal
    from algosat.core.dbschema import orders as orders_table
    from sqlalchemy import select
    
    async with AsyncSessionLocal() as session:
        # Get first available order
        query = select(orders_table).limit(5)
        result = await session.execute(query)
        orders = result.fetchall()
        
        if not orders:
            print("❌ No orders found in database for testing")
            return
        
        print("Available orders for testing:")
        for i, order in enumerate(orders):
            print(f"{i+1}. Order ID: {order.id}, Status: {order.status}, Symbol: {order.strike_symbol}, Side: {order.side}")
        
        # Use the first order for testing
        test_order = orders[0]
        order_id = test_order.id
        
        print(f"\n🧪 Testing exit_order with:")
        print(f"   Order ID: {order_id}")
        print(f"   Current Status: {test_order.status}")
        print(f"   Strike Symbol: {test_order.strike_symbol}")
        print(f"   Side: {test_order.side}")
        print(f"   Executed Quantity: {test_order.executed_quantity}")
        
        # Test with check_live_status=True
        try:
            print(f"\n📊 Calling order_manager.exit_order(order_id={order_id}, check_live_status=True)")
            await order_manager.exit_order(
                parent_order_id=order_id,
                exit_reason="Test exit from test script",
                check_live_status=True
            )
            print("✅ exit_order completed successfully!")
            
        except Exception as e:
            print(f"❌ exit_order failed with error: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    print("🚀 Starting OrderManager.exit_order test...")
    try:
        asyncio.run(test_exit_order())
    except KeyboardInterrupt:
        print("\n⚠️  Test interrupted by user")
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("🏁 Test completed")
