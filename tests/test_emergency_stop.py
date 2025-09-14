#!/usr/bin/env python3
"""
Test script to verify emergency stop functionality
"""
import requests
import json
import time

BASE_URL = "http://localhost:8000"

def test_emergency_stop():
    """Test the emergency stop functionality"""
    
    # Test exit all orders endpoint
    print("Testing exit all orders endpoint...")
    try:
        response = requests.post(f"{BASE_URL}/orders/exit-all", 
                               json={"exit_reason": "emergency_stop"})
        print(f"Exit all orders response: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"Success: {data.get('success', False)}")
            print(f"Message: {data.get('message', '')}")
        else:
            print(f"Error: {response.text}")
    except Exception as e:
        print(f"Error testing exit all orders: {e}")
    
    print("\n" + "="*50 + "\n")
    
    # Test strategy list endpoint
    print("Testing strategy list endpoint...")
    try:
        response = requests.get(f"{BASE_URL}/strategies/")
        print(f"Strategy list response: {response.status_code}")
        if response.status_code == 200:
            strategies = response.json()
            print(f"Total strategies: {len(strategies)}")
            active_strategies = [s for s in strategies if s.get('enabled', False)]
            print(f"Active strategies: {len(active_strategies)}")
            for strategy in active_strategies:
                print(f"  - {strategy.get('name', 'Unknown')} (ID: {strategy.get('id', 'N/A')})")
        else:
            print(f"Error: {response.text}")
    except Exception as e:
        print(f"Error testing strategy list: {e}")
    
    print("\n" + "="*50 + "\n")
    
    # Test orders list endpoint
    print("Testing orders list endpoint...")
    try:
        response = requests.get(f"{BASE_URL}/orders/")
        print(f"Orders list response: {response.status_code}")
        if response.status_code == 200:
            orders = response.json()
            print(f"Total orders: {len(orders)}")
            open_orders = [o for o in orders if o.get('status') in ['OPEN', 'PARTIALLY_FILLED']]
            print(f"Open orders: {len(open_orders)}")
            for order in open_orders:
                print(f"  - Order {order.get('id', 'N/A')}: {order.get('strike_symbol', 'N/A')} - {order.get('status', 'N/A')}")
        else:
            print(f"Error: {response.text}")
    except Exception as e:
        print(f"Error testing orders list: {e}")

if __name__ == "__main__":
    test_emergency_stop()
