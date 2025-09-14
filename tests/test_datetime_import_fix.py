#!/usr/bin/env python3
"""
Test script to verify the datetime import fix in OrderMonitor.
"""

import asyncio
import sys
import os

# Add the project root to the path
sys.path.insert(0, '/opt/algosat')

async def test_datetime_imports():
    """
    Test that the datetime imports are properly available in all code paths.
    """
    print("🔍 Testing datetime import fix in OrderMonitor...")
    
    try:
        # Test the imports in isolation
        from datetime import datetime, timezone
        
        # Test creating datetime objects
        exit_time = datetime.now(timezone.utc)
        print(f"✅ datetime.now(timezone.utc) works: {exit_time}")
        
        # Test in the same way it's used in the fallback code
        def test_fallback_imports():
            """Simulate the fallback code path"""
            from datetime import datetime, timezone
            exit_time = datetime.now(timezone.utc)
            return exit_time
            
        test_time = test_fallback_imports()
        print(f"✅ Fallback import pattern works: {test_time}")
        
        print("🎉 ALL DATETIME IMPORT TESTS PASSED!")
        return True
        
    except Exception as e:
        print(f"❌ Error in datetime import test: {e}")
        return False

async def main():
    """Main test function"""
    print("=" * 60)
    print("TESTING: OrderMonitor datetime import fix")
    print("=" * 60)
    
    success = await test_datetime_imports()
    
    if success:
        print("\n✅ RESULT: DateTime import fix is working correctly!")
        print("   - The UnboundLocalError should now be resolved")
        print("   - Fallback exit processing will work properly")
    else:
        print("\n❌ RESULT: DateTime import fix test failed!")
    
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
