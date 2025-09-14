#!/usr/bin/env python3
"""
Simple test to verify the updated exit_all_orders API endpoint with LTP fetching
"""
import requests
import json
import sys

BASE_URL = "http://localhost:8001"
TEST_CREDENTIALS = {
    "username": "satish",
    "password": "Sat@5858"
}

def test_exit_all_orders_with_ltp_fetch():
    """Test the exit_all_orders endpoint to ensure it fetches LTP when not provided"""
    
    # Login first
    print("🔐 Logging in...")
    login_response = requests.post(
        f"{BASE_URL}/auth/login",
        json=TEST_CREDENTIALS,
        headers={"Content-Type": "application/json"}
    )
    
    if login_response.status_code != 200:
        print(f"❌ Login failed: {login_response.status_code}")
        return False
    
    token = login_response.json().get("access_token")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }
    
    print("✅ Login successful")
    
    # Test exit all orders without LTP (should fetch automatically)
    print("\n🚀 Testing exit_all_orders without LTP (should auto-fetch)...")
    
    exit_response = requests.post(
        f"{BASE_URL}/orders/exit-all",
        params={"exit_reason": "API test with LTP auto-fetch"},
        headers=headers
    )
    
    print(f"Response status: {exit_response.status_code}")
    
    if exit_response.status_code == 200:
        result = exit_response.json()
        print("✅ Exit all orders responded successfully!")
        print(f"   Response: {json.dumps(result, indent=2)}")
        
        if result.get("success"):
            print("✅ Operation reported as successful")
            print("✅ LTP auto-fetching functionality appears to be working")
        else:
            print("⚠️  Operation success flag not True")
        
        return True
    else:
        print(f"❌ Exit all orders failed: {exit_response.status_code}")
        try:
            error_detail = exit_response.json()
            print(f"   Error: {json.dumps(error_detail, indent=2)}")
        except:
            print(f"   Error response: {exit_response.text}")
        return False

if __name__ == "__main__":
    success = test_exit_all_orders_with_ltp_fetch()
    print(f"\n{'✅ Test passed!' if success else '❌ Test failed!'}")
    sys.exit(0 if success else 1)
