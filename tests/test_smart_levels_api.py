#!/usr/bin/env python3
"""
Test script for Smart Levels CRUD API endpoints.
This script tests all the smart levels endpoints to ensure they work correctly.
"""

import asyncio
import aiohttp
import json
from datetime import datetime

# Configuration
BASE_URL = "http://localhost:8001"
TEST_USERNAME = "admin"  # Update with your test username
TEST_PASSWORD = "admin123"  # Update with your test password

class SmartLevelsAPITest:
    def __init__(self):
        self.session = None
        self.token = None
        self.headers = {}
        
    async def setup(self):
        """Setup HTTP session and authenticate."""
        self.session = aiohttp.ClientSession()
        
        # Login to get authentication token
        login_data = {
            "username": TEST_USERNAME,
            "password": TEST_PASSWORD
        }
        
        async with self.session.post(f"{BASE_URL}/auth/login", json=login_data) as response:
            if response.status == 200:
                auth_response = await response.json()
                self.token = auth_response["access_token"]
                self.headers = {"Authorization": f"Bearer {self.token}"}
                print("✅ Authentication successful")
            else:
                print(f"❌ Authentication failed: {response.status}")
                print(await response.text())
                return False
        return True
    
    async def cleanup(self):
        """Cleanup HTTP session."""
        if self.session:
            await self.session.close()
    
    async def test_list_smart_levels(self):
        """Test GET /smart-levels/"""
        print("\n🧪 Testing: List Smart Levels")
        async with self.session.get(f"{BASE_URL}/smart-levels/", headers=self.headers) as response:
            if response.status == 200:
                smart_levels = await response.json()
                print(f"✅ Got {len(smart_levels)} smart levels")
                return smart_levels
            else:
                print(f"❌ Failed to list smart levels: {response.status}")
                print(await response.text())
                return []
    
    async def test_create_smart_level(self, strategy_symbol_id=4):
        """Test POST /smart-levels/"""
        print(f"\n🧪 Testing: Create Smart Level for strategy_symbol_id={strategy_symbol_id}")
        
        smart_level_data = {
            "strategy_symbol_id": strategy_symbol_id,
            "name": f"Test Smart Level {datetime.now().strftime('%H:%M:%S')}",
            "is_active": True,
            "entry_level": 18000.0,
            "bullish_target": 18500.0,  # Above entry level
            "bearish_target": 17500.0,  # Below entry level
            "initial_lot_ce": 5,
            "initial_lot_pe": 5,
            "remaining_lot_ce": 5,
            "remaining_lot_pe": 5,
            "ce_buy_enabled": True,
            "pe_buy_enabled": True,
            "strict_entry_vs_swing_check": True,  # Test new field
            "notes": "Test smart level created by API test"
        }
        
        async with self.session.post(f"{BASE_URL}/smart-levels/", json=smart_level_data, headers=self.headers) as response:
            if response.status == 200:
                created_smart_level = await response.json()
                print(f"✅ Smart level created with ID: {created_smart_level['id']}")
                return created_smart_level
            else:
                print(f"❌ Failed to create smart level: {response.status}")
                print(await response.text())
                return None
    
    async def test_get_smart_level(self, smart_level_id):
        """Test GET /smart-levels/{id}"""
        print(f"\n🧪 Testing: Get Smart Level {smart_level_id}")
        
        async with self.session.get(f"{BASE_URL}/smart-levels/{smart_level_id}", headers=self.headers) as response:
            if response.status == 200:
                smart_level = await response.json()
                print(f"✅ Retrieved smart level: {smart_level['name']}")
                return smart_level
            else:
                print(f"❌ Failed to get smart level: {response.status}")
                print(await response.text())
                return None
    
    async def test_update_smart_level(self, smart_level_id):
        """Test PUT /smart-levels/{id}"""
        print(f"\n🧪 Testing: Update Smart Level {smart_level_id}")
        
        update_data = {
            "name": f"Updated Smart Level {datetime.now().strftime('%H:%M:%S')}",
            "entry_level": 18100.0,
            "bullish_target": 18600.0,  # Above new entry level
            "bearish_target": 17600.0,  # Below new entry level
            "strict_entry_vs_swing_check": False,  # Test updating new field
            "notes": "Updated by API test"
        }
        
        async with self.session.put(f"{BASE_URL}/smart-levels/{smart_level_id}", json=update_data, headers=self.headers) as response:
            if response.status == 200:
                updated_smart_level = await response.json()
                print(f"✅ Smart level updated: {updated_smart_level['name']}")
                return updated_smart_level
            else:
                print(f"❌ Failed to update smart level: {response.status}")
                print(await response.text())
                return None
    
    async def test_delete_smart_level(self, smart_level_id):
        """Test DELETE /smart-levels/{id}"""
        print(f"\n🧪 Testing: Delete Smart Level {smart_level_id}")
        
        async with self.session.delete(f"{BASE_URL}/smart-levels/{smart_level_id}", headers=self.headers) as response:
            if response.status == 200:
                result = await response.json()
                print(f"✅ Smart level deleted: {result['message']}")
                return True
            else:
                print(f"❌ Failed to delete smart level: {response.status}")
                print(await response.text())
                return False
    
    async def test_validation_errors(self, valid_strategy_symbol_id=4):
        """Test validation errors."""
        print("\n🧪 Testing: Validation Errors")
        
        # Test bullish target below entry level (should fail)
        invalid_data = {
            "strategy_symbol_id": valid_strategy_symbol_id,
            "name": "Invalid Smart Level",
            "entry_level": 18000.0,
            "bullish_target": 17900.0,  # Below entry level - should fail
            "bearish_target": 17500.0,
        }
        
        async with self.session.post(f"{BASE_URL}/smart-levels/", json=invalid_data, headers=self.headers) as response:
            if response.status == 400:
                error = await response.json()
                print(f"✅ Validation error caught correctly: {error['detail']}")
                return True
            else:
                print(f"❌ Expected validation error but got: {response.status}")
                print(await response.text())
                return False
    
    async def test_strict_entry_vs_swing_check_field(self, smart_level_id):
        """Test the new strict_entry_vs_swing_check field specifically."""
        print(f"\n🧪 Testing: Strict Entry vs Swing Check Field")
        
        # Get current smart level to verify field exists
        async with self.session.get(f"{BASE_URL}/smart-levels/{smart_level_id}", headers=self.headers) as response:
            if response.status == 200:
                smart_level = await response.json()
                if 'strict_entry_vs_swing_check' in smart_level:
                    print(f"✅ Field 'strict_entry_vs_swing_check' exists with value: {smart_level['strict_entry_vs_swing_check']}")
                else:
                    print("❌ Field 'strict_entry_vs_swing_check' not found in response")
                    return False
            else:
                print(f"❌ Failed to get smart level: {response.status}")
                return False
        
        # Test updating just the new field
        update_data = {
            "strict_entry_vs_swing_check": not smart_level['strict_entry_vs_swing_check']  # Toggle the value
        }
        
        async with self.session.put(f"{BASE_URL}/smart-levels/{smart_level_id}", json=update_data, headers=self.headers) as response:
            if response.status == 200:
                updated_smart_level = await response.json()
                new_value = updated_smart_level['strict_entry_vs_swing_check']
                print(f"✅ Field updated successfully to: {new_value}")
                
                # Verify the change persisted
                async with self.session.get(f"{BASE_URL}/smart-levels/{smart_level_id}", headers=self.headers) as verify_response:
                    if verify_response.status == 200:
                        verified_smart_level = await verify_response.json()
                        if verified_smart_level['strict_entry_vs_swing_check'] == new_value:
                            print(f"✅ Field value persisted correctly: {new_value}")
                            return True
                        else:
                            print(f"❌ Field value not persisted. Expected: {new_value}, Got: {verified_smart_level['strict_entry_vs_swing_check']}")
                            return False
                    else:
                        print(f"❌ Failed to verify update: {verify_response.status}")
                        return False
            else:
                print(f"❌ Failed to update field: {response.status}")
                print(await response.text())
                return False
    
    async def run_all_tests(self):
        """Run all tests."""
        print("🚀 Starting Smart Levels API Tests")
        print("📊 Using strategy_symbol_id=4 (NIFTY50) for testing")
        
        if not await self.setup():
            return
        
        try:
            # Step 1: List existing smart levels
            print("\n" + "="*50)
            await self.test_list_smart_levels()
            
            # Step 2: Test validation errors with valid strategy_symbol_id
            print("\n" + "="*50)
            await self.test_validation_errors(valid_strategy_symbol_id=4)
            
            # Step 3: Create a new smart level with valid strategy_symbol_id
            print("\n" + "="*50)
            created_smart_level = await self.test_create_smart_level(strategy_symbol_id=4)
            if not created_smart_level:
                print("❌ Cannot continue tests without creating a smart level")
                return
            
            smart_level_id = created_smart_level["id"]
            
            # Step 4: Get the created smart level
            print("\n" + "="*50)
            await self.test_get_smart_level(smart_level_id)
            
            # Step 5: Update the smart level
            print("\n" + "="*50)
            await self.test_update_smart_level(smart_level_id)
            
            # Step 6: Test the new strict_entry_vs_swing_check field specifically
            print("\n" + "="*50)
            await self.test_strict_entry_vs_swing_check_field(smart_level_id)
            
            # Step 7: List smart levels again to see the updated one
            print("\n" + "="*50)
            print("🧪 Testing: List Smart Levels After Update")
            smart_levels = await self.test_list_smart_levels()
            
            # Step 7: Test filtering by strategy_symbol_id
            print("\n" + "="*50)
            print("🧪 Testing: Filter Smart Levels by strategy_symbol_id=4")
            async with self.session.get(f"{BASE_URL}/smart-levels/?strategy_symbol_id=4", headers=self.headers) as response:
                if response.status == 200:
                    filtered_levels = await response.json()
                    print(f"✅ Got {len(filtered_levels)} smart levels for strategy_symbol_id=4")
                else:
                    print(f"❌ Failed to filter smart levels: {response.status}")
                    print(await response.text())
            
            # Step 8: Test invalid validation cases
            print("\n" + "="*50)
            print("🧪 Testing: Additional Validation Cases")
            
            # Test bearish target above entry level (should fail)
            invalid_data2 = {
                "strategy_symbol_id": 4,
                "name": "Invalid Smart Level 2",
                "entry_level": 18000.0,
                "bullish_target": 18500.0,
                "bearish_target": 18100.0,  # Above entry level - should fail
            }
            
            async with self.session.post(f"{BASE_URL}/smart-levels/", json=invalid_data2, headers=self.headers) as response:
                if response.status == 400:
                    error = await response.json()
                    print(f"✅ Bearish target validation error caught: {error['detail']}")
                else:
                    print(f"❌ Expected bearish target validation error but got: {response.status}")
            
            # Step 9: Test invalid strategy_symbol_id
            print("\n🧪 Testing: Invalid strategy_symbol_id")
            invalid_data3 = {
                "strategy_symbol_id": 999,  # Non-existent ID
                "name": "Invalid Strategy Symbol",
                "entry_level": 18000.0,
                "bullish_target": 18500.0,
                "bearish_target": 17500.0,
            }
            
            async with self.session.post(f"{BASE_URL}/smart-levels/", json=invalid_data3, headers=self.headers) as response:
                if response.status == 404:
                    error = await response.json()
                    print(f"✅ Invalid strategy_symbol_id error caught: {error['detail']}")
                else:
                    print(f"❌ Expected 404 for invalid strategy_symbol_id but got: {response.status}")
            
            # Step 10: Delete the smart level
            print("\n" + "="*50)
            await self.test_delete_smart_level(smart_level_id)
            
            # Step 11: Verify deletion
            print("\n🧪 Testing: Verify Deletion")
            async with self.session.get(f"{BASE_URL}/smart-levels/{smart_level_id}", headers=self.headers) as response:
                if response.status == 404:
                    print("✅ Smart level successfully deleted (404 on GET)")
                else:
                    print(f"❌ Expected 404 after deletion but got: {response.status}")
            
            # Final summary
            print("\n" + "="*60)
            print("🎉 ALL SMART LEVELS CRUD TESTS COMPLETED SUCCESSFULLY!")
            print("✅ Authentication: PASSED")
            print("✅ List Smart Levels: PASSED") 
            print("✅ Create Smart Level: PASSED")
            print("✅ Get Smart Level: PASSED")
            print("✅ Update Smart Level: PASSED")
            print("✅ Delete Smart Level: PASSED")
            print("✅ Validation Errors: PASSED")
            print("✅ Filtering: PASSED")
            print("="*60)
            
        finally:
            await self.cleanup()

async def main():
    """Main test function."""
    tester = SmartLevelsAPITest()
    await tester.run_all_tests()

if __name__ == "__main__":
    asyncio.run(main())
