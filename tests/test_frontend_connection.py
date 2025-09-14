#!/usr/bin/env python3

"""
Test script to verify frontend can connect to API server
Tests authentication and Smart Levels endpoint
"""

import json
import requests

# Configuration - Using correct port 8001
BASE_URL = "http://localhost:8001"
AUTH_ENDPOINT = f"{BASE_URL}/auth/login"
SMART_LEVELS_ENDPOINT = f"{BASE_URL}/strategies/smart-levels/symbols"
STRATEGIES_ENDPOINT = f"{BASE_URL}/strategies/"

# Test credentials
TEST_USER = {
    "username": "admin",
    "password": "admin123"
}

def test_connection():
    """Test basic connection to API server"""
    try:
        response = requests.get(f"{BASE_URL}/health", timeout=5)
        print(f"✅ Server connection: {response.status_code}")
        if response.status_code == 200:
            print(f"📊 Health check response: {response.json()}")
        return True
    except requests.exceptions.RequestException as e:
        print(f"❌ Server connection failed: {e}")
        return False

def get_auth_token():
    """Get authentication token"""
    try:
        response = requests.post(AUTH_ENDPOINT, json=TEST_USER)
        if response.status_code == 200:
            data = response.json()
            token = data.get("access_token")
            print(f"✅ Authentication successful")
            print(f"🔑 Token: {token[:20]}...")
            return token
        else:
            print(f"❌ Authentication failed: {response.status_code} - {response.text}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"❌ Authentication request failed: {e}")
        return None

def test_strategies_endpoint(token):
    """Test strategies endpoint"""
    headers = {"Authorization": f"Bearer {token}"}
    
    try:
        response = requests.get(STRATEGIES_ENDPOINT, headers=headers)
        if response.status_code == 200:
            strategies = response.json()
            print(f"✅ Strategies endpoint: {response.status_code}")
            print(f"📊 Total strategies: {len(strategies)}")
            
            swing_strategies = [s for s in strategies if s.get('key') in ['SwingHighLowBuy', 'SwingHighLowSell']]
            print(f"🔄 Swing strategies: {len(swing_strategies)}")
            
            for strategy in swing_strategies:
                print(f"  • {strategy.get('name')} ({strategy.get('key')}) - ID: {strategy.get('id')}")
            
            return strategies
        else:
            print(f"❌ Strategies endpoint failed: {response.status_code} - {response.text}")
            return []
    except requests.exceptions.RequestException as e:
        print(f"❌ Strategies request failed: {e}")
        return []

def test_smart_levels_endpoint(token):
    """Test smart levels symbols endpoint"""
    headers = {"Authorization": f"Bearer {token}"}
    
    try:
        response = requests.get(SMART_LEVELS_ENDPOINT, headers=headers)
        if response.status_code == 200:
            result = response.json()
            print(f"✅ Smart Levels endpoint: {response.status_code}")
            print(f"📊 Total smart enabled symbols: {result.get('total_count', 0)}")
            
            symbols = result.get('symbols', [])
            if symbols:
                print("\n🔍 Smart Levels Enabled Symbols:")
                print("-" * 40)
                for symbol in symbols:
                    strategies_str = ", ".join(symbol.get('strategies', []))
                    print(f"  • {symbol['symbol']} (Strategies: {strategies_str})")
            else:
                print("\n⚠️  No symbols found with smart levels enabled")
            
            return result
        else:
            print(f"❌ Smart Levels endpoint failed: {response.status_code} - {response.text}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"❌ Smart Levels request failed: {e}")
        return None

def main():
    print("🧪 Testing Frontend Connection to API Server")
    print("=" * 50)
    
    # Test 1: Basic connection
    if not test_connection():
        print("\n❌ Cannot connect to server. Make sure API server is running on port 8001")
        return
    
    print("\n" + "=" * 50)
    
    # Test 2: Authentication
    token = get_auth_token()
    if not token:
        print("\n❌ Authentication failed. Check credentials or server configuration")
        return
    
    print("\n" + "=" * 50)
    
    # Test 3: Strategies endpoint
    strategies = test_strategies_endpoint(token)
    
    print("\n" + "=" * 50)
    
    # Test 4: Smart Levels endpoint
    smart_levels_result = test_smart_levels_endpoint(token)
    
    print("\n" + "=" * 50)
    print("🎉 All tests completed!")
    
    if smart_levels_result and smart_levels_result.get('total_count', 0) > 0:
        print(f"✅ API is working correctly - {smart_levels_result['total_count']} smart enabled symbols found")
        print("🔧 If frontend shows 0, check:")
        print("   1. Frontend API client is using correct port (8001)")
        print("   2. Authentication is working in browser")
        print("   3. CORS settings allow frontend requests")
        print("   4. Browser network tab for API call errors")
    else:
        print("⚠️  No smart enabled symbols found. To create test data:")
        print("   1. Add some symbols to swing strategies")
        print("   2. Enable smart levels for those symbols")

if __name__ == "__main__":
    main()
