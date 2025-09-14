#!/usr/bin/env python3
"""
Test script to validate the updated symbol + smart levels API functionality with authentication
"""

import asyncio
import aiohttp
import json

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
        try:
            async with session.post(AUTH_ENDPOINT, json=TEST_USER) as response:
                if response.status == 200:
                    data = await response.json()
                    token = data.get("access_token")
                    print(f"✅ Authentication successful, token: {token[:50]}...")
                    return token
                else:
                    error_text = await response.text()
                    print(f"❌ Authentication failed: {response.status} - {error_text}")
                    return None
        except Exception as e:
            print(f"❌ Authentication error: {e}")
            return None

async def get_strategies(session, headers):
    """Get list of strategies"""
    try:
        async with session.get(STRATEGIES_ENDPOINT, headers=headers) as response:
            if response.status == 200:
                strategies = await response.json()
                print(f"✅ Found {len(strategies)} strategies")
                return strategies
            else:
                error_text = await response.text()
                print(f"❌ Failed to get strategies: {response.status} - {error_text}")
                return []
    except Exception as e:
        print(f"❌ Error getting strategies: {e}")
        return []

async def get_strategy_symbols(session, headers, strategy_id):
    """Get symbols for a strategy"""
    try:
        async with session.get(f"{STRATEGIES_ENDPOINT}/{strategy_id}/symbols", headers=headers) as response:
            if response.status == 200:
                symbols = await response.json()
                print(f"✅ Strategy {strategy_id} has {len(symbols)} symbols")
                return symbols
            else:
                error_text = await response.text()
                print(f"❌ Failed to get symbols for strategy {strategy_id}: {response.status} - {error_text}")
                return []
    except Exception as e:
        print(f"❌ Error getting symbols: {e}")
        return []

async def add_symbol_to_strategy(session, headers, strategy_id, symbol_data):
    """Add a symbol to a strategy"""
    try:
        async with session.post(f"{STRATEGIES_ENDPOINT}/{strategy_id}/symbols", 
                               json=symbol_data, headers=headers) as response:
            result = await response.json()
            return response.status, result
    except Exception as e:
        print(f"❌ Error adding symbol: {e}")
        return 500, {"error": str(e)}

async def delete_symbol(session, headers, symbol_id):
    """Delete a symbol"""
    try:
        async with session.delete(f"{STRATEGIES_ENDPOINT}/symbols/{symbol_id}", headers=headers) as response:
            return response.status
    except Exception as e:
        print(f"❌ Error deleting symbol: {e}")
        return 500

async def test_smart_levels_api():
    """Test the smart levels functionality"""
    
    # Get authentication token
    token = await get_auth_token()
    if not token:
        print("❌ Cannot proceed without authentication token")
        return
    
    headers = {"Authorization": f"Bearer {token}"}
    
    async with aiohttp.ClientSession() as session:
        print("\n🧪 Testing Symbol + Smart Levels API")
        print("=" * 60)
        
        # Get strategies
        strategies = await get_strategies(session, headers)
        if not strategies:
            print("❌ No strategies found, cannot continue testing")
            return
        
        # Find swing and non-swing strategies
    swing_strategies = [s for s in strategies if 'swing' in s['name'].lower()]
    non_swing_strategies = [s for s in strategies if 'swing' not in s['name'].lower()]
    
    print(f"📊 Found {len(swing_strategies)} swing strategies and {len(non_swing_strategies)} non-swing strategies")
    print(f"🔍 Strategy details: {[(s['id'], s['name'], s.get('key', 'NO_KEY')) for s in strategies]}")
    
    if not swing_strategies:
        print("❌ No swing strategies found, cannot test smart levels functionality")
        return
    
    # Use the first swing strategy for testing
    test_strategy = swing_strategies[0]
    strategy_id = test_strategy['id']
    print(f"\n🎯 Testing with strategy: {test_strategy['name']} (ID: {strategy_id})")
    
    # Get existing symbols
    existing_symbols = await get_strategy_symbols(session, headers, strategy_id)
    
    # Find a config ID to use (get from existing symbols or use a default)
    config_id = 1  # Default
    if existing_symbols:
        config_id = existing_symbols[0].get('config_id', 1)
    
    print(f"📋 Using config_id: {config_id}")
    
    # Test cases
    test_cases = [
        {
            "name": "Add TEST_SYMBOL with smart_levels=True",
            "symbol": "TEST_SYMBOL",
            "enable_smart_levels": True,
            "should_succeed": True,
            "description": "New symbol should always be allowed"
        },
        {
            "name": "Add TEST_SYMBOL with smart_levels=False", 
            "symbol": "TEST_SYMBOL",
            "enable_smart_levels": False,
            "should_succeed": True,
            "description": "Same symbol with different smart_levels should be allowed"
        },
        {
            "name": "Add TEST_SYMBOL with smart_levels=True again",
            "symbol": "TEST_SYMBOL", 
            "enable_smart_levels": True,
            "should_succeed": False,
            "description": "Same symbol with same smart_levels should be blocked"
        },
            {
                "name": "Add ANOTHER_TEST with smart_levels=False",
                "symbol": "ANOTHER_TEST",
                "enable_smart_levels": False,
                "should_succeed": True,
                "description": "New symbol should always be allowed"
            }
        ]
        
        created_symbol_ids = []
        
        for i, test_case in enumerate(test_cases, 1):
            print(f"\n{i}️⃣ Test: {test_case['name']}")
            print(f"   📝 Description: {test_case['description']}")
            
            symbol_data = {
                "strategy_id": strategy_id,
                "symbol": test_case["symbol"],
                "config_id": config_id,
                "status": "active",
                "enable_smart_levels": test_case["enable_smart_levels"]
            }
            
            status, result = await add_symbol_to_strategy(session, headers, strategy_id, symbol_data)
            
            if test_case["should_succeed"]:
                if status == 200 or status == 201:
                    print(f"   ✅ SUCCESS: Added {test_case['symbol']} with smart_levels={test_case['enable_smart_levels']}")
                    print(f"   📋 Result: ID={result.get('id')}, smart_levels={result.get('enable_smart_levels')}")
                    if result.get('id'):
                        created_symbol_ids.append(result['id'])
                else:
                    print(f"   ❌ UNEXPECTED FAILURE: {status} - {result}")
            else:
                if status != 200 and status != 201:
                    print(f"   ✅ EXPECTED FAILURE: {status} - {result}")
                else:
                    print(f"   ⚠️  UNEXPECTED SUCCESS: This should have failed")
                    print(f"   📋 Result: ID={result.get('id')}, smart_levels={result.get('enable_smart_levels')}")
                    if result.get('id'):
                        created_symbol_ids.append(result['id'])
        
        # Clean up created symbols
        print(f"\n🧹 Cleaning up {len(created_symbol_ids)} test symbols...")
        for symbol_id in created_symbol_ids:
            status = await delete_symbol(session, headers, symbol_id)
            if status == 200:
                print(f"   ✅ Deleted symbol ID: {symbol_id}")
            else:
                print(f"   ⚠️  Failed to delete symbol ID: {symbol_id} (status: {status})")
        
        # Final verification - check symbols again
        final_symbols = await get_strategy_symbols(session, headers, strategy_id)
        
        print(f"\n🎯 Test Summary:")
        print(f"   - Strategy tested: {test_strategy['name']} (ID: {strategy_id})")
        print(f"   - Final symbol count: {len(final_symbols)}")
        print(f"   - Same symbol with different smart_levels: Should be ALLOWED ✅")
        print(f"   - Same symbol with same smart_levels: Should be BLOCKED ❌")
        print(f"   - New symbols: Should always be ALLOWED ✅")

if __name__ == "__main__":
    asyncio.run(test_smart_levels_api())
