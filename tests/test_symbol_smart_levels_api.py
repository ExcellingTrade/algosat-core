#!/usr/bin/env python3
"""
Test script to validate the updated symbol + smart levels API functionality
"""

import asyncio
import aiohttp
import json

async def test_add_symbol_api():
    """Test the updated add symbol API with smart levels validation"""
    
    base_url = "http://localhost:19840"
    
    async with aiohttp.ClientSession() as session:
        print("🧪 Testing Symbol + Smart Levels API")
        print("=" * 50)
        
        # Test case 1: Try to add NIFTY50 to SwingHighLowBuy with smart_levels=False
        # This should be allowed since NIFTY50 exists with smart_levels=True
        print("\n1️⃣ Test: Add NIFTY50 to SwingHighLowBuy with smart_levels=False")
        test_data = {
            "strategy_id": 3,  # SwingHighLowBuy
            "symbol": "NIFTY50",
            "config_id": 8,
            "status": "active", 
            "enable_smart_levels": False
        }
        
        try:
            async with session.post(f"{base_url}/api/strategies/3/symbols", json=test_data) as response:
                result = await response.json()
                if response.status == 200:
                    print(f"   ✅ SUCCESS: Added NIFTY50 with smart_levels=False")
                    print(f"   📋 Result: ID={result.get('id')}, smart_levels={result.get('enable_smart_levels')}")
                else:
                    print(f"   ❌ FAILED: {response.status} - {result}")
        except Exception as e:
            print(f"   ❌ ERROR: {e}")
        
        # Test case 2: Try to add NIFTY50 to SwingHighLowBuy with smart_levels=True  
        # This should fail since NIFTY50 already exists with smart_levels=True
        print("\n2️⃣ Test: Add NIFTY50 to SwingHighLowBuy with smart_levels=True (should fail)")
        test_data_dup = {
            "strategy_id": 3,  # SwingHighLowBuy
            "symbol": "NIFTY50", 
            "config_id": 8,
            "status": "active",
            "enable_smart_levels": True
        }
        
        try:
            async with session.post(f"{base_url}/api/strategies/3/symbols", json=test_data_dup) as response:
                result = await response.json()
                if response.status == 200:
                    print(f"   ⚠️  UNEXPECTED SUCCESS: This should have failed")
                    print(f"   📋 Result: ID={result.get('id')}, smart_levels={result.get('enable_smart_levels')}")
                else:
                    print(f"   ✅ EXPECTED FAILURE: {response.status} - {result}")
        except Exception as e:
            print(f"   ✅ EXPECTED ERROR: {e}")
        
        # Test case 3: Add a new symbol (TCS) to swing strategy
        print("\n3️⃣ Test: Add TCS to SwingHighLowBuy with smart_levels=True (new symbol)")
        test_data_new = {
            "strategy_id": 3,  # SwingHighLowBuy
            "symbol": "TCS",
            "config_id": 8,
            "status": "active",
            "enable_smart_levels": True
        }
        
        try:
            async with session.post(f"{base_url}/api/strategies/3/symbols", json=test_data_new) as response:
                result = await response.json()
                if response.status == 200:
                    print(f"   ✅ SUCCESS: Added TCS with smart_levels=True")
                    print(f"   📋 Result: ID={result.get('id')}, smart_levels={result.get('enable_smart_levels')}")
                    
                    # Clean up: delete the test symbol
                    symbol_id = result.get('id')
                    if symbol_id:
                        print(f"   🧹 Cleaning up: Deleting test symbol ID={symbol_id}")
                        async with session.delete(f"{base_url}/api/strategies/symbols/{symbol_id}") as del_response:
                            if del_response.status == 200:
                                print(f"   ✅ Cleanup successful")
                            else:
                                print(f"   ⚠️  Cleanup failed: {del_response.status}")
                else:
                    print(f"   ❌ FAILED: {response.status} - {result}")
        except Exception as e:
            print(f"   ❌ ERROR: {e}")
        
        print("\n🎯 Test Summary:")
        print("   - Same symbol with different smart_levels should be allowed for swing strategies")
        print("   - Same symbol with same smart_levels should be blocked")
        print("   - New symbols should always be allowed")

if __name__ == "__main__":
    asyncio.run(test_add_symbol_api())
