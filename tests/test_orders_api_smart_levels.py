#!/usr/bin/env python3
"""
Test script for Orders API with Smart Levels support.
This script tests the orders API endpoints to ensure they include the smart_level_enabled field.
"""

import asyncio
import aiohttp
import json
from datetime import datetime

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
        
        async with self.session.post(f"{BASE_URL}/auth/login", json=login_data) as response:
            if response.status == 200:
                auth_response = await response.json()
                self.token = auth_response["access_token"]
                self.headers = {"Authorization": f"Bearer {self.token}"}
                print("✅ Authentication successful")
            else:
                print(f"❌ Authentication failed: {response.status}")
                print(await response.text())
                return False
        return True
    
    async def cleanup(self):
        """Cleanup HTTP session."""
        if self.session:
            await self.session.close()
    
    async def test_list_all_orders(self):
        """Test GET /orders endpoint."""
        print("\n🧪 Testing GET /orders (list all orders)...")
        
        try:
            async with self.session.get(f"{BASE_URL}/orders", headers=self.headers) as response:
                if response.status == 200:
                    orders = await response.json()
                    print(f"✅ Successfully retrieved {len(orders)} orders")
                    
                    if orders:
                        first_order = orders[0]
                        print(f"📋 First order fields: {list(first_order.keys())}")
                        
                        # Check for required fields
                        required_fields = ['id', 'order_id', 'smart_level_enabled']
                        missing_fields = [field for field in required_fields if field not in first_order]
                        
                        if missing_fields:
                            print(f"❌ Missing required fields: {missing_fields}")
                            return False
                        
                        # Check smart_level_enabled field specifically
                        smart_level_enabled = first_order.get('smart_level_enabled')
                        print(f"📊 smart_level_enabled field: {smart_level_enabled} (type: {type(smart_level_enabled)})")
                        
                        if smart_level_enabled is not None:
                            print("✅ smart_level_enabled field is present")
                        else:
                            print("⚠️  smart_level_enabled field is None")
                        
                        # Show sample order data
                        print(f"📄 Sample order data:")
                        print(f"   ID: {first_order.get('id')}")
                        print(f"   Symbol: {first_order.get('symbol')}")
                        print(f"   Strategy: {first_order.get('strategy_name')}")
                        print(f"   Status: {first_order.get('status')}")
                        print(f"   Smart Levels Enabled: {first_order.get('smart_level_enabled')}")
                        
                    else:
                        print("ℹ️  No orders found")
                    
                    return True
                else:
                    print(f"❌ Failed to retrieve orders: {response.status}")
                    error_text = await response.text()
                    print(f"Error details: {error_text}")
                    return False
                    
        except Exception as e:
            print(f"❌ Exception during orders retrieval: {e}")
            return False
    
    async def test_orders_by_broker(self):
        """Test GET /orders with broker filter."""
        print("\n🧪 Testing GET /orders?broker_name=zerodha...")
        
        try:
            params = {"broker_name": "zerodha"}
            async with self.session.get(f"{BASE_URL}/orders", params=params, headers=self.headers) as response:
                if response.status == 200:
                    orders = await response.json()
                    print(f"✅ Successfully retrieved {len(orders)} orders for broker 'zerodha'")
                    
                    if orders:
                        first_order = orders[0]
                        smart_level_enabled = first_order.get('smart_level_enabled')
                        print(f"📊 smart_level_enabled in filtered results: {smart_level_enabled}")
                    
                    return True
                else:
                    print(f"❌ Failed to retrieve orders by broker: {response.status}")
                    return False
                    
        except Exception as e:
            print(f"❌ Exception during broker-filtered orders retrieval: {e}")
            return False
    
    async def test_orders_by_symbol(self):
        """Test GET /orders/by-symbol/{symbol} endpoint."""
        print("\n🧪 Testing GET /orders/by-symbol/NIFTY50...")
        
        try:
            async with self.session.get(f"{BASE_URL}/orders/by-symbol/NIFTY50", headers=self.headers) as response:
                if response.status == 200:
                    orders = await response.json()
                    print(f"✅ Successfully retrieved {len(orders)} orders for symbol 'NIFTY50'")
                    
                    if orders:
                        first_order = orders[0]
                        smart_level_enabled = first_order.get('smart_level_enabled')
                        print(f"📊 smart_level_enabled in symbol-specific results: {smart_level_enabled}")
                        
                        # Check if order_id field is properly set
                        order_id = first_order.get('order_id')
                        id_field = first_order.get('id')
                        print(f"📋 order_id: {order_id}, id: {id_field}")
                        
                        if order_id != id_field:
                            print("❌ order_id and id fields don't match!")
                            return False
                        
                    return True
                else:
                    print(f"❌ Failed to retrieve orders by symbol: {response.status}")
                    error_text = await response.text()
                    print(f"Error details: {error_text}")
                    return False
                    
        except Exception as e:
            print(f"❌ Exception during symbol-specific orders retrieval: {e}")
            return False
    
    async def test_order_detail(self):
        """Test GET /orders/{order_id} endpoint."""
        print("\n🧪 Testing GET /orders/{order_id} (order detail)...")
        
        try:
            # First get a list of orders to find an order ID
            async with self.session.get(f"{BASE_URL}/orders", headers=self.headers) as response:
                if response.status == 200:
                    orders = await response.json()
                    if not orders:
                        print("ℹ️  No orders available for detail test")
                        return True
                    
                    order_id = orders[0]['id']
                    print(f"📋 Testing with order ID: {order_id}")
                    
                    # Get order detail
                    async with self.session.get(f"{BASE_URL}/orders/{order_id}", headers=self.headers) as detail_response:
                        if detail_response.status == 200:
                            order_detail = await detail_response.json()
                            print(f"✅ Successfully retrieved order detail")
                            print(f"📄 Order detail fields: {list(order_detail.keys())}")
                            return True
                        else:
                            print(f"❌ Failed to retrieve order detail: {detail_response.status}")
                            return False
                else:
                    print(f"❌ Failed to retrieve orders for detail test: {response.status}")
                    return False
                    
        except Exception as e:
            print(f"❌ Exception during order detail retrieval: {e}")
            return False
    
    async def test_schema_validation(self):
        """Test schema validation of OrderListResponse."""
        print("\n🧪 Testing schema validation...")
        
        try:
            # Import here to avoid import issues during script execution
            import sys
            import os
            sys.path.append(os.path.dirname(os.path.abspath(__file__)))
            
            from algosat.api.schemas import OrderListResponse
            
            # Test with sample data
            sample_order = {
                'id': 1,
                'order_id': 1,
                'strategy_name': 'Test Strategy',
                'symbol': 'NIFTY50',
                'strike_symbol': 'NIFTY50-CE-23000',
                'status': 'OPEN',
                'smart_level_enabled': True,
                'pnl': 100.0,
                'entry_price': 150.0,
                'lot_qty': 50,
                'broker_executions': []
            }
            
            order_response = OrderListResponse(**sample_order)
            print("✅ Schema validation passed")
            print(f"📋 smart_level_enabled in schema: {order_response.smart_level_enabled}")
            
            return True
            
        except Exception as e:
            print(f"❌ Schema validation failed: {e}")
            return False
    
    async def run_all_tests(self):
        """Run all test cases."""
        print("🚀 Starting Orders API Tests with Smart Levels support...")
        print(f"🔗 Base URL: {BASE_URL}")
        print(f"👤 Username: {TEST_USERNAME}")
        
        # Setup authentication
        if not await self.setup():
            print("❌ Setup failed, aborting tests")
            return False
        
        tests = [
            ("Schema Validation", self.test_schema_validation),
            ("List All Orders", self.test_list_all_orders),
            ("Orders by Broker", self.test_orders_by_broker),
            ("Orders by Symbol", self.test_orders_by_symbol),
            ("Order Detail", self.test_order_detail),
        ]
        
        results = []
        for test_name, test_func in tests:
            try:
                result = await test_func()
                results.append((test_name, result))
                if result:
                    print(f"✅ {test_name}: PASSED")
                else:
                    print(f"❌ {test_name}: FAILED")
            except Exception as e:
                print(f"💥 {test_name}: EXCEPTION - {e}")
                results.append((test_name, False))
        
        # Summary
        print("\n" + "="*50)
        print("📊 TEST SUMMARY")
        print("="*50)
        
        passed = sum(1 for _, result in results if result)
        total = len(results)
        
        for test_name, result in results:
            status = "✅ PASSED" if result else "❌ FAILED"
            print(f"{test_name}: {status}")
        
        print(f"\nOverall: {passed}/{total} tests passed")
        
        if passed == total:
            print("🎉 All tests passed!")
        else:
            print("⚠️  Some tests failed")
        
        await self.cleanup()
        return passed == total

async def main():
    """Main test runner."""
    test_runner = OrdersAPITest()
    success = await test_runner.run_all_tests()
    
    if success:
        print("\n🎯 All tests completed successfully!")
        exit(0)
    else:
        print("\n💥 Some tests failed!")
        exit(1)

if __name__ == "__main__":
    asyncio.run(main())
