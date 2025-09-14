#!/usr/bin/env python3
"""
Test script for Orders API endpoints.
This script tests the orders API to ensure it works correctly with the new fields.
"""

import asyncio
import aiohttp
import json
from datetime import datetime
from typing import Optional, Dict, Any, List

# Configuration
BASE_URL = "http://localhost:8001"
TEST_USERNAME = "admin"  # Update with your test username
TEST_PASSWORD = "admin123"  # Update with your test password

class OrdersAPITest:
    def __init__(self):
        self.session = None
        self.token = None
        self.headers = {}
        
    async def setup(self):
        """Setup HTTP session and authenticate."""
        self.session = aiohttp.ClientSession()
        
        # Login to get authentication token
        login_data = {
            "username": TEST_USERNAME,
            "password": TEST_PASSWORD
        }
        
        print(f"🔐 Attempting login to {BASE_URL}/auth/login")
        async with self.session.post(f"{BASE_URL}/auth/login", json=login_data) as response:
            if response.status == 200:
                auth_response = await response.json()
                self.token = auth_response["access_token"]
                self.headers = {"Authorization": f"Bearer {self.token}"}
                print("✅ Authentication successful")
                print(f"   Token: {self.token[:20]}...")
            else:
                print(f"❌ Authentication failed: {response.status}")
                error_text = await response.text()
                print(f"   Error: {error_text}")
                return False
        return True
    
    async def cleanup(self):
        """Cleanup HTTP session."""
        if self.session:
            await self.session.close()
    
    async def test_list_all_orders(self):
        """Test GET /orders/ - List all orders"""
        print("\n🧪 Testing: List All Orders")
        print("=" * 50)
        
        async with self.session.get(f"{BASE_URL}/orders/", headers=self.headers) as response:
            if response.status == 200:
                orders = await response.json()
                print(f"✅ Retrieved {len(orders)} orders")
                
                if orders:
                    # Display first few orders with new fields
                    print("\n📋 Sample Orders (showing first 3):")
                    for i, order in enumerate(orders[:3]):
                        print(f"\n   Order #{i+1}:")
                        print(f"      ID: {order.get('id', 'N/A')}")
                        print(f"      Order ID: {order.get('order_id', 'N/A')}")
                        print(f"      Symbol: {order.get('symbol', 'N/A')}")
                        print(f"      Strategy Name: {order.get('strategy_name', 'N/A')}")
                        print(f"      Status: {order.get('status', 'N/A')}")
                        print(f"      Direction: {order.get('signal_direction', 'N/A')}")
                        print(f"      Lot Qty: {order.get('lot_qty', 'N/A')}")
                        print(f"      Entry Price: {order.get('entry_spot_price', 'N/A')}")
                        print(f"      Target: {order.get('target_spot_level', 'N/A')}")
                        print(f"      Stoploss: {order.get('stoploss_spot_level', 'N/A')}")
                        print(f"      Signal Time: {order.get('signal_time', 'N/A')}")
                        print(f"      Broker: {order.get('broker_name', 'N/A')}")
                else:
                    print("   No orders found")
                
                return orders
            else:
                print(f"❌ Failed to list orders: {response.status}")
                error_text = await response.text()
                print(f"   Error: {error_text}")
                return []
    
    async def test_list_orders_by_broker(self, broker_name: str = "zerodha"):
        """Test GET /orders/?broker_name={broker_name}"""
        print(f"\n🧪 Testing: List Orders by Broker ({broker_name})")
        print("=" * 50)
        
        params = {"broker_name": broker_name}
        async with self.session.get(f"{BASE_URL}/orders/", params=params, headers=self.headers) as response:
            if response.status == 200:
                orders = await response.json()
                print(f"✅ Retrieved {len(orders)} orders for broker '{broker_name}'")
                
                if orders:
                    print(f"\n📋 Orders for {broker_name} broker:")
                    for order in orders[:5]:  # Show first 5
                        print(f"   • Order {order.get('order_id', order.get('id'))}: {order.get('symbol')} - {order.get('status')} - Strategy: {order.get('strategy_name', 'N/A')}")
                else:
                    print(f"   No orders found for broker '{broker_name}'")
                
                return orders
            else:
                print(f"❌ Failed to list orders by broker: {response.status}")
                error_text = await response.text()
                print(f"   Error: {error_text}")
                return []
    
    async def test_list_orders_by_broker_and_strategy(self, broker_name: str = "zerodha", strategy_config_id: int = 1):
        """Test GET /orders/?broker_name={broker_name}&strategy_config_id={strategy_config_id}"""
        print(f"\n🧪 Testing: List Orders by Broker and Strategy ({broker_name}, config_id={strategy_config_id})")
        print("=" * 50)
        
        params = {"broker_name": broker_name, "strategy_config_id": strategy_config_id}
        async with self.session.get(f"{BASE_URL}/orders/", params=params, headers=self.headers) as response:
            if response.status == 200:
                orders = await response.json()
                print(f"✅ Retrieved {len(orders)} orders for broker '{broker_name}' and strategy config {strategy_config_id}")
                
                if orders:
                    print(f"\n📋 Filtered Orders:")
                    for order in orders:
                        print(f"   • Order {order.get('order_id', order.get('id'))}: {order.get('symbol')} - {order.get('status')} - Strategy: {order.get('strategy_name', 'N/A')}")
                else:
                    print(f"   No orders found for the specified filters")
                
                return orders
            else:
                print(f"❌ Failed to list orders by broker and strategy: {response.status}")
                error_text = await response.text()
                print(f"   Error: {error_text}")
                return []
    
    async def test_get_order_detail(self, order_id: int):
        """Test GET /orders/{order_id}"""
        print(f"\n🧪 Testing: Get Order Detail (ID: {order_id})")
        print("=" * 50)
        
        async with self.session.get(f"{BASE_URL}/orders/{order_id}", headers=self.headers) as response:
            if response.status == 200:
                order = await response.json()
                print(f"✅ Retrieved detailed information for order {order_id}")
                
                print(f"\n📋 Order Details:")
                print(f"   ID: {order.get('id')}")
                print(f"   Order ID: {order.get('order_id', order.get('id'))}")
                print(f"   Symbol: {order.get('symbol')}")
                print(f"   Strategy Name: {order.get('strategy_name', 'N/A')}")
                print(f"   Broker: {order.get('broker_name')}")
                print(f"   Status: {order.get('status')}")
                print(f"   Direction: {order.get('signal_direction')}")
                print(f"   Lot Quantity: {order.get('lot_qty')}")
                print(f"   Entry Spot Price: {order.get('entry_spot_price')}")
                print(f"   Entry Swing High: {order.get('entry_spot_swing_high')}")
                print(f"   Entry Swing Low: {order.get('entry_spot_swing_low')}")
                print(f"   Target Level: {order.get('target_spot_level')}")
                print(f"   Stoploss Level: {order.get('stoploss_spot_level')}")
                print(f"   Entry RSI: {order.get('entry_rsi')}")
                print(f"   Signal Time: {order.get('signal_time')}")
                print(f"   Created At: {order.get('created_at')}")
                print(f"   Updated At: {order.get('updated_at')}")
                
                return order
            elif response.status == 404:
                print(f"❌ Order {order_id} not found")
                return None
            else:
                print(f"❌ Failed to get order detail: {response.status}")
                error_text = await response.text()
                print(f"   Error: {error_text}")
                return None
    
    async def test_orders_field_validation(self):
        """Test to validate that new fields (strategy_name, order_id) are present in responses"""
        print(f"\n🧪 Testing: New Fields Validation (strategy_name, order_id)")
        print("=" * 50)
        
        # Get all orders to check fields
        async with self.session.get(f"{BASE_URL}/orders/", headers=self.headers) as response:
            if response.status == 200:
                orders = await response.json()
                
                if not orders:
                    print("⚠️  No orders available to test field validation")
                    return
                
                print(f"✅ Testing field presence in {len(orders)} orders")
                
                # Check first order for new fields
                first_order = orders[0]
                
                # Test order_id field
                if 'order_id' in first_order:
                    print(f"✅ order_id field present: {first_order['order_id']}")
                else:
                    print("❌ order_id field missing")
                
                # Test strategy_name field
                if 'strategy_name' in first_order:
                    if first_order['strategy_name']:
                        print(f"✅ strategy_name field present: '{first_order['strategy_name']}'")
                    else:
                        print("⚠️  strategy_name field present but empty")
                else:
                    print("❌ strategy_name field missing")
                
                # Count orders with strategy names
                orders_with_strategy = sum(1 for order in orders if order.get('strategy_name'))
                print(f"📊 {orders_with_strategy}/{len(orders)} orders have strategy names")
                
                # Show unique strategy names
                strategy_names = set(order.get('strategy_name') for order in orders if order.get('strategy_name'))
                if strategy_names:
                    print(f"📋 Unique strategies found: {', '.join(sorted(strategy_names))}")
                
            else:
                print(f"❌ Failed to test field validation: {response.status}")
    
    async def run_all_tests(self):
        """Run all test cases"""
        print("🚀 Starting Orders API Tests")
        print("=" * 60)
        
        # Setup authentication
        if not await self.setup():
            return
        
        try:
            # Test 1: List all orders
            all_orders = await self.test_list_all_orders()
            
            # Test 2: List orders by broker
            broker_orders = await self.test_list_orders_by_broker("zerodha")
            
            # Test 3: List orders by broker and strategy  
            filtered_orders = await self.test_list_orders_by_broker_and_strategy("zerodha", 1)
            
            # Test 4: Get order detail (if orders exist)
            if all_orders:
                first_order_id = all_orders[0].get('id')
                await self.test_get_order_detail(first_order_id)
            
            # Test 5: Validate new fields
            await self.test_orders_field_validation()
            
            print(f"\n🎉 All tests completed!")
            print("=" * 60)
            
        except Exception as e:
            print(f"❌ Test execution failed: {e}")
            import traceback
            traceback.print_exc()
        
        finally:
            await self.cleanup()

async def main():
    """Main test runner"""
    test_client = OrdersAPITest()
    await test_client.run_all_tests()

if __name__ == "__main__":
    # Run the test
    asyncio.run(main())
