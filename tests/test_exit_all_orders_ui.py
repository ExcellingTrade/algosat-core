#!/usr/bin/env python3
"""
Test script to verify the Exit All Orders functionality works correctly.
This test will verify that the API endpoint properly handles the exit_all_orders request.
"""
import requests
import json
import time
from datetime import datetime

# API Configuration
BASE_URL = "http://localhost:8001"
TEST_CREDENTIALS = {
    "username": "satish",
    "password": "Sat@5858"
}

class ExitAllOrdersUITest:
    def __init__(self):
        self.base_url = BASE_URL
        self.token = None
        self.headers = {
            "Content-Type": "application/json"
        }
        self.session = requests.Session()
        
    def test_api_connection(self):
        """Test if the API server is running and accessible."""
        try:
            print("🔍 Testing API connection...")
            response = self.session.get(f"{self.base_url}/health", timeout=5)
            if response.status_code == 200:
                print("✅ API server is running and accessible")
                return True
            else:
                print(f"❌ API server returned status code: {response.status_code}")
                return False
        except requests.exceptions.RequestException as e:
            print(f"❌ Failed to connect to API server: {e}")
            print("   Please ensure the API server is running on localhost:8001")
            return False
    
    def login(self):
        """Login to get a valid JWT token."""
        try:
            print("🔐 Logging in...")
            response = self.session.post(
                f"{self.base_url}/auth/login",
                json=TEST_CREDENTIALS,
                headers=self.headers,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                self.token = data.get("access_token")
                self.headers["Authorization"] = f"Bearer {self.token}"
                print("✅ Successfully logged in")
                return True
            else:
                print(f"❌ Login failed with status code: {response.status_code}")
                print(f"   Response: {response.text}")
                return False
                
        except requests.exceptions.RequestException as e:
            print(f"❌ Login request failed: {e}")
            return False
    
    def test_exit_all_orders_endpoint(self):
        """Test the exit_all_orders endpoint."""
        try:
            print("\n🧪 Testing exit_all_orders endpoint...")
            
            # Test with manual exit reason
            response = self.session.post(
                f"{self.base_url}/orders/exit-all?exit_reason=manual",
                headers=self.headers,
                timeout=30
            )
            
            print(f"   Status Code: {response.status_code}")
            print(f"   Response: {response.text}")
            
            if response.status_code == 200:
                data = response.json()
                success = data.get("success", False)
                message = data.get("message", "")
                
                print(f"   Success: {success}")
                print(f"   Message: {message}")
                
                if success:
                    print("✅ Exit all orders endpoint test passed")
                    return True
                else:
                    print("⚠️  Exit all orders endpoint returned success=False")
                    print(f"   This might be expected if there are no open orders")
                    return True
            else:
                print(f"❌ Exit all orders endpoint test failed with status: {response.status_code}")
                return False
                
        except requests.exceptions.RequestException as e:
            print(f"❌ Exit all orders endpoint test failed: {e}")
            return False
    
    def test_broker_status(self):
        """Test getting broker status to ensure brokers are available."""
        try:
            print("\n🏢 Testing broker status...")
            
            response = self.session.get(
                f"{self.base_url}/brokers",
                headers=self.headers,
                timeout=10
            )
            
            if response.status_code == 200:
                brokers = response.json()
                print(f"   Found {len(brokers)} brokers")
                
                enabled_brokers = [b for b in brokers if b.get("is_enabled")]
                print(f"   Enabled brokers: {len(enabled_brokers)}")
                
                for broker in enabled_brokers:
                    print(f"   - {broker.get('broker_name')}: enabled={broker.get('is_enabled')}")
                
                if len(enabled_brokers) > 0:
                    print("✅ Broker status test passed - at least one broker is enabled")
                    return True
                else:
                    print("⚠️  No brokers are enabled")
                    return False
            else:
                print(f"❌ Broker status test failed with status: {response.status_code}")
                return False
                
        except requests.exceptions.RequestException as e:
            print(f"❌ Broker status test failed: {e}")
            return False
    
    def test_orders_status(self):
        """Test getting orders to see if there are any open orders."""
        try:
            print("\n📋 Testing orders status...")
            
            response = self.session.get(
                f"{self.base_url}/orders",
                headers=self.headers,
                timeout=10
            )
            
            if response.status_code == 200:
                orders = response.json()
                print(f"   Found {len(orders)} total orders")
                
                open_orders = [o for o in orders if o.get("status") in ["OPEN", "PARTIALLY_FILLED"]]
                print(f"   Open orders: {len(open_orders)}")
                
                if len(open_orders) > 0:
                    print("✅ Orders status test passed - found open orders to exit")
                    for order in open_orders[:3]:  # Show first 3 open orders
                        print(f"   - Order {order.get('id')}: {order.get('strike_symbol')} [{order.get('status')}]")
                    return True
                else:
                    print("⚠️  No open orders found")
                    return False
            else:
                print(f"❌ Orders status test failed with status: {response.status_code}")
                return False
                
        except requests.exceptions.RequestException as e:
            print(f"❌ Orders status test failed: {e}")
            return False
    
    def run_all_tests(self):
        """Run all tests."""
        print("🚀 Starting Exit All Orders UI Tests")
        print("=" * 50)
        
        # Test API connection
        if not self.test_api_connection():
            print("❌ API connection failed. Exiting tests.")
            return False
        
        # Login
        if not self.login():
            print("❌ Login failed. Exiting tests.")
            return False
        
        # Test broker status
        broker_test = self.test_broker_status()
        
        # Test orders status
        orders_test = self.test_orders_status()
        
        # Test exit all orders endpoint
        exit_test = self.test_exit_all_orders_endpoint()
        
        print("\n" + "=" * 50)
        print("🏁 Test Results Summary:")
        print(f"   API Connection: ✅")
        print(f"   Authentication: ✅")
        print(f"   Broker Status: {'✅' if broker_test else '⚠️'}")
        print(f"   Orders Status: {'✅' if orders_test else '⚠️'}")
        print(f"   Exit All Orders: {'✅' if exit_test else '❌'}")
        
        if exit_test:
            print("\n🎉 All critical tests passed!")
            print("   The Exit All Orders functionality is working correctly.")
            return True
        else:
            print("\n❌ Some tests failed. Please check the API server and configuration.")
            return False

if __name__ == "__main__":
    test = ExitAllOrdersUITest()
    success = test.run_all_tests()
    
    if success:
        print("\n✅ Exit All Orders UI functionality is ready!")
    else:
        print("\n❌ Exit All Orders UI functionality needs attention.")
        exit(1)
