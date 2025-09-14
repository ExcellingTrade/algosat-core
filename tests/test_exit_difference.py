#!/usr/bin/env python3
"""
Test script to compare the difference between test script and frontend calls
"""
import requests
import json
import time

# API Configuration
BASE_URL = "http://localhost:8001"
TEST_CREDENTIALS = {
    "username": "satish",
    "password": "Sat@5858"
}

def test_difference():
    session = requests.Session()
    headers = {"Content-Type": "application/json"}
    
    # Login
    login_response = session.post(
        f"{BASE_URL}/auth/login",
        json=TEST_CREDENTIALS,
        headers=headers
    )
    
    if login_response.status_code != 200:
        print(f"Login failed: {login_response.status_code}")
        return
    
    token = login_response.json()["access_token"]
    headers["Authorization"] = f"Bearer {token}"
    
    print("=" * 60)
    print("Testing exit-all endpoint calls")
    print("=" * 60)
    
    # Test 1: How test script calls it (using params)
    print("\n1. Testing with params (like test script):")
    response1 = session.post(
        f"{BASE_URL}/orders/exit-all",
        params={"exit_reason": "test_via_params"},
        headers=headers,
        timeout=30
    )
    print(f"   Status: {response1.status_code}")
    print(f"   Response: {response1.text}")
    
    # Test 2: How frontend calls it (using query params in URL)
    print("\n2. Testing with query params in URL (like frontend):")
    response2 = session.post(
        f"{BASE_URL}/orders/exit-all?exit_reason=test_via_url",
        headers=headers,
        timeout=30
    )
    print(f"   Status: {response2.status_code}")
    print(f"   Response: {response2.text}")
    
    # Test 3: Check if orders exist
    print("\n3. Checking orders:")
    orders_response = session.get(
        f"{BASE_URL}/orders/",
        headers=headers
    )
    if orders_response.status_code == 200:
        orders = orders_response.json()
        print(f"   Found {len(orders)} orders")
        open_orders = [o for o in orders if o.get("status") in ["OPEN", "PARTIALLY_FILLED", "AWAITING_ENTRY", "PENDING", 
                                                            "EXIT_TARGET_PENDING", "EXIT_STOPLOSS_PENDING", 
                                                            "EXIT_REVERSAL_PENDING", "EXIT_EOD_PENDING", 
                                                            "EXIT_EXPIRY_PENDING", "EXIT_ATOMIC_FAILED_PENDING",
                                                            "EXIT_MANUAL_PENDING", "EXIT_CLOSED_PENDING"]]
        print(f"   Open orders: {len(open_orders)}")
        for order in open_orders[:3]:
            print(f"     - Order {order.get('id')}: {order.get('status')} ({order.get('strike_symbol')})")
    
    # Test 4: Check if there are broker executions
    print("\n4. Checking broker executions for open orders:")
    if orders_response.status_code == 200:
        orders = orders_response.json()
        open_orders = [o for o in orders if o.get("status") in ["OPEN", "PARTIALLY_FILLED", "AWAITING_ENTRY", "PENDING", 
                                                            "EXIT_TARGET_PENDING", "EXIT_STOPLOSS_PENDING", 
                                                            "EXIT_REVERSAL_PENDING", "EXIT_EOD_PENDING", 
                                                            "EXIT_EXPIRY_PENDING", "EXIT_ATOMIC_FAILED_PENDING",
                                                            "EXIT_MANUAL_PENDING", "EXIT_CLOSED_PENDING"]]
        for order in open_orders:
            broker_execs = order.get("broker_executions", [])
            print(f"   Order {order.get('id')}: {len(broker_execs)} broker executions")
            for be in broker_execs:
                print(f"     - Broker: {be.get('broker_name')}, Status: {be.get('status')}, Qty: {be.get('executed_quantity')}")

if __name__ == "__main__":
    test_difference()
