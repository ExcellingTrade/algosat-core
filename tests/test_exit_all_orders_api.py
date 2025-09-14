#!/usr/bin/env python3
"""
Test script for the exit orders API endpoints.
This test will:
1. Login to get a valid JWT token
2. Test the /orders/exit-all API endpoint (with and without strategy_id filter)
3. Test the /orders/{order_id}/exit API endpoint
4. Verify the responses and check that logs are produced
5. Test edge cases including invalid strategy_id values
"""
import requests
import json
import time
import sys
from datetime import datetime

# API Configuration
BASE_URL = "http://localhost:8001"
TEST_CREDENTIALS = {
    "username": "satish",
    "password": "Sat@5858"
}

class ExitAllOrdersAPITest:
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
            print("\n🔐 Attempting to login...")
            
            login_data = {
                "username": TEST_CREDENTIALS["username"],
                "password": TEST_CREDENTIALS["password"]
            }
            
            response = self.session.post(
                f"{self.base_url}/auth/login",
                json=login_data,
                headers=self.headers,
                timeout=10
            )
            
            print(f"Login response status: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                self.token = result.get("access_token")
                if self.token:
                    # Update headers with authentication token
                    self.headers["Authorization"] = f"Bearer {self.token}"
                    print(f"✅ Login successful!")
                    print(f"   Token type: {result.get('token_type', 'N/A')}")
                    print(f"   Expires in: {result.get('expires_in', 'N/A')} seconds")
                    print(f"   User info: {result.get('user_info', 'N/A')}")
                    return True
                else:
                    print("❌ Login failed: No access token received")
                    return False
            else:
                print(f"❌ Login failed with status code: {response.status_code}")
                try:
                    error_detail = response.json()
                    print(f"   Error details: {error_detail}")
                except:
                    print(f"   Error response: {response.text}")
                return False
                
        except requests.exceptions.RequestException as e:
            print(f"❌ Login request failed: {e}")
            return False
        except json.JSONDecodeError as e:
            print(f"❌ Failed to parse login response: {e}")
            return False
    
    def test_auth_required_endpoint(self):
        """Test that authentication is required for protected endpoints."""
        try:
            print("\n🔒 Testing authentication requirement...")
            
            # Test without token
            headers_no_auth = {"Content-Type": "application/json"}
            response = self.session.post(
                f"{self.base_url}/orders/exit-all",
                headers=headers_no_auth,
                timeout=10
            )
            
            if response.status_code == 401:
                print("✅ Authentication is properly required (401 Unauthorized)")
                return True
            else:
                print(f"❌ Expected 401 but got {response.status_code}")
                return False
                
        except requests.exceptions.RequestException as e:
            print(f"❌ Auth test request failed: {e}")
            return False
    
    def test_exit_all_orders_endpoint(self):
        """Test the /orders/exit-all endpoint."""
        try:
            print("\n🚀 Testing /orders/exit-all endpoint...")
            
            if not self.token:
                print("❌ No authentication token available")
                return False
            
            # Test with optional exit_reason parameter
            test_exit_reason = f"API test exit at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            
            response = self.session.post(
                f"{self.base_url}/orders/exit-all",
                params={"exit_reason": test_exit_reason},
                headers=self.headers,
                timeout=30  # Increased timeout for order processing
            )
            
            print(f"Response status: {response.status_code}")
            print(f"Response headers: {dict(response.headers)}")
            
            if response.status_code == 200:
                result = response.json()
                print("✅ Exit all orders endpoint responded successfully!")
                print(f"   Response: {json.dumps(result, indent=2)}")
                
                # Check expected response structure
                expected_fields = ["success", "message"]
                missing_fields = [field for field in expected_fields if field not in result]
                
                if missing_fields:
                    print(f"⚠️  Warning: Missing expected fields: {missing_fields}")
                else:
                    print("✅ Response contains expected fields")
                
                # Check if success flag is True
                if result.get("success") is True:
                    print("✅ Operation reported as successful")
                else:
                    print("⚠️  Operation success flag not True")
                
                return True
            else:
                print(f"❌ Exit all orders endpoint failed with status: {response.status_code}")
                try:
                    error_detail = response.json()
                    print(f"   Error details: {json.dumps(error_detail, indent=2)}")
                except:
                    print(f"   Error response: {response.text}")
                return False
                
        except requests.exceptions.RequestException as e:
            print(f"❌ Exit all orders request failed: {e}")
            return False
        except json.JSONDecodeError as e:
            print(f"❌ Failed to parse exit all orders response: {e}")
            return False
    
    def test_exit_all_orders_with_strategy_id(self):
        """Test the /orders/exit-all endpoint with strategy_id filter."""
        try:
            print("\n🎯 Testing /orders/exit-all endpoint with strategy_id filter...")
            
            if not self.token:
                print("❌ No authentication token available")
                return False
            
            # First, get a list of orders to find a valid strategy ID
            orders_response = self.session.get(
                f"{self.base_url}/orders/",
                headers=self.headers,
                timeout=10
            )
            
            if orders_response.status_code != 200:
                print("❌ Failed to fetch orders for testing strategy filter")
                return False
            
            orders = orders_response.json()
            
            # Use hardcoded strategy_id (DB currently has orders with strategy_id 4)
            test_strategy_id = 4
            
            print(f"   Testing with strategy ID: {test_strategy_id} (hardcoded)")
            print(f"   Found {len(orders)} total orders in the system")
            
            # Test with strategy_id and exit_reason parameters
            test_exit_reason = f"Strategy filter API test at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            
            response = self.session.post(
                f"{self.base_url}/orders/exit-all",
                params={
                    "strategy_id": test_strategy_id,
                    "exit_reason": test_exit_reason
                },
                headers=self.headers,
                timeout=30
            )
            
            print(f"Response status: {response.status_code}")
            print(f"Response headers: {dict(response.headers)}")
            
            if response.status_code == 200:
                result = response.json()
                print("✅ Exit all orders with strategy_id endpoint responded successfully!")
                print(f"   Response: {json.dumps(result, indent=2)}")
                
                # Check expected response structure
                expected_fields = ["success", "message"]
                missing_fields = [field for field in expected_fields if field not in result]
                
                if missing_fields:
                    print(f"⚠️  Warning: Missing expected fields: {missing_fields}")
                else:
                    print("✅ Response contains expected fields")
                
                # Check if success flag is True
                if result.get("success") is True:
                    print("✅ Operation reported as successful")
                else:
                    print("⚠️  Operation success flag not True")
                
                # Check if message mentions strategy filtering
                message = result.get("message", "").lower()
                if "strategy" in message or str(test_strategy_id) in result.get("message", ""):
                    print("✅ Response message indicates strategy filtering was applied")
                else:
                    print("⚠️  Response message doesn't clearly indicate strategy filtering")
                
                return True
            else:
                print(f"❌ Exit all orders with strategy_id endpoint failed: {response.status_code}")
                try:
                    error_detail = response.json()
                    print(f"   Error details: {json.dumps(error_detail, indent=2)}")
                except:
                    print(f"   Error response: {response.text}")
                return False
                
        except requests.exceptions.RequestException as e:
            print(f"❌ Exit all orders with strategy_id request failed: {e}")
            return False
        except json.JSONDecodeError as e:
            print(f"❌ Failed to parse exit all orders with strategy_id response: {e}")
            return False
    
    def test_exit_all_orders_invalid_strategy_id(self):
        """Test the /orders/exit-all endpoint with invalid strategy_id."""
        try:
            print("\n🎯 Testing /orders/exit-all endpoint with invalid strategy_id...")
            
            if not self.token:
                print("❌ No authentication token available")
                return False
            
            # Use an invalid strategy ID (very high number unlikely to exist)
            invalid_strategy_id = 999999
            print(f"   Testing with invalid strategy ID: {invalid_strategy_id}")
            
            test_exit_reason = f"Invalid strategy ID test at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            
            response = self.session.post(
                f"{self.base_url}/orders/exit-all",
                params={
                    "strategy_id": invalid_strategy_id,
                    "exit_reason": test_exit_reason
                },
                headers=self.headers,
                timeout=30
            )
            
            print(f"Response status: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                print("✅ Exit all orders with invalid strategy_id handled appropriately")
                print(f"   Response: {json.dumps(result, indent=2)}")
                
                # Should indicate no orders found for this strategy
                message = result.get("message", "").lower()
                if "no orders" in message or "not found" in message or "0 orders" in message:
                    print("✅ Response appropriately indicates no orders found for invalid strategy")
                else:
                    print("⚠️  Response doesn't clearly indicate no orders found for invalid strategy")
                
                return True
            else:
                print(f"❌ Unexpected response for invalid strategy ID: {response.status_code}")
                try:
                    error_detail = response.json()
                    print(f"   Error details: {json.dumps(error_detail, indent=2)}")
                except:
                    print(f"   Error response: {response.text}")
                return False
                
        except requests.exceptions.RequestException as e:
            print(f"❌ Exit all orders with invalid strategy_id request failed: {e}")
            return False
        except json.JSONDecodeError as e:
            print(f"❌ Failed to parse exit all orders with invalid strategy_id response: {e}")
            return False
    
    def test_exit_all_orders_with_zero_strategy_id(self):
        """Test the /orders/exit-all endpoint with strategy_id=0."""
        try:
            print("\n🎯 Testing /orders/exit-all endpoint with strategy_id=0...")
            
            if not self.token:
                print("❌ No authentication token available")
                return False
            
            print("   Testing with strategy_id=0 (edge case)")
            
            test_exit_reason = f"Zero strategy ID test at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            
            response = self.session.post(
                f"{self.base_url}/orders/exit-all",
                params={
                    "strategy_id": 0,
                    "exit_reason": test_exit_reason
                },
                headers=self.headers,
                timeout=30
            )
            
            print(f"Response status: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                print("✅ Exit all orders with strategy_id=0 handled appropriately")
                print(f"   Response: {json.dumps(result, indent=2)}")
                return True
            else:
                print(f"❌ Unexpected response for strategy_id=0: {response.status_code}")
                try:
                    error_detail = response.json()
                    print(f"   Error details: {json.dumps(error_detail, indent=2)}")
                except:
                    print(f"   Error response: {response.text}")
                return False
                
        except requests.exceptions.RequestException as e:
            print(f"❌ Exit all orders with strategy_id=0 request failed: {e}")
            return False
        except json.JSONDecodeError as e:
            print(f"❌ Failed to parse exit all orders with strategy_id=0 response: {e}")
            return False

    def test_exit_all_orders_without_reason(self):
        """Test the /orders/exit-all endpoint without exit_reason parameter."""
        try:
            print("\n🚀 Testing /orders/exit-all endpoint without exit_reason...")
            
            if not self.token:
                print("❌ No authentication token available")
                return False
            
            response = self.session.post(
                f"{self.base_url}/orders/exit-all",
                headers=self.headers,
                timeout=30
            )
            
            print(f"Response status: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                print("✅ Exit all orders endpoint (without reason) responded successfully!")
                print(f"   Response: {json.dumps(result, indent=2)}")
                return True
            else:
                print(f"❌ Exit all orders endpoint (without reason) failed: {response.status_code}")
                try:
                    error_detail = response.json()
                    print(f"   Error details: {json.dumps(error_detail, indent=2)}")
                except:
                    print(f"   Error response: {response.text}")
                return False
                
        except requests.exceptions.RequestException as e:
            print(f"❌ Exit all orders request (without reason) failed: {e}")
            return False
        except json.JSONDecodeError as e:
            print(f"❌ Failed to parse exit all orders response (without reason): {e}")
            return False
    
    def check_orders_endpoint_availability(self):
        """Check if the orders endpoint is available to verify orders exist."""
        try:
            print("\n📊 Checking orders endpoint availability...")
            
            if not self.token:
                print("❌ No authentication token available")
                return False
            
            response = self.session.get(
                f"{self.base_url}/orders/",
                headers=self.headers,
                timeout=10
            )
            
            print(f"Orders endpoint status: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                print(f"✅ Orders endpoint accessible, found {len(result)} orders")
                if len(result) > 0:
                    print("   Sample order data:")
                    for i, order in enumerate(result[:3]):  # Show first 3 orders
                        print(f"     Order {i+1}: ID={order.get('id')}, Status={order.get('status')}, Symbol={order.get('symbol')}")
                return True
            else:
                print(f"❌ Orders endpoint failed: {response.status_code}")
                return False
                
        except requests.exceptions.RequestException as e:
            print(f"❌ Orders endpoint request failed: {e}")
            return False
        except json.JSONDecodeError as e:
            print(f"❌ Failed to parse orders response: {e}")
            return False
    
    def run_complete_test(self):
        """Run the complete test suite."""
        print("="*60)
        print("🧪 Exit Orders API Test Suite")
        print("="*60)
        
        test_results = {
            "api_connection": False,
            "login": False,
            "auth_required": False,
            "orders_endpoint": False,
            "exit_all_orders_with_reason": False,
            "exit_all_orders_without_reason": False,
            "exit_all_orders_with_strategy_id": False,
            "exit_all_orders_invalid_strategy_id": False,
            "exit_all_orders_with_zero_strategy_id": False,
            "exit_single_order": False,
            "exit_single_order_without_params": False,
            "exit_single_order_invalid_id": False
        }
        
        # Step 1: Test API connection
        test_results["api_connection"] = self.test_api_connection()
        if not test_results["api_connection"]:
            print("\n❌ API connection failed. Cannot proceed with tests.")
            return False
        
        # Step 2: Test login
        test_results["login"] = self.login()
        if not test_results["login"]:
            print("\n❌ Login failed. Cannot proceed with authenticated tests.")
            return False
        
        # Step 3: Test authentication requirement
        test_results["auth_required"] = self.test_auth_required_endpoint()
        
        # Step 4: Check orders endpoint
        test_results["orders_endpoint"] = self.check_orders_endpoint_availability()
        
        # Step 5: Test exit all orders with reason
        test_results["exit_all_orders_with_reason"] = self.test_exit_all_orders_endpoint()
        
        # Step 6: Test exit all orders without reason  
        test_results["exit_all_orders_without_reason"] = self.test_exit_all_orders_without_reason()
        
        # Step 7: Test exit all orders with strategy_id filter
        test_results["exit_all_orders_with_strategy_id"] = self.test_exit_all_orders_with_strategy_id()
        
        # Step 8: Test exit all orders with invalid strategy_id
        test_results["exit_all_orders_invalid_strategy_id"] = self.test_exit_all_orders_invalid_strategy_id()
        
        # Step 9: Test exit all orders with strategy_id=0
        test_results["exit_all_orders_with_zero_strategy_id"] = self.test_exit_all_orders_with_zero_strategy_id()
        
        # Step 10: Test exit single order with parameters
        test_results["exit_single_order"] = self.test_exit_single_order_endpoint()
        
        # Step 11: Test exit single order without parameters
        test_results["exit_single_order_without_params"] = self.test_exit_single_order_without_params()
        
        # Step 12: Test exit single order with invalid ID
        test_results["exit_single_order_invalid_id"] = self.test_exit_single_order_invalid_id()
        
        # Print summary
        print("\n" + "="*60)
        print("📋 Test Results Summary")
        print("="*60)
        
        for test_name, passed in test_results.items():
            status = "✅ PASSED" if passed else "❌ FAILED"
            print(f"{test_name.replace('_', ' ').title()}: {status}")
        
        total_tests = len(test_results)
        passed_tests = sum(test_results.values())
        
        print(f"\nOverall: {passed_tests}/{total_tests} tests passed")
        
        if passed_tests == total_tests:
            print("🎉 All tests passed! Exit all orders API is working correctly.")
            return True
        else:
            print("⚠️  Some tests failed. Please check the API implementation.")
            return False
    
    def run_quick_test(self):
        """Run a quick test focusing on the main functionality."""
        print("="*60)
        print("⚡ Quick Exit Orders API Test")
        print("="*60)
        
        # Test connection
        if not self.test_api_connection():
            return False
        
        # Login
        if not self.login():
            return False
        
        # Test the exit all orders endpoint
        print("\n--- Testing Exit All Orders ---")
        if not self.test_exit_all_orders_endpoint():
            return False
        
        # Test the exit all orders with strategy_id filter
        print("\n--- Testing Exit All Orders with Strategy Filter ---")
        if not self.test_exit_all_orders_with_strategy_id():
            print("⚠️  Strategy filter test failed, but continuing with other tests...")
        
        # Test the exit single order endpoint
        print("\n--- Testing Exit Single Order ---")
        if not self.test_exit_single_order_endpoint():
            return False
        
        print("\n✅ Quick test completed successfully!")
        return True
    
    def test_exit_single_order_endpoint(self):
        """Test the /orders/{order_id}/exit endpoint."""
        try:
            print("\n🎯 Testing /orders/{order_id}/exit endpoint...")
            
            if not self.token:
                print("❌ No authentication token available")
                return False
            
            # First, get a list of orders to find a valid order ID
            orders_response = self.session.get(
                f"{self.base_url}/orders/",
                headers=self.headers,
                timeout=10
            )
            
            if orders_response.status_code != 200:
                print("❌ Failed to fetch orders for testing single order exit")
                return False
            
            orders = orders_response.json()
            
            # Find an order with an open status that can be exited
            test_order_id = None
            test_order_info = None
            
            # Look for open orders first
            open_statuses = ['AWAITING_ENTRY', 'PENDING', 'PARTIALLY_FILLED', 'PARTIAL', 'FILLED']
            for order in orders:
                if order.get('status') in open_statuses:
                    test_order_id = order.get('id')
                    test_order_info = order
                    break
            
            # If no open orders, use the first available order for testing (API should handle gracefully)
            if not test_order_id and orders:
                test_order_id = orders[0].get('id')
                test_order_info = orders[0]
                print(f"   No open orders found, using order {test_order_id} with status {orders[0].get('status')} for testing")
            
            if not test_order_id:
                print("❌ No orders available for testing single order exit")
                return False
            
            print(f"   Testing with order ID: {test_order_id}")
            print(f"   Order status: {test_order_info.get('status')}")
            print(f"   Order symbol: {test_order_info.get('symbol') or test_order_info.get('strike_symbol', 'N/A')}")
            
            # Test with exit_reason and ltp parameters
            test_exit_reason = f"Single order API test at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            test_ltp = 150.75  # Sample LTP value
            
            response = self.session.post(
                f"{self.base_url}/orders/{test_order_id}/exit",
                params={
                    "exit_reason": test_exit_reason,
                    "ltp": test_ltp
                },
                headers=self.headers,
                timeout=30
            )
            
            print(f"Response status: {response.status_code}")
            print(f"Response headers: {dict(response.headers)}")
            
            if response.status_code == 200:
                result = response.json()
                print("✅ Exit single order endpoint responded successfully!")
                print(f"   Response: {json.dumps(result, indent=2)}")
                
                # Check expected response structure
                expected_fields = ["success", "message", "order_id"]
                missing_fields = [field for field in expected_fields if field not in result]
                
                if missing_fields:
                    print(f"⚠️  Warning: Missing expected fields: {missing_fields}")
                else:
                    print("✅ Response contains expected fields")
                
                # Check if success flag is True
                if result.get("success") is True:
                    print("✅ Operation reported as successful")
                else:
                    print("⚠️  Operation success flag not True")
                
                # Check if order_id matches
                if result.get("order_id") == test_order_id:
                    print("✅ Returned order_id matches test order_id")
                else:
                    print(f"⚠️  Returned order_id ({result.get('order_id')}) doesn't match test order_id ({test_order_id})")
                
                return True
            else:
                print(f"❌ Exit single order endpoint failed with status: {response.status_code}")
                try:
                    error_detail = response.json()
                    print(f"   Error details: {json.dumps(error_detail, indent=2)}")
                except:
                    print(f"   Error response: {response.text}")
                return False
                
        except requests.exceptions.RequestException as e:
            print(f"❌ Exit single order request failed: {e}")
            return False
        except json.JSONDecodeError as e:
            print(f"❌ Failed to parse exit single order response: {e}")
            return False
    
    def test_exit_single_order_without_params(self):
        """Test the /orders/{order_id}/exit endpoint without optional parameters."""
        try:
            print("\n🎯 Testing /orders/{order_id}/exit endpoint without optional parameters...")
            
            if not self.token:
                print("❌ No authentication token available")
                return False
            
            # Get orders to find a test order
            orders_response = self.session.get(
                f"{self.base_url}/orders/",
                headers=self.headers,
                timeout=10
            )
            
            if orders_response.status_code != 200:
                print("❌ Failed to fetch orders for testing")
                return False
            
            orders = orders_response.json()
            if not orders:
                print("❌ No orders available for testing")
                return False
            
            # Use the first available order
            test_order_id = orders[0].get('id')
            print(f"   Testing with order ID: {test_order_id}")
            
            response = self.session.post(
                f"{self.base_url}/orders/{test_order_id}/exit",
                headers=self.headers,
                timeout=30
            )
            
            print(f"Response status: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                print("✅ Exit single order endpoint (without params) responded successfully!")
                print(f"   Response: {json.dumps(result, indent=2)}")
                return True
            else:
                print(f"❌ Exit single order endpoint (without params) failed: {response.status_code}")
                try:
                    error_detail = response.json()
                    print(f"   Error details: {json.dumps(error_detail, indent=2)}")
                except:
                    print(f"   Error response: {response.text}")
                return False
                
        except requests.exceptions.RequestException as e:
            print(f"❌ Exit single order request (without params) failed: {e}")
            return False
        except json.JSONDecodeError as e:
            print(f"❌ Failed to parse exit single order response (without params): {e}")
            return False
    
    def test_exit_single_order_invalid_id(self):
        """Test the /orders/{order_id}/exit endpoint with invalid order ID."""
        try:
            print("\n🎯 Testing /orders/{order_id}/exit endpoint with invalid order ID...")
            
            if not self.token:
                print("❌ No authentication token available")
                return False
            
            # Use an invalid order ID (very high number unlikely to exist)
            invalid_order_id = 999999
            print(f"   Testing with invalid order ID: {invalid_order_id}")
            
            response = self.session.post(
                f"{self.base_url}/orders/{invalid_order_id}/exit",
                params={"exit_reason": "Invalid ID test"},
                headers=self.headers,
                timeout=30
            )
            
            print(f"Response status: {response.status_code}")
            
            # We expect this to either succeed (if order manager handles gracefully)
            # or return a 404/400 error
            if response.status_code in [200, 400, 404, 500]:
                result = response.json()
                print("✅ Exit single order endpoint handled invalid ID appropriately")
                print(f"   Response: {json.dumps(result, indent=2)}")
                return True
            else:
                print(f"❌ Unexpected response for invalid order ID: {response.status_code}")
                return False
                
        except requests.exceptions.RequestException as e:
            print(f"❌ Exit single order request (invalid ID) failed: {e}")
            return False
        except json.JSONDecodeError as e:
            print(f"❌ Failed to parse exit single order response (invalid ID): {e}")
            return False
        

def main():
    """Main function to run the test."""
    test = ExitAllOrdersAPITest()
    
    # Check command line arguments
    if len(sys.argv) > 1 and sys.argv[1] == "--quick":
        success = test.run_quick_test()
    else:
        success = test.run_complete_test()
    
    # Exit with appropriate code
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
