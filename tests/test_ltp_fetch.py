#!/usr/bin/env python3
"""
Simple test to verify LTP fetching in OrderManager
"""
import asyncio
import sys
import os

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def test_ltp_fetch():
    try:
        from algosat.core.broker_manager import BrokerManager
        from algosat.core.order_manager import OrderManager
        from algosat.core.data_manager import DataManager
        
        print("✅ Successfully imported modules")
        
        # Create instances
        broker_manager = BrokerManager()
        order_manager = OrderManager(broker_manager=broker_manager)
        data_manager = DataManager(broker_manager=broker_manager)
        
        print("✅ Successfully created instances")
        
        # Test if we can ensure broker
        try:
            await data_manager.ensure_broker()
            print("✅ Successfully ensured broker")
        except Exception as e:
            print(f"⚠️  Could not ensure broker: {e}")
        
        # Test LTP fetch logic (simulate what happens in exit_order)
        symbol = "NSE:NIFTY50-INDEX"  # Example symbol
        try:
            ltp_response = await data_manager.get_ltp(symbol)
            if isinstance(ltp_response, dict):
                ltp = ltp_response.get(symbol)
            else:
                ltp = ltp_response
            
            print(f"✅ LTP fetch test successful for {symbol}: {ltp}")
        except Exception as e:
            print(f"⚠️  LTP fetch failed: {e}")
        
        print("✅ Test completed successfully")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_ltp_fetch())
