#!/usr/bin/env python3
"""
Test the new order status and execution tracking logic without database interaction.
"""

import sys
sys.path.insert(0, '/opt/algosat')

def test_order_status_enum():
    """Test the new OrderStatus enum."""
    try:
        from algosat.core.order_request import OrderStatus
        print("✅ OrderStatus enum imported successfully")
        
        # Test new status values
        new_statuses = [
            OrderStatus.AWAITING_ENTRY,
            OrderStatus.OPEN,
            OrderStatus.CLOSED,
            OrderStatus.CANCELLED,
            OrderStatus.FAILED
        ]
        
        print("\\n📋 New Order Statuses:")
        for status in new_statuses:
            print(f"  - {status.value}")
            
        return True
    except Exception as e:
        print(f"❌ OrderStatus enum test failed: {e}")
        return False

def test_execution_side_enum():
    """Test the ExecutionSide enum."""
    try:
        from algosat.core.order_request import ExecutionSide
        print("\\n✅ ExecutionSide enum imported successfully")
        
        print(f"  - ENTRY: {ExecutionSide.ENTRY.value}")
        print(f"  - EXIT: {ExecutionSide.EXIT.value}")
        
        return True
    except Exception as e:
        print(f"❌ ExecutionSide enum test failed: {e}")
        return False

def test_order_manager_methods():
    """Test that OrderManager has the new methods."""
    try:
        from algosat.core.order_manager import OrderManager
        print("\\n✅ OrderManager imported successfully")
        
        # Check if new methods exist
        methods_to_check = [
            'determine_order_status',
            'update_order_status',
            'insert_granular_execution',
            'get_granular_executions',
            'calculate_vwap_for_executions',
            'process_broker_order_update'
        ]
        
        for method_name in methods_to_check:
            if hasattr(OrderManager, method_name):
                print(f"  ✅ {method_name} method exists")
            else:
                print(f"  ❌ {method_name} method missing")
                return False
                
        return True
    except Exception as e:
        print(f"❌ OrderManager test failed: {e}")
        return False

def test_status_determination_logic():
    """Test the status determination logic."""
    try:
        from algosat.core.order_manager import OrderManager
        from algosat.core.broker_manager import BrokerManager
        
        broker_manager = BrokerManager()
        order_manager = OrderManager(broker_manager)
        
        print("\\n🧪 Testing status determination logic...")
        
        # Test cases for different execution scenarios
        test_cases = [
            {
                "name": "No executions",
                "executions": [],
                "expected": "AWAITING_ENTRY"
            },
            {
                "name": "Entry execution only",
                "executions": [
                    {"side": "ENTRY", "status": "FILLED", "executed_quantity": 100}
                ],
                "expected": "OPEN"
            },
            {
                "name": "Entry and exit executions",
                "executions": [
                    {"side": "ENTRY", "status": "FILLED", "executed_quantity": 100},
                    {"side": "EXIT", "status": "FILLED", "executed_quantity": 100}
                ],
                "expected": "CLOSED"
            },
            {
                "name": "Cancelled executions",
                "executions": [
                    {"side": "ENTRY", "status": "CANCELLED", "executed_quantity": 0}
                ],
                "expected": "CANCELLED"
            },
            {
                "name": "Failed executions",
                "executions": [
                    {"side": "ENTRY", "status": "FAILED", "executed_quantity": 0}
                ],
                "expected": "FAILED"
            }
        ]
        
        # Mock the get_granular_executions method for testing
        async def mock_get_granular_executions(order_id):
            # Return the test case executions
            return test_cases[order_id - 1]["executions"]
        
        order_manager.get_granular_executions = mock_get_granular_executions
        
        # Test each case
        import asyncio
        
        async def run_status_tests():
            for i, test_case in enumerate(test_cases, 1):
                try:
                    result = await order_manager.determine_order_status(i)
                    expected = test_case["expected"]
                    if result == expected:
                        print(f"  ✅ {test_case['name']}: {result}")
                    else:
                        print(f"  ❌ {test_case['name']}: got {result}, expected {expected}")
                        return False
                except Exception as e:
                    print(f"  ❌ {test_case['name']}: Error - {e}")
                    return False
            return True
        
        success = asyncio.run(run_status_tests())
        return success
        
    except Exception as e:
        print(f"❌ Status determination test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all tests."""
    print("🚀 Testing Order Status and Execution Tracking Implementation")
    print("=" * 60)
    
    tests = [
        ("OrderStatus Enum", test_order_status_enum),
        ("ExecutionSide Enum", test_execution_side_enum),
        ("OrderManager Methods", test_order_manager_methods),
        ("Status Determination Logic", test_status_determination_logic)
    ]
    
    results = []
    for test_name, test_func in tests:
        print(f"\\n🧪 Running: {test_name}")
        print("-" * 40)
        success = test_func()
        results.append((test_name, success))
    
    # Summary
    print("\\n📊 TEST SUMMARY")
    print("=" * 40)
    passed = 0
    for test_name, success in results:
        status = "✅ PASSED" if success else "❌ FAILED"
        print(f"{status}: {test_name}")
        if success:
            passed += 1
    
    print(f"\\n🎯 Results: {passed}/{len(results)} tests passed")
    
    if passed == len(results):
        print("🎉 All tests passed! The order status and execution tracking system is ready.")
        return True
    else:
        print("💥 Some tests failed. Please check the implementation.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
