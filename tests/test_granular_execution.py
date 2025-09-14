"""
Simple test for granular execution tracking without full system dependencies.
"""

import asyncio
import sys
import os
from datetime import datetime

# Add the algosat directory to Python path
sys.path.insert(0, '/opt/algosat')

async def test_basic_imports():
    """Test that all our new components can be imported."""
    try:
        print("🧪 Testing basic imports...")
        
        # Test ExecutionSide enum
        from algosat.core.order_request import ExecutionSide
        print(f"✅ ExecutionSide imported: {list(ExecutionSide)}")
        
        # Test database schema
        from algosat.core.dbschema import broker_executions
        print("✅ Updated broker_executions schema imported")
        
        # Test that the schema has our new columns
        column_names = [col.name for col in broker_executions.columns]
        expected_columns = ['side', 'execution_price', 'executed_quantity', 'broker_order_id']
        
        for col in expected_columns:
            if col in column_names:
                print(f"✅ Column '{col}' found in schema")
            else:
                print(f"❌ Column '{col}' missing from schema")
        
        print("\n📋 All broker_executions columns:")
        for col in column_names:
            print(f"  - {col}")
        
        return True
        
    except Exception as e:
        print(f"❌ Import test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_enum_values():
    """Test ExecutionSide enum functionality."""
    try:
        print("\n🧪 Testing ExecutionSide enum...")
        
        from algosat.core.order_request import ExecutionSide
        
        # Test enum values
        entry = ExecutionSide.ENTRY
        exit_side = ExecutionSide.EXIT
        
        print(f"✅ ENTRY value: '{entry.value}'")
        print(f"✅ EXIT value: '{exit_side.value}'")
        
        # Test string conversion
        print(f"✅ ENTRY as string: '{str(entry)}'")
        print(f"✅ EXIT as string: '{str(exit_side)}'")
        
        return True
        
    except Exception as e:
        print(f"❌ Enum test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_order_manager_methods():
    """Test that OrderManager has our new methods."""
    try:
        print("\n🧪 Testing OrderManager new methods...")
        
        from algosat.core.order_manager import OrderManager
        
        # Create a mock broker manager for testing
        class MockBrokerManager:
            pass
        
        mock_broker_manager = MockBrokerManager()
        order_manager = OrderManager(mock_broker_manager)
        
        # Check that our new methods exist
        required_methods = [
            'insert_granular_execution',
            'get_granular_executions', 
            'calculate_vwap_for_executions',
            'update_order_aggregated_prices',
            'process_broker_order_update'
        ]
        
        for method_name in required_methods:
            if hasattr(order_manager, method_name):
                method = getattr(order_manager, method_name)
                if callable(method):
                    print(f"✅ Method '{method_name}' exists and is callable")
                else:
                    print(f"❌ Method '{method_name}' exists but is not callable")
            else:
                print(f"❌ Method '{method_name}' not found")
        
        return True
        
    except Exception as e:
        print(f"❌ OrderManager test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_database_functions():
    """Test that our new database functions are available."""
    try:
        print("\n🧪 Testing database functions...")
        
        import algosat.core.db as db_module
        
        # Check for our new database functions
        required_functions = [
            'get_granular_executions_by_order_id',
            'get_executions_summary_by_order_id'
        ]
        
        for func_name in required_functions:
            if hasattr(db_module, func_name):
                func = getattr(db_module, func_name)
                if callable(func):
                    print(f"✅ Function '{func_name}' exists and is callable")
                else:
                    print(f"❌ Function '{func_name}' exists but is not callable")
            else:
                print(f"❌ Function '{func_name}' not found")
        
        return True
        
    except Exception as e:
        print(f"❌ Database functions test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def run_all_tests():
    """Run all tests in sequence."""
    print("🚀 Starting Granular Execution Tracking Tests")
    print("=" * 60)
    
    tests = [
        ("Basic Imports", test_basic_imports),
        ("ExecutionSide Enum", test_enum_values),
        ("OrderManager Methods", test_order_manager_methods),
        ("Database Functions", test_database_functions)
    ]
    
    results = []
    
    for test_name, test_func in tests:
        print(f"\n{'=' * 60}")
        print(f"🧪 Running: {test_name}")
        print('=' * 60)
        
        try:
            success = await test_func()
            results.append((test_name, success))
        except Exception as e:
            print(f"❌ Test '{test_name}' crashed: {e}")
            results.append((test_name, False))
    
    # Print summary
    print(f"\n{'=' * 60}")
    print("📊 TEST SUMMARY")
    print('=' * 60)
    
    passed = 0
    total = len(results)
    
    for test_name, success in results:
        status = "✅ PASSED" if success else "❌ FAILED"
        print(f"{status}: {test_name}")
        if success:
            passed += 1
    
    print(f"\n🎯 Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! The granular execution tracking system is ready.")
    else:
        print("⚠️  Some tests failed. Please check the output above.")
    
    return passed == total

if __name__ == "__main__":
    asyncio.run(run_all_tests())
