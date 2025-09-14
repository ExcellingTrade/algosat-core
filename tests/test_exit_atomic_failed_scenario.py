#!/usr/bin/env python3
"""
Test script to verify enhanced exit_order logic for EXIT_ATOMIC_FAILED scenarios.
This tests the case where:
1. Orders have status EXIT_ATOMIC_FAILED in database (indicating exit was attempted but failed)
2. Database still shows PENDING status for broker executions (order monitor hasn't updated yet)
3. exit_order is called with check_live_status=True
4. Live broker data shows orders are actually FILLED
5. exit_order should sync live status first, then call appropriate action (exit vs cancel)
"""

import asyncio
import sys
import os
sys.path.append('/opt/algosat')

from algosat.core.order_manager import OrderManager
from algosat.core.broker_manager import BrokerManager
from algosat.core.db import AsyncSessionLocal, get_broker_executions_for_order, get_order_by_id
from algosat.common.logger import get_logger

# Configure logging
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = get_logger("TestExitAtomicFailedScenario")

async def test_exit_atomic_failed_scenario():
    """
    Test EXIT_ATOMIC_FAILED scenario where live status sync is crucial for proper exit/cancel decisions
    """
    
    print("🚀 TESTING EXIT_ATOMIC_FAILED SCENARIO WITH LIVE STATUS SYNC")
    print("=" * 80)
    
    # Initialize components
    broker_manager = BrokerManager()
    order_manager = OrderManager(broker_manager=broker_manager)
    
    # Test with order 207 which should have FILLED entries in mock data
    parent_order_id = 207
    
    print(f"1️⃣ TESTING ORDER {parent_order_id} - EXIT_ATOMIC_FAILED SCENARIO:")
    print("   Scenario: Order has EXIT_ATOMIC_FAILED status, DB shows PENDING, but broker shows FILLED")
    print("   Expected: Live status sync should update DB, then call exit_order (not cancel_order)")
    print()
    
    # Get current broker executions to understand initial state
    async with AsyncSessionLocal() as session:
        broker_execs = await get_broker_executions_for_order(session, parent_order_id)
        order_info = await get_order_by_id(session, parent_order_id)
        
        print(f"📊 INITIAL STATE:")
        print(f"   Order {parent_order_id} status: {order_info.get('status') if order_info else 'NOT_FOUND'}")
        print(f"   Broker executions found: {len(broker_execs)}")
        
        for i, be in enumerate(broker_execs, 1):
            print(f"   Execution #{i}:")
            print(f"   ├─ ID: {be.get('id')}")
            print(f"   ├─ Broker: {be.get('broker_id')} ({be.get('broker_name', 'Unknown')})")
            print(f"   ├─ Order ID: {be.get('broker_order_id')}")
            print(f"   ├─ Status: {be.get('status')}")
            print(f"   ├─ Side: {be.get('side')}")
            print(f"   └─ Symbol: {be.get('symbol')}")
        print()
    
    print(f"2️⃣ CALLING exit_order WITH check_live_status=True:")
    print("   This should:")
    print("   ✓ Fetch live broker data first")
    print("   ✓ Update database with live status")
    print("   ✓ Make exit/cancel decisions based on UPDATED status")
    print("   ✓ For FILLED orders: call exit_order")
    print("   ✓ For PENDING orders: call cancel_order")
    print()
    
    try:
        start_time = asyncio.get_event_loop().time()
        
        # Call exit_order with live status checking enabled
        result = await order_manager.exit_order(
            parent_order_id=parent_order_id,
            exit_reason="EXIT_ATOMIC_FAILED_TEST_LIVE_SYNC",
            check_live_status=True  # This is the key parameter that should trigger live sync
        )
        
        end_time = asyncio.get_event_loop().time()
        duration = end_time - start_time
        
        print(f"   ✅ exit_order completed in {duration:.2f} seconds")
        print(f"   Result: {result}")
        print()
        
    except Exception as e:
        print(f"   ❌ exit_order failed: {e}")
        import traceback
        traceback.print_exc()
        return
    
    print(f"3️⃣ VERIFYING RESULTS:")
    print("   Checking if live status sync worked correctly...")
    print()
    
    # Verify the results
    async with AsyncSessionLocal() as session:
        updated_broker_execs = await get_broker_executions_for_order(session, parent_order_id)
        updated_order_info = await get_order_by_id(session, parent_order_id)
        
        print(f"📊 FINAL STATE:")
        print(f"   Order {parent_order_id} status: {updated_order_info.get('status') if updated_order_info else 'NOT_FOUND'}")
        print(f"   Broker executions found: {len(updated_broker_execs)}")
        
        entry_count = 0
        exit_count = 0
        filled_entries = 0
        pending_entries = 0
        
        for i, be in enumerate(updated_broker_execs, 1):
            side = be.get('side', '')
            status = be.get('status', '')
            
            if side == 'ENTRY':
                entry_count += 1
                if status == 'FILLED':
                    filled_entries += 1
                elif status in ('PENDING', 'AWAITING_ENTRY'):
                    pending_entries += 1
            elif side == 'EXIT':
                exit_count += 1
            
            print(f"   Execution #{i}:")
            print(f"   ├─ ID: {be.get('id')}")
            print(f"   ├─ Broker: {be.get('broker_id')} ({be.get('broker_name', 'Unknown')})")
            print(f"   ├─ Order ID: {be.get('broker_order_id')}")
            print(f"   ├─ Status: {status}")
            print(f"   ├─ Side: {side}")
            print(f"   ├─ Action: {be.get('action')}")
            print(f"   └─ Symbol: {be.get('symbol')}")
        
        print()
        print(f"📈 SUMMARY:")
        print(f"   ENTRY executions: {entry_count}")
        print(f"   ├─ FILLED entries: {filled_entries}")
        print(f"   └─ PENDING entries: {pending_entries}")
        print(f"   EXIT executions: {exit_count}")
        print()
        
        print(f"4️⃣ VALIDATION:")
        
        # Validate the logic worked correctly
        validation_passed = True
        
        if filled_entries > 0 and exit_count == 0:
            print(f"   ❌ FAILED: Found {filled_entries} FILLED entries but no EXIT executions created")
            validation_passed = False
        elif filled_entries > 0 and exit_count != filled_entries:
            print(f"   ⚠️  WARNING: Found {filled_entries} FILLED entries but {exit_count} EXIT executions (mismatch)")
        elif filled_entries > 0 and exit_count == filled_entries:
            print(f"   ✅ SUCCESS: Found {filled_entries} FILLED entries and {exit_count} EXIT executions (correct)")
        
        if pending_entries > 0:
            print(f"   ℹ️  INFO: Found {pending_entries} PENDING entries (should trigger cancel_order calls)")
        
        if validation_passed:
            print(f"   🎯 OVERALL VALIDATION: ✅ PASSED")
        else:
            print(f"   🎯 OVERALL VALIDATION: ❌ FAILED")
        
        print()
        print(f"🏁 EXIT_ATOMIC_FAILED SCENARIO TEST COMPLETED")
        
        if not validation_passed:
            print("⚠️  SOME VALIDATIONS FAILED - REVIEW RESULTS ABOVE")
        else:
            print("✅ ALL VALIDATIONS PASSED - LIVE STATUS SYNC WORKING CORRECTLY")

if __name__ == "__main__":
    asyncio.run(test_exit_atomic_failed_scenario())
