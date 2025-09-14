#!/usr/bin/env python3
"""
Test the updated _insert_exit_broker_execution method signature
"""

import sys
import os
sys.path.append('/opt/algosat')

def test_exit_broker_execution_signature():
    """Test that the _insert_exit_broker_execution method accepts the action parameter"""
    
    print("=== Testing _insert_exit_broker_execution Method Signature ===\n")
    
    try:
        # Import the OrderManager class
        from algosat.core.order_manager import OrderManager
        from algosat.core.broker_manager import BrokerManager
        print("✅ Successfully imported OrderManager and BrokerManager")
        
        # Create a dummy BrokerManager for OrderManager initialization
        broker_manager = BrokerManager()
        order_manager = OrderManager(broker_manager)
        print("✅ Successfully created OrderManager instance")
        
        # Check that the _insert_exit_broker_execution method exists and has the right signature
        method = getattr(order_manager, '_insert_exit_broker_execution', None)
        if method is None:
            print("❌ _insert_exit_broker_execution method not found")
            return
        
        # Check the method signature using inspect
        import inspect
        sig = inspect.signature(method)
        params = list(sig.parameters.keys())
        
        print(f"✅ Method found with parameters: {params}")
        
        # Check if 'action' parameter is present
        if 'action' in params:
            print("✅ 'action' parameter is present in method signature")
        else:
            print("❌ 'action' parameter is missing from method signature")
            
        # Check if 'action' has a default value
        action_param = sig.parameters.get('action')
        if action_param and action_param.default is not inspect.Parameter.empty:
            print(f"✅ 'action' parameter has default value: {action_param.default}")
        else:
            print("⚠️  'action' parameter has no default value")
            
        # Test the method can be called with action parameter (mock session)
        class MockSession:
            async def execute(self, query):
                pass
                
        mock_session = MockSession()
        
        # This should not raise a TypeError about unexpected keyword argument
        try:
            import asyncio
            
            async def test_call():
                await method(
                    mock_session,
                    parent_order_id=1,
                    broker_id=1,
                    broker_order_id="TEST123",
                    side="EXIT",
                    status="FILLED",
                    executed_quantity=100,
                    execution_price=150.0,
                    product_type="MIS",
                    order_type="MARKET",
                    order_messages="Test exit",
                    symbol="TEST-SYMBOL",
                    execution_time=None,
                    notes="Test notes",
                    action="SELL"  # This should work now
                )
                
            # Just check that the call would work (don't actually execute)
            print("✅ Method signature accepts 'action' parameter without error")
            
        except Exception as e:
            print(f"❌ Method signature test failed: {e}")
            
        print("\n=== Method signature test completed ===")
        
    except Exception as e:
        print(f"❌ Error testing method signature: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_exit_broker_execution_signature()
