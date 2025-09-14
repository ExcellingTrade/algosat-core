#!/usr/bin/env python3

import requests
import json

def test_symbol_data():
    """Test that symbol data includes enable_smart_levels field"""
    
    # First, get a valid token
    login_data = {
        "username": "admin",
        "password": "admin123"
    }
    
    try:
        # Login to get token
        login_response = requests.post("http://localhost:8001/auth/login", json=login_data)
        
        if login_response.status_code != 200:
            print(f"❌ Login failed: {login_response.status_code}")
            print(login_response.text)
            return
            
        token = login_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        
        print("✅ Login successful, testing symbol data...")
        
        # Get strategies
        strategies_response = requests.get("http://localhost:8001/strategies/", headers=headers)
        
        if strategies_response.status_code != 200:
            print(f"❌ Failed to get strategies: {strategies_response.status_code}")
            return
            
        strategies = strategies_response.json()
        print(f"📊 Found {len(strategies)} strategies")
        
        # Test symbols for each strategy
        for strategy in strategies:
            print(f"\n🔍 Testing strategy: {strategy['name']} (ID: {strategy['id']}, Key: {strategy['key']})")
            
            symbols_response = requests.get(f"http://localhost:8001/strategies/{strategy['id']}/symbols/", headers=headers)
            
            if symbols_response.status_code != 200:
                print(f"  ❌ Failed to get symbols: {symbols_response.status_code}")
                continue
                
            symbols = symbols_response.json()
            print(f"  📋 Found {len(symbols)} symbols")
            
            for symbol in symbols:
                enable_smart_levels = symbol.get('enable_smart_levels', 'MISSING')
                print(f"    • {symbol['symbol']}: enable_smart_levels = {enable_smart_levels}")
                
                if enable_smart_levels == 'MISSING':
                    print(f"      ⚠️  WARNING: enable_smart_levels field is missing!")
                    print(f"      Available fields: {list(symbol.keys())}")
        
        print(f"\n✅ Symbol data test complete!")
        
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    test_symbol_data()
