#!/usr/bin/env python3
"""
Comprehensive test script for Smart Levels API functionality.
Tests the enhanced validation logic that allows same symbol with different smart_levels status.
"""

import asyncio
import aiohttp
import json

# Test configuration
BASE_URL = "http://localhost:8001"
USERNAME = "admin"
PASSWORD = "admin123"

async def authenticate():
    """Get authentication token"""
    async with aiohttp.ClientSession() as session:
        data = {
            "username": USERNAME,
            "password": PASSWORD
        }
        
        async with session.post(f"{BASE_URL}/auth/login", json=data) as response:
            if response.status == 200:
                result = await response.json()
                token = result.get("access_token")
                print(f"✅ Authentication successful, token: {token[:50]}...")
                return token
            else:
                text = await response.text()
                print(f"❌ Authentication failed: {response.status} - {text}")
                return None

async def get_strategies(headers):
    """Get all strategies"""
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{BASE_URL}/strategies", headers=headers) as response:
            if response.status == 200:
                return await response.json()
            else:
                text = await response.text()
                print(f"❌ Failed to get strategies: {response.status} - {text}")
                return []

async def get_strategy_symbols(session, headers, strategy_id):
    """Get symbols for a strategy"""
    async with session.get(f"{BASE_URL}/strategies/{strategy_id}/symbols", headers=headers) as response:
        if response.status == 200:
            return await response.json()
        else:
            text = await response.text()
            print(f"❌ Failed to get symbols: {response.status} - {text}")
            return []

async def add_symbol_to_strategy(session, headers, strategy_id, symbol, config_id, enable_smart_levels=False):
    """Add a symbol to a strategy"""
    data = {
        "strategy_id": strategy_id,  # Required field matching URL parameter
        "symbol": symbol,
        "config_id": config_id,
        "status": "active",
        "enable_smart_levels": enable_smart_levels
    }
    
    async with session.post(f"{BASE_URL}/strategies/{strategy_id}/symbols", headers=headers, json=data) as response:
        result_text = await response.text()
        if response.status in [200, 201]:
            try:
                return await response.json() if response.content_type == 'application/json' else json.loads(result_text)
            except:
                return {"status": "success", "text": result_text}
        else:
            return {"error": f"Status {response.status}: {result_text}"}

async def delete_symbol_from_strategy(session, headers, symbol_id):
    """Delete a symbol from strategy"""
    async with session.delete(f"{BASE_URL}/strategies/symbols/{symbol_id}", headers=headers) as response:
        return response.status

async def main():
    # Authenticate
    token = await authenticate()
    if not token:
        return
    
    headers = {"Authorization": f"Bearer {token}"}
    
    print(f"\n🧪 Testing Symbol + Smart Levels API")
    print("=" * 60)
    
    # Get strategies
    strategies = await get_strategies(headers)
    print(f"✅ Found {len(strategies)} strategies")
    
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
    
    async with aiohttp.ClientSession() as session:
        # Get existing symbols
        existing_symbols = await get_strategy_symbols(session, headers, strategy_id)
        print(f"✅ Strategy {strategy_id} has {len(existing_symbols)} symbols")
        
        # Find a config ID to use
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
        
        # Run tests
        for i, test_case in enumerate(test_cases, 1):
            print(f"\n{i}️⃣ Test: {test_case['name']}")
            print(f"   📝 Description: {test_case['description']}")
            
            result = await add_symbol_to_strategy(
                session, headers, strategy_id, 
                test_case['symbol'], config_id, 
                test_case['enable_smart_levels']
            )
            
            if 'error' in result:
                if test_case['should_succeed']:
                    print(f"   ❌ UNEXPECTED FAILURE: {result['error']}")
                else:
                    print(f"   ✅ Expected failure: {result['error']}")
            else:
                if test_case['should_succeed']:
                    symbol_id = result.get('id')
                    smart_levels = result.get('enable_smart_levels')
                    print(f"   ✅ SUCCESS: Added {test_case['symbol']} with smart_levels={smart_levels}")
                    print(f"   📋 Result: ID={symbol_id}, smart_levels={smart_levels}")
                    if symbol_id:
                        created_symbol_ids.append(symbol_id)
                else:
                    symbol_id = result.get('id')
                    smart_levels = result.get('enable_smart_levels')
                    print(f"   ⚠️  UNEXPECTED SUCCESS: This should have failed")
                    print(f"   📋 Result: ID={symbol_id}, smart_levels={smart_levels}")
                    if symbol_id:
                        created_symbol_ids.append(symbol_id)
        
        # Cleanup
        print(f"\n🧹 Cleaning up {len(created_symbol_ids)} test symbols...")
        for symbol_id in created_symbol_ids:
            status = await delete_symbol_from_strategy(session, headers, symbol_id)
            if status in [200, 204]:
                print(f"   ✅ Deleted symbol ID: {symbol_id}")
            else:
                print(f"   ⚠️  Failed to delete symbol ID: {symbol_id} (status: {status})")
        
        # Verify cleanup
        final_symbols = await get_strategy_symbols(session, headers, strategy_id)
        print(f"✅ Strategy {strategy_id} has {len(final_symbols)} symbols")
        
        print(f"\n🎯 Test Summary:")
        print(f"   - Strategy tested: {test_strategy['name']} (ID: {strategy_id})")
        print(f"   - Final symbol count: {len(final_symbols)}")
        print(f"   - Same symbol with different smart_levels: Should be ALLOWED ✅")
        print(f"   - Same symbol with same smart_levels: Should be BLOCKED ❌")
        print(f"   - New symbols: Should always be ALLOWED ✅")

if __name__ == "__main__":
    asyncio.run(main())
