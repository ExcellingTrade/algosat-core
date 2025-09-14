#!/usr/bin/env python3
"""
Test script to verify the Strategies API returns description field
"""
import requests
import json

# API Configuration
BASE_URL = "http://localhost:8001"  # Updated to correct port
TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VyX2lkIjoxLCJ1c2VybmFtZSI6ImFkbWluIiwicm9sZSI6InVzZXIiLCJlbWFpbCI6ImFkbWluQGFkbWluLmNvbSIsImV4cCI6MTc1MTAwMzg1NX0.TeQ9XeyCjA6J5Q4XvZLhgVaG6cQxGlkM5CCpn34vaoU"
headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json"
}

def test_strategies_api():
    """Test the strategies API endpoint and check for description field"""
    try:
        print("🔍 Testing Strategies API...")
        
        # Test strategies endpoint
        response = requests.get(f"{BASE_URL}/strategies", headers=headers)
        
        if response.status_code == 200:
            strategies = response.json()
            print(f"✅ Strategies API working! Found {len(strategies)} strategies")
            
            # Check if description field is present in response
            description_found = False
            for strategy in strategies:
                print(f"  📊 Strategy: {strategy.get('name', 'Unknown')} (ID: {strategy.get('id')})")
                print(f"      Key: {strategy.get('key', 'Unknown')}")
                print(f"      Description: {strategy.get('description', 'None')}")
                print(f"      Enabled: {strategy.get('enabled', False)}")
                print(f"      Order Type: {strategy.get('order_type', 'Unknown')}")
                print(f"      Product Type: {strategy.get('product_type', 'Unknown')}")
                print("      ---")
                
                if 'description' in strategy:
                    description_found = True
            
            if description_found:
                print("✅ Description field is present in API response!")
            else:
                print("❌ Description field is missing from API response!")
            
            # Test strategy symbols if we have strategies
            if strategies:
                strategy_id = strategies[0]['id']
                print(f"\n🔍 Testing Strategy Symbols for ID {strategy_id}...")
                
                symbols_response = requests.get(f"{BASE_URL}/strategies/{strategy_id}/symbols/", headers=headers)
                
                if symbols_response.status_code == 200:
                    symbols = symbols_response.json()
                    print(f"✅ Strategy Symbols API working! Found {len(symbols)} symbols")
                    
                    for symbol in symbols:
                        print(f"  📈 Symbol: {symbol.get('symbol', 'Unknown')} (ID: {symbol.get('id')}) - Status: {symbol.get('status', 'Unknown')}")
                else:
                    print(f"❌ Strategy Symbols API failed: {symbols_response.status_code} - {symbols_response.text}")
            
            return True
        else:
            print(f"❌ Strategies API failed: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Error testing Strategies API: {e}")
        return False

def test_health_check():
    """Test basic health check"""
    try:
        print("\n🔍 Testing Health Check...")
        response = requests.get(f"{BASE_URL}/health", headers=headers)
        
        if response.status_code == 200:
            health = response.json()
            print(f"✅ Health Check passed: {health.get('status', 'Unknown')}")
            return True
        else:
            print(f"❌ Health Check failed: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Error with Health Check: {e}")
        return False

if __name__ == "__main__":
    print("🧪 AlgoSat API Test - Strategies Verification")
    print("=" * 50)
    
    # Test health first
    if test_health_check():
        # Test strategies
        test_strategies_api()
    else:
        print("❌ Basic health check failed, skipping other tests")
    
    print("\n" + "=" * 50)
    print("🏁 Test completed!")
