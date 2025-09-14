#!/usr/bin/env python3

"""
Test script for the smart levels symbols endpoint
"""

import json
import requests

# Configuration
BASE_URL = "http://localhost:8001"
AUTH_ENDPOINT = f"{BASE_URL}/auth/login"
SMART_LEVELS_ENDPOINT = f"{BASE_URL}/strategies/smart-levels/symbols"

# Test credentials
TEST_USER = {
    "username": "admin",
    "password": "admin123"
}

def get_auth_token():
    """Get authentication token"""
    response = requests.post(AUTH_ENDPOINT, json=TEST_USER)
    if response.status_code == 200:
        data = response.json()
        return data.get("access_token")
    else:
        print(f"Authentication failed: {response.status_code} - {response.text}")
        return None

def test_smart_levels_symbols():
    """Test the new smart levels symbols endpoint"""
    
    # Get auth token
    token = get_auth_token()
    if not token:
        print("Failed to get authentication token")
        return
    
    headers = {"Authorization": f"Bearer {token}"}
    
    print("Testing smart levels symbols endpoint...")
    print("=" * 50)
    
    # Test the new endpoint
    response = requests.get(SMART_LEVELS_ENDPOINT, headers=headers)
    if response.status_code == 200:
        result = response.json()
        print(f"✅ Success! Status: {response.status_code}")
        print(f"📊 Total symbols found: {result.get('total_count', 0)}")
        
        symbols = result.get('symbols', [])
        if symbols:
            print("\n🔍 Smart Levels Enabled Symbols:")
            print("-" * 40)
            for symbol in symbols:
                strategies_str = ", ".join(symbol.get('strategies', []))
                print(f"  • {symbol['symbol']} (Strategies: {strategies_str})")
        else:
            print("\n⚠️  No symbols found with smart levels enabled")
            print("   Make sure you have symbols with enable_smart_levels=true")
            print("   in swinghighlowbuy or swinghighlowsell strategies")
        
        print(f"\n📋 Full Response:")
        print(json.dumps(result, indent=2))
        
    else:
        print(f"❌ Failed: {response.status_code}")
        print(f"Error: {response.text}")

if __name__ == "__main__":
    print("Testing Smart Levels Symbols API Endpoint...")
    test_smart_levels_symbols()
    print("\nTest complete!")
