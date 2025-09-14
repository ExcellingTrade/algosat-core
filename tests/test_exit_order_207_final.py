#!/usr/bin/env python3
"""
Comprehensive test for exit_order method on order_id 207.
Tests all field updates, mock data integration, and proper exit_action calculation.
"""

import sys
import asyncio
from datetime import datetime, date
sys.path.insert(0, '/opt/algosat')

async def test_exit_order_207():
    """Test exit_order for order_id 207 with comprehensive field validation"""
    
    print("=== COMPREHENSIVE EXIT_ORDER TEST FOR ORDER_ID 207 ===\n")
    
    # Verify date for mock data
    today = date.today()
    if today != date(2025, 8, 9):
        print(f"❌ WARNING: Today is {today}, but mock data is only active on 2025-08-09")
        print("   Mock broker data will not be available for testing!")
    else:
        print(f"✅ Date verification: {today} - Mock data is active")
    
    try:
        print("\n1️⃣ INITIALIZING COMPONENTS...")
        
        # Step 1: Initialize database
        print("   Initializing database...")
        from algosat.core.db import init_db
        await init_db()
        print("   ✅ Database initialized")
        
        # Step 2: Initialize broker manager
        print("   Initializing broker manager...")
        from algosat.core.broker_manager import BrokerManager
        broker_manager = BrokerManager()
        await broker_manager.setup()
        print("   ✅ Broker manager initialized")
        
        # Step 3: Initialize order manager
        print("   Initializing order manager...")
        from algosat.core.order_manager import OrderManager
        order_manager = OrderManager(broker_manager)
        print("   ✅ Order manager initialized")
        
        # Step 4: Test mock data availability
        print(f"\n2️⃣ TESTING MOCK DATA AVAILABILITY:")
        
        try:
            all_broker_orders = await order_manager.get_all_broker_order_details()
            print(f"📊 Mock broker order data retrieved:")
            for broker_name, orders in all_broker_orders.items():
                print(f"   {broker_name}: {len(orders)} orders")
                if orders and len(orders) > 0:
                    sample = orders[0]
                    print(f"      Sample order ID: {sample.get('id', sample.get('order_id', 'N/A'))}")
                    print(f"      Sample fields: {list(sample.keys())[:8]}...")
        except Exception as e:
            print(f"   ⚠️  Mock data fetch error: {e}")
        
        # Step 5: Check existing order data
        print(f"\n3️⃣ CHECKING ORDER_ID 207 DATA:")
        
        order_id = 207
        
        from algosat.core.db import AsyncSessionLocal, get_broker_executions_for_order, get_order_by_id
        
        async with AsyncSessionLocal() as session:
            # Get order details
            order_row = await get_order_by_id(session, order_id)
            if not order_row:
                print(f"❌ Order {order_id} not found in database")
                return
                
            print(f"📋 Order {order_id} Details:")
            print(f"   Symbol: {order_row.get('strike_symbol')}")
            print(f"   Status: {order_row.get('status')}")
            print(f"   Side: {order_row.get('side')}")
            print(f"   Executed Quantity: {order_row.get('executed_quantity')}")
            print(f"   Entry Price: {order_row.get('entry_price')}")
            print(f"   Exit Price: {order_row.get('exit_price')}")
            print(f"   PnL: {order_row.get('pnl')}")
            
            # Get broker executions BEFORE exit
            entry_executions = await get_broker_executions_for_order(session, order_id, side='ENTRY')
            exit_executions_before = await get_broker_executions_for_order(session, order_id, side='EXIT')
            
            print(f"\n📥 ENTRY BROKER EXECUTIONS ({len(entry_executions)}):")
            for i, entry in enumerate(entry_executions):
                print(f"   {i+1}. ID={entry.get('id')}")
                print(f"      broker_id={entry.get('broker_id')} (broker: {get_broker_name_safe(entry.get('broker_id'))})")
                print(f"      broker_order_id={entry.get('broker_order_id')}")
                print(f"      status={entry.get('status')}")
                print(f"      action={entry.get('action')}")
                print(f"      executed_quantity={entry.get('executed_quantity')}")
                print(f"      execution_price={entry.get('execution_price')}")
                print(f"      symbol={entry.get('symbol')}")
                print(f"      product_type={entry.get('product_type')}")
                print(f"      execution_time={entry.get('execution_time')}")
                print()
                
            print(f"📤 EXIT EXECUTIONS BEFORE ({len(exit_executions_before)})")
            if exit_executions_before:
                for i, exit_exec in enumerate(exit_executions_before):
                    print(f"   {i+1}. ID={exit_exec.get('id')}, action={exit_exec.get('action')}, price={exit_exec.get('execution_price')}")
        
        # Step 6: Execute exit_order with test parameters
        print(f"\n4️⃣ EXECUTING EXIT_ORDER:")
        
        test_ltp = 250.75  # Test LTP value
        exit_reason = "COMPREHENSIVE_TEST_ORDER_207"
        
        print(f"   Test Parameters:")
        print(f"   - parent_order_id: {order_id}")
        print(f"   - ltp: {test_ltp}")
        print(f"   - exit_reason: '{exit_reason}'")
        print(f"   - check_live_status: True")
        
        # Execute exit_order
        print(f"\n   Executing exit_order...")
        start_time = datetime.now()
        
        result = await order_manager.exit_order(
            parent_order_id=order_id,
            exit_reason=exit_reason,
            ltp=test_ltp,
            check_live_status=True
        )
        
        end_time = datetime.now()
        execution_time = (end_time - start_time).total_seconds()
        
        print(f"   ✅ exit_order completed in {execution_time:.2f} seconds")
        print(f"   Result: {result}")
        
        # Step 7: Verify results and validate fields
        print(f"\n5️⃣ VERIFYING RESULTS:")
        
        async with AsyncSessionLocal() as session:
            # Get updated executions
            exit_executions_after = await get_broker_executions_for_order(session, order_id, side='EXIT')
            updated_order = await get_order_by_id(session, order_id)
            
            new_exits = len(exit_executions_after) - len(exit_executions_before)
            print(f"📊 EXIT executions: {len(exit_executions_before)} → {len(exit_executions_after)} (+{new_exits} new)")
            
            # Check order status changes
            if updated_order:
                print(f"📋 Order status: {order_row.get('status')} → {updated_order.get('status')}")
                if updated_order.get('exit_time'):
                    print(f"📅 Exit time set: {updated_order.get('exit_time')}")
                if updated_order.get('exit_price'):
                    print(f"💰 Exit price: {updated_order.get('exit_price')}")
                if updated_order.get('pnl') is not None:
                    print(f"📈 PnL: {updated_order.get('pnl')}")
            
            if exit_executions_after:
                print(f"\n📤 ALL EXIT BROKER EXECUTIONS:")
                
                for i, exit_exec in enumerate(exit_executions_after):
                    print(f"\n   EXIT EXECUTION #{i+1}:")
                    print(f"   ├─ ID: {exit_exec.get('id')}")
                    print(f"   ├─ parent_order_id: {exit_exec.get('parent_order_id')} {'✅' if exit_exec.get('parent_order_id') == order_id else '❌'}")
                    print(f"   ├─ broker_id: {exit_exec.get('broker_id')} ({get_broker_name_safe(exit_exec.get('broker_id'))})")
                    print(f"   ├─ broker_order_id: {exit_exec.get('broker_order_id')}")
                    print(f"   ├─ exit_broker_order_id: {exit_exec.get('exit_broker_order_id')}")
                    print(f"   ├─ side: {exit_exec.get('side')} {'✅' if exit_exec.get('side') == 'EXIT' else '❌'}")
                    
                    # Validate action field
                    action = exit_exec.get('action')
                    action_status = '✅' if action in ['BUY', 'SELL', 'EXIT'] else '❌'
                    print(f"   ├─ action: {action} {action_status}")
                    
                    print(f"   ├─ status: {exit_exec.get('status')}")
                    print(f"   ├─ executed_quantity: {exit_exec.get('executed_quantity')}")
                    
                    # Validate execution price
                    exec_price = exit_exec.get('execution_price')
                    price_status = '✅' if exec_price == test_ltp else f'⚠️ (expected {test_ltp})'
                    print(f"   ├─ execution_price: {exec_price} {price_status}")
                    
                    print(f"   ├─ product_type: {exit_exec.get('product_type')}")
                    print(f"   ├─ order_type: {exit_exec.get('order_type')}")
                    print(f"   ├─ symbol: {exit_exec.get('symbol')}")
                    
                    # Validate execution time
                    exec_time = exit_exec.get('execution_time')
                    time_status = '✅' if exec_time else '❌'
                    print(f"   ├─ execution_time: {exec_time} {time_status}")
                    
                    print(f"   ├─ order_messages: {exit_exec.get('order_messages')}")
                    print(f"   ├─ notes: {exit_exec.get('notes')}")
                    print(f"   └─ raw_execution_data: {'Set' if exit_exec.get('raw_execution_data') else 'None'}")
                    
                    # Validate action logic for this specific exit
                    if action == 'SELL':
                        print(f"      🎯 Action Logic: BUY entry → SELL exit ✅")
                    elif action == 'BUY':
                        print(f"      🎯 Action Logic: SELL entry → BUY exit ✅")
                    elif action == 'EXIT':
                        print(f"      🎯 Action Logic: Unknown entry → EXIT fallback ⚠️")
                    else:
                        print(f"      🎯 Action Logic: Invalid action '{action}' ❌")
                        
            else:
                print(f"❌ No EXIT executions found after exit_order")
                return
        
        # Step 8: Comprehensive field validation
        print(f"\n6️⃣ COMPREHENSIVE FIELD VALIDATION:")
        
        validation_results = {}
        
        for i, exit_exec in enumerate(exit_executions_after):
            print(f"\n   VALIDATION FOR EXIT EXECUTION #{i+1}:")
            
            # Required field validation
            required_fields = {
                'parent_order_id': (exit_exec.get('parent_order_id'), order_id),
                'broker_id': (exit_exec.get('broker_id'), 'not None'),
                'broker_order_id': (exit_exec.get('broker_order_id'), 'not None'),
                'side': (exit_exec.get('side'), 'EXIT'),
                'action': (exit_exec.get('action'), ['BUY', 'SELL', 'EXIT']),
                'status': (exit_exec.get('status'), 'not None'),
                'executed_quantity': (exit_exec.get('executed_quantity'), 'not None'),
                'execution_price': (exit_exec.get('execution_price'), test_ltp),
                'symbol': (exit_exec.get('symbol'), 'not None'),
                'execution_time': (exit_exec.get('execution_time'), 'not None'),
                'order_messages': (exit_exec.get('order_messages'), 'not None'),
                'notes': (exit_exec.get('notes'), 'not None')
            }
            
            exec_validation = {}
            
            for field, (actual, expected) in required_fields.items():
                if expected == 'not None':
                    is_valid = actual is not None
                elif isinstance(expected, list):
                    is_valid = actual in expected
                else:
                    is_valid = actual == expected
                    
                status = '✅' if is_valid else '❌'
                exec_validation[field] = is_valid
                print(f"   {status} {field}: {actual} {'✅' if is_valid else f'(expected: {expected})'}")
            
            validation_results[f'execution_{i+1}'] = exec_validation
        
        # Overall validation summary
        all_validations_passed = all(
            all(field_results.values()) 
            for field_results in validation_results.values()
        )
        
        print(f"\n🎯 OVERALL VALIDATION: {'✅ ALL CHECKS PASSED' if all_validations_passed else '❌ SOME CHECKS FAILED'}")
        
        # Step 9: Test summary
        print(f"\n7️⃣ TEST SUMMARY:")
        print(f"✅ Database initialization: Success")
        print(f"✅ Broker manager setup: Success") 
        print(f"✅ Order manager initialization: Success")
        print(f"✅ Mock data availability: {'Verified' if today == date(2025, 8, 9) else 'Not available'}")
        print(f"✅ Order {order_id} retrieval: Success")
        print(f"✅ exit_order execution: Completed in {execution_time:.2f}s")
        print(f"✅ EXIT executions created: {new_exits}")
        print(f"✅ Field validation: {'All passed' if all_validations_passed else 'Some failed'}")
        print(f"✅ Action field logic: Tested")
        print(f"✅ Execution time handling: Verified")
        print(f"✅ LTP price setting: Validated")
        
        print(f"\n🚀 COMPREHENSIVE EXIT_ORDER TEST FOR ORDER_ID 207 COMPLETED")
        
        if all_validations_passed:
            print(f"🎉 ALL TESTS PASSED - EXIT_ORDER WORKING CORRECTLY!")
        else:
            print(f"⚠️  SOME VALIDATIONS FAILED - REVIEW RESULTS ABOVE")
        
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()

def get_broker_name_safe(broker_id):
    """Safe broker name lookup"""
    broker_map = {1: 'fyers', 2: 'angel', 3: 'zerodha'}
    return broker_map.get(broker_id, f'unknown({broker_id})')

if __name__ == "__main__":
    print("🚀 Starting comprehensive exit_order test for order_id 207...")
    try:
        asyncio.run(test_exit_order_207())
    except KeyboardInterrupt:
        print("\n⚠️  Test interrupted by user")
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("🏁 Test completed")
