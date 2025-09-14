#!/usr/bin/env python3

"""
Test script for the enable_smart_levels field functionality
"""

import asyncio
import json
import aiohttp
from datetime import datetime

# Configuration
BASE_URL = "http://localhost:8001"
AUTH_ENDPOINT = f"{BASE_URL}/auth/login"
STRATEGIES_ENDPOINT = f"{BASE_URL}/strategies"

# Test credentials - update as needed
TEST_USER = {
    "username": "admin",
    "password": "admin123"
}

async def get_auth_token():
    """Get authentication token"""
    async with aiohttp.ClientSession() as session:
        async with session.post(AUTH_ENDPOINT, json=TEST_USER) as response:
            if response.status == 200:
                data = await response.json()
                return data.get("access_token")
            else:
                error_text = await response.text()
                print(f"Authentication failed: {response.status} - {error_text}")
                return None

async def create_test_strategy_and_symbol(session):
    """Create a test strategy and symbol for testing"""
    # Create a test strategy first (this might not work if there's no create strategy endpoint)
    # Let's check if we have any existing strategies first
    async with session.get(STRATEGIES_ENDPOINT) as response:
        if response.status == 200:
            strategies = await response.json()
            if strategies:
                strategy_id = strategies[0]["id"]
                print(f"   Found existing strategy ID: {strategy_id}")
                
                # Check if this strategy has symbols
                async with session.get(f"{STRATEGIES_ENDPOINT}/{strategy_id}/symbols") as symbols_response:
                    if symbols_response.status == 200:
                        symbols = await symbols_response.json()
                        if symbols:
                            symbol_id = symbols[0]["id"]
                            print(f"   Found existing symbol ID: {symbol_id}")
                            return strategy_id, symbol_id
                        else:
                            print("   No symbols found, need to create one")
                            # Need to create a symbol - but first we need a config
                            return strategy_id, None
                    else:
                        print(f"   Failed to get symbols: {symbols_response.status}")
                        return None, None
            else:
                print("   No strategies found in database")
                return None, None
        else:
            error_text = await response.text()
            print(f"   Failed to get strategies: {response.status} - {error_text}")
            return None, None

async def test_enable_smart_levels_endpoints():
    """Test the new enable_smart_levels endpoints"""
    
    # Get auth token
    token = await get_auth_token()
    if not token:
        print("Failed to get authentication token")
        return
    
    headers = {"Authorization": f"Bearer {token}"}
    
    async with aiohttp.ClientSession(headers=headers) as session:
        
        # 1. Get or create test strategy and symbol
        print("1. Getting or creating test strategy and symbol...")
        strategy_id, symbol_id = await create_test_strategy_and_symbol(session)
        
        if not strategy_id:
            print("   Could not find or create a strategy. Skipping test.")
            return
            
        if not symbol_id:
            print("   No symbols found for strategy. Let's try to understand the data structure...")
            # Let's check what configs exist for this strategy
            async with session.get(f"{STRATEGIES_ENDPOINT}/{strategy_id}/configs") as configs_response:
                if configs_response.status == 200:
                    configs = await configs_response.json()
                    if configs:
                        config_id = configs[0]["id"]
                        print(f"   Found config ID: {config_id}, creating test symbol...")
                        
                        # Create a test symbol
                        test_symbol_data = {
                            "strategy_id": strategy_id,
                            "symbol": "TEST_SYMBOL_FOR_SMART_LEVELS",
                            "segment": "EQ", 
                            "config_id": config_id,
                            "status": "active",
                            "lot_size": 1,
                            "margin_required": 1000.0,
                            "enable_smart_levels": False
                        }
                        
                        async with session.post(f"{STRATEGIES_ENDPOINT}/{strategy_id}/symbols", json=test_symbol_data) as create_response:
                            if create_response.status == 201:
                                result = await create_response.json()
                                symbol_id = result["id"]
                                print(f"   Created test symbol ID: {symbol_id}")
                            else:
                                error_text = await create_response.text()
                                print(f"   Failed to create test symbol: {create_response.status} - {error_text}")
                                return
                    else:
                        print("   No configs found for strategy. Cannot create symbol.")
                        return
                else:
                    print(f"   Failed to get configs: {configs_response.status}")
                    return
        
        # 2. Get strategy symbols
        print(f"2. Getting symbols for strategy {strategy_id}...")
        async with session.get(f"{STRATEGIES_ENDPOINT}/{strategy_id}/symbols") as response:
            if response.status == 200:
                symbols = await response.json()
                if symbols:
                    symbol_id = symbols[0]["id"]
                    current_smart_levels = symbols[0].get("enable_smart_levels", False)
                    print(f"   Using symbol ID: {symbol_id}")
                    print(f"   Current enable_smart_levels: {current_smart_levels}")
                else:
                    print("   No symbols found")
                    return
            else:
                print(f"   Failed to get symbols: {response.status}")
                return
        
        # 3. Test enable smart levels
        print(f"3. Testing enable smart levels for symbol {symbol_id}...")
        async with session.put(f"{STRATEGIES_ENDPOINT}/symbols/{symbol_id}/smart-levels/enable") as response:
            if response.status == 200:
                result = await response.json()
                print(f"   Success! enable_smart_levels: {result.get('enable_smart_levels')}")
            else:
                error_text = await response.text()
                print(f"   Failed: {response.status} - {error_text}")
        
        # 4. Test disable smart levels
        print(f"4. Testing disable smart levels for symbol {symbol_id}...")
        async with session.put(f"{STRATEGIES_ENDPOINT}/symbols/{symbol_id}/smart-levels/disable") as response:
            if response.status == 200:
                result = await response.json()
                print(f"   Success! enable_smart_levels: {result.get('enable_smart_levels')}")
            else:
                error_text = await response.text()
                print(f"   Failed: {response.status} - {error_text}")
        
        # 5. Test toggle smart levels
        print(f"5. Testing toggle smart levels for symbol {symbol_id}...")
        async with session.put(f"{STRATEGIES_ENDPOINT}/symbols/{symbol_id}/smart-levels/toggle") as response:
            if response.status == 200:
                result = await response.json()
                print(f"   Success! enable_smart_levels: {result.get('enable_smart_levels')}")
            else:
                error_text = await response.text()
                print(f"   Failed: {response.status} - {error_text}")
        
        # 6. Verify final state
        print(f"6. Verifying final state...")
        async with session.get(f"{STRATEGIES_ENDPOINT}/symbols/{symbol_id}") as response:
            if response.status == 200:
                result = await response.json()
                print(f"   Final enable_smart_levels: {result.get('enable_smart_levels')}")
            else:
                error_text = await response.text()
                print(f"   Failed to get symbol: {response.status} - {error_text}")

async def test_add_symbol_with_smart_levels():
    """Test adding a symbol with enable_smart_levels field"""
    
    # Get auth token
    token = await get_auth_token()
    if not token:
        print("Failed to get authentication token")
        return
    
    headers = {"Authorization": f"Bearer {token}"}
    
    async with aiohttp.ClientSession(headers=headers) as session:
        
        # Get a strategy to add symbol to
        async with session.get(STRATEGIES_ENDPOINT) as response:
            if response.status == 200:
                strategies = await response.json()
                if strategies:
                    strategy_id = strategies[0]["id"]
                    print(f"Testing add symbol with smart levels to strategy {strategy_id}")
                    
                    # Get a config for this strategy
                    async with session.get(f"{STRATEGIES_ENDPOINT}/{strategy_id}/configs") as configs_response:
                        if configs_response.status == 200:
                            configs = await configs_response.json()
                            if configs:
                                config_id = configs[0]["id"]
                                print(f"   Using config ID: {config_id}")
                            else:
                                print("   No configs found for strategy")
                                return
                        else:
                            print(f"   Failed to get configs: {configs_response.status}")
                            return
                else:
                    print("No strategies found")
                    return
            else:
                print(f"Failed to get strategies: {response.status}")
                return
        
        # Test adding symbol with enable_smart_levels=True
        symbol_data = {
            "strategy_id": strategy_id,
            "symbol": "TEST_SMART_SYMBOL",
            "segment": "EQ",
            "config_id": config_id,
            "status": "active",
            "lot_size": 1,
            "margin_required": 1000.0,
            "enable_smart_levels": True
        }
        
        print("Testing add symbol with enable_smart_levels=True...")
        async with session.post(f"{STRATEGIES_ENDPOINT}/{strategy_id}/symbols", json=symbol_data) as response:
            if response.status in [200, 201]:  # Accept both 200 and 201 as success
                result = await response.json()
                print(f"   Success! Symbol created with enable_smart_levels: {result.get('enable_smart_levels')}")
                
                # Clean up - delete the test symbol
                symbol_id = result.get("id")
                if symbol_id:
                    async with session.delete(f"{STRATEGIES_ENDPOINT}/symbols/{symbol_id}") as delete_response:
                        if delete_response.status == 200:
                            print("   Test symbol cleaned up successfully")
                        else:
                            print("   Failed to clean up test symbol")
            else:
                error_text = await response.text()
                print(f"   Failed: {response.status} - {error_text}")

if __name__ == "__main__":
    print("Testing enable_smart_levels functionality...")
    print("=" * 50)
    
    asyncio.run(test_enable_smart_levels_endpoints())
    
    print("\n" + "=" * 50)
    print("Testing add symbol with smart levels...")
    
    asyncio.run(test_add_symbol_with_smart_levels())
    
    print("\nTesting complete!")
