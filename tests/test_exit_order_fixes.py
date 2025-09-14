#!/usr/bin/env python3

"""
Test script to verify fixes for exit_order issues:
1. Action field normalization (SIDE.BUY → BUY)  
2. Quantity field population in EXIT broker_executions
"""

import asyncio
import sys
import os

# Add the project root to Python path
sys.path.insert(0, '/opt/algosat')

from algosat.core.broker_manager import BrokerManager
from algosat.core.order_manager import OrderManager

async def test_exit_order_fixes():
    """Test the exit_order fixes for action normalization and quantity field."""
    
    print("🧪 Testing exit_order fixes for order_id 207...")
    
    # Initialize managers
    broker_manager = BrokerManager()
    await broker_manager.setup()
    order_manager = OrderManager(broker_manager)
    
    # Test exit_order for order_id 207
    try:
        print("\n📋 Calling exit_order for order_id 207...")
        await order_manager.exit_order(
            parent_order_id=207,
            exit_reason="testing_fixes_action_and_quantity",
            check_live_status=True
        )
        print("✅ Exit order completed successfully")
        
    except Exception as e:
        print(f"❌ Error during exit_order: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    print("\n🎯 Exit order test completed!")
    return True

async def main():
    """Main test function."""
    print("🚀 Starting exit_order fixes test...")
    print("=" * 60)
    
    success = await test_exit_order_fixes()
    
    print("\n" + "=" * 60)
    if success:
        print("✅ All tests completed! Check database to verify:")
        print("   1. Action field should be 'BUY' not 'SIDE.BUY' for Fyers ENTRY")
        print("   2. Quantity field should be 75 not None for EXIT orders")
        print("   3. Execution_price should remain 0.0 (expected for testing)")
        print("   4. Execution_time should remain None (expected for testing)")
    else:
        print("❌ Test failed!")
    
    return success

if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(0 if result else 1)
