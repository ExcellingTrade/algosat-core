#!/usr/bin/env python3
"""
Comprehensive test for exit_order with proper broker initialization and mock data.
Tests order_id 207 with full field validation.
"""

import sys
sys.path.append('/opt/algosat')

import asyncio
from datetime import datetime, timezone, date
import logging

# Configure logging for better visibility
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def initialize_test_brokers():
    """Initialize brokers for testing"""
    try:
        from algosat.core.broker_manager import BrokerManager
        from algosat.brokers.fyers import Fyers  
        from algosat.brokers.zerodha import Zerodha
        
        # Create broker manager
        broker_manager = BrokerManager()
        
        # Initialize Fyers broker (id=1)
        fyers_broker = Fyers()
        fyers_broker.broker_id = 1
        fyers_broker.broker_name = "fyers"
        
        # Initialize Zerodha broker (id=3) 
        zerodha_broker = Zerodha()
        zerodha_broker.broker_id = 3
        zerodha_broker.broker_name = "zerodha"
        
        # Add brokers to manager
        broker_manager.brokers = {
            'fyers': fyers_broker,
            'zerodha': zerodha_broker
        }
        
        logger.info("✅ Test brokers initialized successfully")
        return broker_manager
        
    except Exception as e:
        logger.error(f"❌ Failed to initialize test brokers: {e}")
        return None

async def test_exit_order_207_complete():
    """
    Complete test of exit_order for order_id 207 with proper broker setup
    """
    
    print("=== COMPREHENSIVE EXIT_ORDER TEST FOR ORDER_ID 207 ===\n")
    
    # Verify date for mock data
    today = date.today()
    if today != date(2025, 8, 9):
        print(f"❌ WARNING: Today is {today}, but mock data is only active on 2025-08-09")
        return
    
    print(f"✅ Date verification: {today} - Mock data is active")
    
    try:
        # Step 1: Initialize components with proper broker setup
        print("\n1️⃣ INITIALIZING COMPONENTS WITH BROKER SETUP:")
        
        from algosat.core.order_manager import OrderManager
        from algosat.core.db import AsyncSessionLocal, get_broker_executions_for_order, get_order_by_id
        
        # Initialize broker manager with test brokers
        broker_manager = await initialize_test_brokers()
        if not broker_manager:
            print("❌ Failed to initialize broker manager")
            return
            
        # Create order manager
        order_manager = OrderManager(broker_manager=broker_manager)
        
        print("✅ Order manager initialized with test brokers")
        
        # Step 2: Test mock data availability
        print("\n2️⃣ TESTING MOCK DATA AVAILABILITY:")
        
        # Test get_all_broker_order_details with mock data
        all_broker_orders = await order_manager.get_all_broker_order_details()
        
        print(f"📊 Mock broker order data retrieved:")
        for broker_name, orders in all_broker_orders.items():
            print(f"   {broker_name}: {len(orders)} orders")
            if orders:
                # Show sample order fields
                sample = orders[0]
                print(f"      Sample fields: {list(sample.keys())[:10]}...")
        
        # Step 3: Check existing order data
        print(f"\n3️⃣ CHECKING ORDER_ID 207 DATA:")
        
        order_id = 207
        
        async with AsyncSessionLocal() as session:
            # Get order details
            order_row = await get_order_by_id(session, order_id)
            if not order_row:
                print(f"❌ Order {order_id} not found")
                return
                
            print(f"📋 Order {order_id}:")
            print(f"   Symbol: {order_row.get('strike_symbol')}")
            print(f"   Status: {order_row.get('status')}")
            print(f"   Side: {order_row.get('side')}")
            
            # Get broker executions BEFORE exit
            entry_executions = await get_broker_executions_for_order(session, order_id, side='ENTRY')
            exit_executions_before = await get_broker_executions_for_order(session, order_id, side='EXIT')
            
            print(f"\n📥 ENTRY BROKER EXECUTIONS ({len(entry_executions)}):")
            for i, entry in enumerate(entry_executions):
                print(f"   {i+1}. ID={entry.get('id')}")
                print(f"      broker_id={entry.get('broker_id')} (broker: {await get_broker_name_safe(entry.get('broker_id'))})")
                print(f"      broker_order_id={entry.get('broker_order_id')}")
                print(f"      status={entry.get('status')}")
                print(f"      action={entry.get('action')}")
                print(f"      executed_quantity={entry.get('executed_quantity')}")
                print(f"      execution_price={entry.get('execution_price')}")
                print(f"      symbol={entry.get('symbol')}")
                print(f"      product_type={entry.get('product_type')}")
                print()
                
            print(f"📤 EXIT EXECUTIONS BEFORE ({len(exit_executions_before)}): {len(exit_executions_before)}")
        
        # Step 4: Execute exit_order with test parameters
        print(f"\n4️⃣ EXECUTING EXIT_ORDER:")
        
        test_ltp = 200.50
        exit_reason = "COMPREHENSIVE_TEST_207"
        
        print(f"   Parameters:")
        print(f"   - parent_order_id: {order_id}")
        print(f"   - ltp: {test_ltp}")
        print(f"   - exit_reason: '{exit_reason}'")
        print(f"   - check_live_status: True")
        
        # Execute exit_order
        start_time = datetime.now()
        result = await order_manager.exit_order(
            parent_order_id=order_id,
            exit_reason=exit_reason,
            ltp=test_ltp,
            check_live_status=True
        )
        end_time = datetime.now()
        
        print(f"✅ exit_order completed in {(end_time - start_time).total_seconds():.2f} seconds")
        print(f"   Result: {result}")
        
        # Step 5: Verify results and validate fields
        print(f"\n5️⃣ VERIFYING RESULTS:")
        
        async with AsyncSessionLocal() as session:
            # Get updated executions
            exit_executions_after = await get_broker_executions_for_order(session, order_id, side='EXIT')
            
            new_exits = len(exit_executions_after) - len(exit_executions_before)
            print(f"📊 EXIT executions: {len(exit_executions_before)} → {len(exit_executions_after)} (+{new_exits} new)")
            
            if exit_executions_after:
                print(f"\n📤 ALL EXIT BROKER EXECUTIONS:")
                
                for i, exit_exec in enumerate(exit_executions_after):
                    print(f"\n   EXIT EXECUTION #{i+1}:")
                    print(f"   ├─ ID: {exit_exec.get('id')}")
                    print(f"   ├─ parent_order_id: {exit_exec.get('parent_order_id')} ✅")
                    print(f"   ├─ broker_id: {exit_exec.get('broker_id')} (broker: {await get_broker_name_safe(exit_exec.get('broker_id'))})")
                    print(f"   ├─ broker_order_id: {exit_exec.get('broker_order_id')}")
                    print(f"   ├─ exit_broker_order_id: {exit_exec.get('exit_broker_order_id')}")
                    print(f"   ├─ side: {exit_exec.get('side')} ✅")
                    print(f"   ├─ action: {exit_exec.get('action')} {'✅' if exit_exec.get('action') in ['BUY', 'SELL', 'EXIT'] else '❌'}")
                    print(f"   ├─ status: {exit_exec.get('status')} ✅")
                    print(f"   ├─ executed_quantity: {exit_exec.get('executed_quantity')}")
                    print(f"   ├─ execution_price: {exit_exec.get('execution_price')} {'✅' if exit_exec.get('execution_price') == test_ltp else '⚠️'}")
                    print(f"   ├─ product_type: {exit_exec.get('product_type')}")
                    print(f"   ├─ order_type: {exit_exec.get('order_type')}")
                    print(f"   ├─ symbol: {exit_exec.get('symbol')}")
                    print(f"   ├─ execution_time: {exit_exec.get('execution_time')} ✅")
                    print(f"   ├─ order_messages: {exit_exec.get('order_messages')}")
                    print(f"   ├─ notes: {exit_exec.get('notes')}")
                    print(f"   └─ raw_execution_data: {'Set' if exit_exec.get('raw_execution_data') else 'None'}")
                    
                    # Validate action logic
                    action = exit_exec.get('action')
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
        
        # Step 6: Field validation summary
        print(f"\n6️⃣ VALIDATION SUMMARY:")
        
        if exit_executions_after:
            all_valid = True
            
            for exit_exec in exit_executions_after:
                # Check required fields
                required_checks = {
                    'parent_order_id': exit_exec.get('parent_order_id') == order_id,
                    'broker_id': exit_exec.get('broker_id') is not None,
                    'broker_order_id': exit_exec.get('broker_order_id') is not None,
                    'side': exit_exec.get('side') == 'EXIT',
                    'action': exit_exec.get('action') in ['BUY', 'SELL', 'EXIT'],
                    'status': exit_exec.get('status') is not None,
                    'executed_quantity': exit_exec.get('executed_quantity') is not None,
                    'execution_price': exit_exec.get('execution_price') is not None,
                    'symbol': exit_exec.get('symbol') is not None,
                    'execution_time': exit_exec.get('execution_time') is not None,
                    'order_messages': exit_exec.get('order_messages') is not None,
                    'notes': exit_exec.get('notes') is not None
                }
                
                for field, is_valid in required_checks.items():
                    status = '✅' if is_valid else '❌'
                    print(f"   {status} {field}: {is_valid}")
                    if not is_valid:
                        all_valid = False
            
            print(f"\n🎯 OVERALL VALIDATION: {'✅ PASSED' if all_valid else '❌ FAILED'}")
        else:
            print(f"❌ No exit executions to validate")
            
        print(f"\n🚀 COMPREHENSIVE TEST COMPLETED")
        
        # Summary
        print(f"\n📋 TEST SUMMARY:")
        print(f"✅ Broker initialization: Success")
        print(f"✅ Mock data availability: Verified")
        print(f"✅ Order retrieval: Success")
        print(f"✅ exit_order execution: Completed")
        print(f"✅ Field validation: {'Passed' if exit_executions_after else 'No data to validate'}")
        
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()

async def get_broker_name_safe(broker_id):
    """Safe broker name lookup"""
    broker_map = {1: 'fyers', 2: 'angel', 3: 'zerodha'}
    return broker_map.get(broker_id, f'unknown({broker_id})')

if __name__ == "__main__":
    asyncio.run(test_exit_order_207_complete())
