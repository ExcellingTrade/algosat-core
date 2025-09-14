#!/usr/bin/env python3
"""
Test script to verify the risk limits API is working
"""
import requests
import json

BASE_URL = "http://localhost:8001"

def get_auth_token():
    """Get authentication token by logging in"""
    login_url = f"{BASE_URL}/auth/login"
    login_data = {
        "username": "admin",
        "password": "admin123"
    }
    
    try:
        response = requests.post(login_url, json=login_data)
        if response.status_code == 200:
            auth_data = response.json()
            access_token = auth_data.get('access_token')
            print("✅ Authentication successful!")
            return access_token
        else:
            print(f"❌ Login failed: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"❌ Login error: {e}")
        return None

def test_risk_limits_update():
    """Test updating broker risk limits"""
    token = get_auth_token()
    if not token:
        return
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    # First get brokers
    brokers_response = requests.get(f"{BASE_URL}/brokers/", headers=headers)
    if brokers_response.status_code != 200:
        print(f"❌ Failed to get brokers: {brokers_response.status_code}")
        return
    
    brokers = brokers_response.json()
    if not brokers:
        print("No brokers found")
        return
        
    # Test with first broker
    broker = brokers[0]
    broker_name = broker['broker_name']
    
    print(f"Testing risk limits update for broker: {broker_name}")
    
    # Test data
    test_data = {
        "max_loss": 25000.0,
        "max_profit": 75000.0
    }
    
    # Update broker
    update_url = f"{BASE_URL}/brokers/{broker_name}"
    response = requests.put(update_url, headers=headers, json=test_data)
    
    if response.status_code == 200:
        result = response.json()
        print(f"✅ Successfully updated risk limits!")
        print(f"Max Loss: ₹{result.get('max_loss', 'N/A')}")
        print(f"Max Profit: ₹{result.get('max_profit', 'N/A')}")
    else:
        print(f"❌ Failed to update risk limits: {response.status_code}")
        print(f"Response: {response.text}")

if __name__ == "__main__":
    test_risk_limits_update()
