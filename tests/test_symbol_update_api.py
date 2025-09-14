#!/usr/bin/env python3
"""
Test script to verify the Symbol Update API endpoint
"""
import requests
import json

# API Configuration
BASE_URL = "http://localhost:8001"
TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VyX2lkIjoxLCJ1c2VybmFtZSI6ImFkbWluIiwicm9sZSI6InVzZXIiLCJlbWFpbCI6ImFkbWluQGFkbWluLmNvbSIsImV4cCI6MTc1MTAwMzg1NX0.TeQ9XeyCjA6J5Q4XvZLhgVaG6cQxGlkM5CCpn34vaoU"
headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json"
}

def test_symbol_update_api():
    """Test the symbol update API endpoint"""
    try:
        print("🔍 Testing Symbol Update API...")
        
        # First, get some symbols to test with
        strategies_response = requests.get(f"{BASE_URL}/strategies", headers=headers)
        if strategies_response.status_code != 200:
            print(f"❌ Failed to get strategies: {strategies_response.status_code}")
            return False
            
        strategies = strategies_response.json()
        if not strategies:
            print("❌ No strategies found")
            return False
            
        strategy_id = strategies[0]['id']
        print(f"📊 Using strategy ID: {strategy_id}")
        
        # Get symbols for this strategy
        symbols_response = requests.get(f"{BASE_URL}/strategies/{strategy_id}/symbols/", headers=headers)
        if symbols_response.status_code != 200:
            print(f"❌ Failed to get symbols: {symbols_response.status_code}")
            return False
            
        symbols = symbols_response.json()
        if not symbols:
            print("❌ No symbols found for this strategy")
            return False
            
        symbol_id = symbols[0]['id']
        current_config_id = symbols[0]['config_id']
        print(f"📈 Using symbol ID: {symbol_id}, current config: {current_config_id}")
        
        # Get available configs for this strategy
        configs_response = requests.get(f"{BASE_URL}/strategies/{strategy_id}/configs/", headers=headers)
        if configs_response.status_code != 200:
            print(f"❌ Failed to get configs: {configs_response.status_code}")
            return False
            
        configs = configs_response.json()
        if len(configs) < 2:
            print("❌ Need at least 2 configs to test symbol update")
            return False
            
        # Find a different config to switch to
        new_config_id = None
        for config in configs:
            if config['id'] != current_config_id:
                new_config_id = config['id']
                break
                
        if not new_config_id:
            print("❌ No different config found to test with")
            return False
            
        print(f"🔄 Updating symbol {symbol_id} from config {current_config_id} to config {new_config_id}")
        
        # Test the update endpoint
        update_data = {"config_id": new_config_id}
        update_response = requests.put(f"{BASE_URL}/strategies/symbols/{symbol_id}", 
                                     headers=headers, 
                                     json=update_data)
        
        if update_response.status_code == 200:
            updated_symbol = update_response.json()
            print(f"✅ Symbol update successful!")
            print(f"   Symbol ID: {updated_symbol.get('id')}")
            print(f"   New Config ID: {updated_symbol.get('config_id')}")
            print(f"   Symbol: {updated_symbol.get('symbol')}")
            print(f"   Status: {updated_symbol.get('status')}")
            
            # Verify the change by getting the symbol again
            verify_response = requests.get(f"{BASE_URL}/strategies/{strategy_id}/symbols/", headers=headers)
            if verify_response.status_code == 200:
                updated_symbols = verify_response.json()
                updated_symbol_data = next((s for s in updated_symbols if s['id'] == symbol_id), None)
                if updated_symbol_data and updated_symbol_data['config_id'] == new_config_id:
                    print("✅ Update verified successfully!")
                else:
                    print("❌ Update verification failed")
            
            # Revert the change back to original config
            revert_data = {"config_id": current_config_id}
            revert_response = requests.put(f"{BASE_URL}/strategies/symbols/{symbol_id}", 
                                         headers=headers, 
                                         json=revert_data)
            if revert_response.status_code == 200:
                print(f"✅ Reverted symbol back to original config {current_config_id}")
            else:
                print(f"⚠️  Failed to revert symbol: {revert_response.status_code}")
            
            return True
        else:
            print(f"❌ Symbol update failed: {update_response.status_code} - {update_response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Error testing Symbol Update API: {e}")
        return False

if __name__ == "__main__":
    print("🧪 AlgoSat API Test - Symbol Update Verification")
    print("=" * 60)
    
    success = test_symbol_update_api()
    
    print("\n" + "=" * 60)
    if success:
        print("🏁 Symbol Update API test completed successfully!")
    else:
        print("❌ Symbol Update API test failed!")
