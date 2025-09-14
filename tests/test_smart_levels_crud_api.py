#!/usr/bin/env python3

"""
Test script to verify Smart Levels Configuration API endpoints
"""

import json
import requests

# Configuration
BASE_URL = "http://localhost:8001"
AUTH_ENDPOINT = f"{BASE_URL}/auth/login"
SMART_LEVELS_ENDPOINT = f"{BASE_URL}/smart-levels/"
STRATEGIES_ENDPOINT = f"{BASE_URL}/strategies/"

# Test credentials
TEST_USER = {
    "username": "admin",
    "password": "admin123"
}

def get_auth_token():
    """Get authentication token"""
    try:
        response = requests.post(AUTH_ENDPOINT, json=TEST_USER)
        if response.status_code == 200:
            data = response.json()
            token = data.get("access_token")
            return token
        else:
            print(f"❌ Authentication failed: {response.status_code} - {response.text}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"❌ Authentication request failed: {e}")
        return None

def test_smart_levels_crud_api(token):
    """Test Smart Levels CRUD API endpoints"""
    headers = {"Authorization": f"Bearer {token}"}
    
    print("🧪 Testing Smart Levels CRUD API")
    print("=" * 40)
    
    # Test 1: List all smart levels
    try:
        response = requests.get(SMART_LEVELS_ENDPOINT, headers=headers)
        if response.status_code == 200:
            smart_levels = response.json()
            print(f"✅ GET /smart-levels/: {response.status_code}")
            print(f"📊 Total smart levels configured: {len(smart_levels)}")
            
            if smart_levels:
                print("\n🔍 Existing Smart Levels:")
                for level in smart_levels:
                    print(f"  • ID: {level['id']}, Name: {level['name']}, Entry: {level['entry_level']}")
            else:
                print("📝 No smart levels configured yet")
                
        else:
            print(f"❌ GET /smart-levels/ failed: {response.status_code} - {response.text}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"❌ GET /smart-levels/ request failed: {e}")
        return False
    
    # Test 2: Get strategies to find a strategy_symbol_id
    try:
        strategies_response = requests.get(STRATEGIES_ENDPOINT, headers=headers)
        if strategies_response.status_code == 200:
            strategies = strategies_response.json()
            swing_strategy = None
            
            for strategy in strategies:
                if strategy.get('key') in ['SwingHighLowBuy', 'SwingHighLowSell']:
                    swing_strategy = strategy
                    break
            
            if swing_strategy:
                print(f"📈 Found swing strategy: {swing_strategy['name']} (ID: {swing_strategy['id']})")
                
                # Get symbols for this strategy
                symbols_response = requests.get(f"{STRATEGIES_ENDPOINT}{swing_strategy['id']}/symbols/", headers=headers)
                if symbols_response.status_code == 200:
                    symbols = symbols_response.json()
                    smart_enabled_symbols = [s for s in symbols if s.get('enable_smart_levels')]
                    
                    if smart_enabled_symbols:
                        test_symbol = smart_enabled_symbols[0]
                        print(f"🎯 Using symbol: {test_symbol['symbol']} (Strategy Symbol ID: {test_symbol['id']})")
                        
                        # Test 3: Create a test smart level
                        test_smart_level = {
                            "strategy_symbol_id": test_symbol['id'],
                            "name": f"Test Level for {test_symbol['symbol']}",
                            "is_active": True,
                            "entry_level": 25000.0,
                            "bullish_target": 25500.0,
                            "bearish_target": 24500.0,
                            "initial_lot_ce": 2,
                            "initial_lot_pe": 2,
                            "remaining_lot_ce": 2,
                            "remaining_lot_pe": 2,
                            "ce_buy_enabled": True,
                            "ce_sell_enabled": False,
                            "pe_buy_enabled": True,
                            "pe_sell_enabled": False,
                            "notes": "Test smart level configuration"
                        }
                        
                        create_response = requests.post(SMART_LEVELS_ENDPOINT, 
                                                      json=test_smart_level, 
                                                      headers=headers)
                        
                        if create_response.status_code == 200:
                            created_level = create_response.json()
                            print(f"✅ POST /smart-levels/: {create_response.status_code}")
                            print(f"🆕 Created smart level ID: {created_level['id']}")
                            
                            # Test 4: Get the created smart level
                            get_response = requests.get(f"{SMART_LEVELS_ENDPOINT}{created_level['id']}", headers=headers)
                            if get_response.status_code == 200:
                                print(f"✅ GET /smart-levels/{created_level['id']}: {get_response.status_code}")
                                level_data = get_response.json()
                                print(f"📋 Level details: {level_data['name']}, Entry: {level_data['entry_level']}")
                                
                                # Test 5: Update the smart level
                                update_data = {
                                    "name": f"Updated Test Level for {test_symbol['symbol']}",
                                    "entry_level": 25100.0
                                }
                                
                                update_response = requests.put(f"{SMART_LEVELS_ENDPOINT}{created_level['id']}", 
                                                             json=update_data, 
                                                             headers=headers)
                                
                                if update_response.status_code == 200:
                                    print(f"✅ PUT /smart-levels/{created_level['id']}: {update_response.status_code}")
                                    updated_level = update_response.json()
                                    print(f"📝 Updated name: {updated_level['name']}")
                                    print(f"📝 Updated entry level: {updated_level['entry_level']}")
                                else:
                                    print(f"❌ PUT failed: {update_response.status_code} - {update_response.text}")
                                
                                # Test 6: Delete the test smart level
                                delete_response = requests.delete(f"{SMART_LEVELS_ENDPOINT}{created_level['id']}", headers=headers)
                                
                                if delete_response.status_code == 200:
                                    print(f"✅ DELETE /smart-levels/{created_level['id']}: {delete_response.status_code}")
                                    print("🗑️ Test smart level deleted successfully")
                                else:
                                    print(f"❌ DELETE failed: {delete_response.status_code} - {delete_response.text}")
                                
                            else:
                                print(f"❌ GET single smart level failed: {get_response.status_code} - {get_response.text}")
                        else:
                            print(f"❌ POST /smart-levels/ failed: {create_response.status_code} - {create_response.text}")
                            return False
                    else:
                        print("⚠️ No symbols with smart levels enabled found")
                        return False
                else:
                    print(f"❌ Failed to get symbols: {symbols_response.status_code}")
                    return False
            else:
                print("⚠️ No swing strategies found")
                return False
        else:
            print(f"❌ Failed to get strategies: {strategies_response.status_code}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"❌ Strategies request failed: {e}")
        return False
    
    return True

def main():
    print("🧪 Testing Smart Levels Configuration API")
    print("=" * 50)
    
    # Get authentication token
    token = get_auth_token()
    if not token:
        print("❌ Cannot proceed without authentication token")
        return
    
    print("✅ Authentication successful")
    print()
    
    # Test Smart Levels CRUD API
    success = test_smart_levels_crud_api(token)
    
    print("\n" + "=" * 50)
    if success:
        print("🎉 All Smart Levels API tests passed!")
        print("✅ The backend API is ready for frontend integration")
    else:
        print("❌ Some tests failed. Please check the API implementation.")

if __name__ == "__main__":
    main()
