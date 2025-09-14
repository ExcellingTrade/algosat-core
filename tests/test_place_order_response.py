#!/usr/bin/env python3
"""
Test the updated place_order response to ensure traded_price is included.
"""

import sys
sys.path.insert(0, '/opt/algosat')

def test_place_order_response():
    """Test that place_order returns the expected response format."""
    try:
        from algosat.core.order_request import OrderRequest, Side, OrderType, ProductType
        from algosat.core.order_manager import OrderManager
        from algosat.core.broker_manager import BrokerManager
        from algosat.models.strategy_config import StrategyConfig
        
        print("✅ All required classes imported successfully")
        
        # Mock the database and broker operations for testing
        class MockBrokerManager:
            async def place_order(self, order_payload, strategy_name=None):
                return {
                    "fyers": {
                        "order_id": "FY123456",
                        "status": "pending",
                        "message": "Order placed successfully"
                    }
                }
        
        class MockOrderManager(OrderManager):
            def __init__(self):
                super().__init__(MockBrokerManager())
            
            async def _insert_and_get_order_id(self, config, order_payload, broker_name, result, parent_order_id):
                return 12345  # Mock order ID
            
            async def _insert_broker_execution(self, session, order_id, broker_name, response):
                pass  # Mock implementation
        
        # Create test objects
        order_manager = MockOrderManager()
        
        # Mock strategy config
        config = StrategyConfig(
            id=1,
            strategy_id=1,
            name="Test Config",
            exchange="NSE",
            trade={"max_nse_qty": 500},
            indicators={}
        )
        
        # Create test order
        order_payload = OrderRequest(
            symbol="NSE:NIFTY50-28JUN25-23400-CE",
            side=Side.BUY,
            order_type=OrderType.MARKET,
            product_type=ProductType.INTRADAY,
            quantity=100,
            price=250.0
        )
        
        print("\\n🧪 Testing place_order response format...")
        
        # Test the place_order method
        import asyncio
        
        async def test_place_order():
            # Mock the database session context manager
            class MockAsyncSessionLocal:
                async def __aenter__(self):
                    return self
                async def __aexit__(self, exc_type, exc_val, exc_tb):
                    pass
                async def commit(self):
                    pass
            
            # Replace the actual session with mock
            import algosat.core.order_manager
            algosat.core.order_manager.AsyncSessionLocal = MockAsyncSessionLocal
            
            response = await order_manager.place_order(config, order_payload, "TestStrategy")
            
            # Check response format
            expected_keys = ["order_id", "traded_price", "status", "broker_responses"]
            
            print("\\n📋 Response structure:")
            for key in expected_keys:
                if key in response:
                    print(f"  ✅ {key}: {response[key]}")
                else:
                    print(f"  ❌ {key}: MISSING")
                    return False
            
            # Validate specific values
            if response["traded_price"] == 0.0:
                print("  ✅ traded_price is 0.0 (default value)")
            else:
                print(f"  ❌ traded_price should be 0.0, got {response['traded_price']}")
                return False
            
            if response["status"] == "AWAITING_ENTRY":
                print("  ✅ status is AWAITING_ENTRY (initial status)")
            else:
                print(f"  ❌ status should be AWAITING_ENTRY, got {response['status']}")
                return False
            
            return True
        
        success = asyncio.run(test_place_order())
        return success
        
    except Exception as e:
        print(f"❌ place_order response test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run the place_order response test."""
    print("🚀 Testing place_order Response Format")
    print("=" * 50)
    
    success = test_place_order_response()
    
    if success:
        print("\\n🎉 place_order response test passed!")
        print("✅ The order response now includes traded_price field")
        print("✅ The order response now includes status field")
        print("✅ The order response maintains broker_responses field")
    else:
        print("\\n💥 place_order response test failed!")
    
    return success

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
