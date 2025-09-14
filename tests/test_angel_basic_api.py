#!/usr/bin/env python3
"""
Test basic Angel API calls to check if the connection is working.
"""

import asyncio
import sys
import os

# Add the project root to the path
sys.path.insert(0, '/opt/algosat')

async def test_angel_basic_api():
    """Test basic Angel API functionality."""
    try:
        print("🚀 Testing Basic Angel API Calls")
        print("=" * 60)
        
        # Import required modules
        from algosat.brokers.angel import AngelWrapper
        
        # Create Angel broker instance
        angel_broker = AngelWrapper()
        await angel_broker.login()  # Initialize with credentials from DB
        
        print("✅ Angel broker authenticated successfully")
        
        # Test 1: Get profile (basic API call)
        print(f"\n🔄 Testing getProfile API call...")
        
        import asyncio
        loop = asyncio.get_running_loop()
        
        def _sync_profile():
            try:
                return angel_broker.smart_api.getProfile(angel_broker.refresh_token)
            except Exception as e:
                print(f"Profile API error: {e}")
                return None
                
        profile_response = await loop.run_in_executor(None, _sync_profile)
        print(f"Profile Response: {profile_response}")
        
        # Test 2: Get holdings (another basic API call)
        print(f"\n🔄 Testing getHolding API call...")
        
        def _sync_holdings():
            try:
                return angel_broker.smart_api.getHolding()
            except Exception as e:
                print(f"Holdings API error: {e}")
                return None
                
        holdings_response = await loop.run_in_executor(None, _sync_holdings)
        print(f"Holdings Response: {holdings_response}")
        
        # Test 3: Get RMS (Risk Management System) 
        print(f"\n🔄 Testing getRMS API call...")
        
        def _sync_rms():
            try:
                return angel_broker.smart_api.getRMS()
            except Exception as e:
                print(f"RMS API error: {e}")
                return None
                
        rms_response = await loop.run_in_executor(None, _sync_rms)
        print(f"RMS Response: {rms_response}")
        
        print("\n✅ Basic Angel API test completed!")
        
    except Exception as e:
        print(f"❌ Error during basic API test: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_angel_basic_api())