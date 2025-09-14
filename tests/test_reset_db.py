#!/usr/bin/env python3
"""
Test script to verify the reset database functionality.
This script can be used to test the database reset endpoint.
"""

import asyncio
import sys
import os

# Add the project root to Python path
sys.path.insert(0, '/opt/algosat')

async def test_reset_function():
    """Test the reset_database_tables function directly."""
    try:
        from algosat.core.db import reset_database_tables, AsyncSessionLocal
        
        print("Testing reset_database_tables function...")
        
        async with AsyncSessionLocal() as session:
            result = await reset_database_tables(session)
            print(f"Reset completed successfully: {result}")
            return result
            
    except Exception as e:
        print(f"Error testing reset function: {e}")
        return None

async def test_api_import():
    """Test importing the API components."""
    try:
        from algosat.api.routes.admin import router
        print("✅ Admin router imported successfully")
        
        from algosat.core.db import reset_database_tables
        print("✅ Database reset function imported successfully")
        
        return True
        
    except Exception as e:
        print(f"❌ Error importing API components: {e}")
        return False

async def main():
    """Main test function."""
    print("=== Testing Database Reset Functionality ===\n")
    
    # Test imports
    import_success = await test_api_import()
    
    if not import_success:
        print("Import tests failed. Exiting.")
        return
    
    print("\n=== Import Tests Passed ===\n")
    
    # Uncomment the following line to test the actual database reset
    # WARNING: This will delete data from your database!
    # result = await test_reset_function()
    # print(f"Database reset result: {result}")
    
    print("=== Test completed ===")
    print("\nTo test the API endpoint, you can use:")
    print("curl -X POST http://localhost:8000/admin/resetdb -H 'Authorization: Bearer YOUR_TOKEN'")

if __name__ == "__main__":
    asyncio.run(main())
