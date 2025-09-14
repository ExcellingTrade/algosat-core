#!/usr/bin/env python3
"""
Test script to simulate the specific EXIT_ATOMIC_FAILED scenario:
1. Create broker executions with PENDING status in database
2. Mock broker returns FILLED status  
3. Call exit_order with check_live_status=True
4. Verify that status gets updated to FILLED and exit_order is called (not cancel_order)
"""

import asyncio
import sys
import os
sys.path.append('/opt/algosat')

from algosat.core.order_manager import OrderManager
from algosat.core.broker_manager import BrokerManager
from algosat.core.db import AsyncSessionLocal, get_broker_executions_for_order, get_order_by_id, update_rows_in_table
from algosat.core.dbschema import broker_executions
from algosat.common.logger import get_logger
from datetime import datetime, timezone

# Configure logging  
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = get_logger("TestPendingToFilledScenario")

async def simulate_pending_to_filled_scenario():
    """
    Simulate the exact scenario where:
    - DB shows PENDING status (order monitor hasn't updated yet)
    - Broker shows FILLED status (order was actually executed)
    - exit_order with check_live_status=True should sync and call exit (not cancel)
    """
    
    print("🚀 SIMULATING PENDING → FILLED LIVE SYNC SCENARIO")
    print("=" * 80)
    
    # Initialize components
    broker_manager = BrokerManager()
    order_manager = OrderManager(broker_manager=broker_manager)
    
    parent_order_id = 207
    
    print(f"1️⃣ SETUP: Simulating scenario where DB shows PENDING but broker shows FILLED")
    print()
    
    # First, update some broker executions to PENDING status to simulate the scenario
    async with AsyncSessionLocal() as session:
        # Get current ENTRY broker executions
        broker_execs = await get_broker_executions_for_order(session, parent_order_id)
        entry_execs = [be for be in broker_execs if be.get('side') == 'ENTRY']
        
        if not entry_execs:
            print("❌ No ENTRY executions found for testing")
            return
            
        print(f"📊 BEFORE STATUS CHANGE:")
        for i, be in enumerate(entry_execs, 1):
            print(f"   Entry #{i}: ID={be.get('id')}, Status={be.get('status')}, Broker={be.get('broker_id')}")
        
        # Update first entry execution to PENDING to simulate the scenario
        test_exec_id = entry_execs[0].get('id')
        print(f"\n🔄 SIMULATING DB OUT OF SYNC:")
        print(f"   Updating broker_execution ID={test_exec_id} to PENDING status")
        print("   (This simulates the case where order monitor hasn't updated DB yet)")
        
        await update_rows_in_table(
            target_table=broker_executions,
            condition=broker_executions.c.id == test_exec_id,
            new_values={'status': 'PENDING'}
        )
        await session.commit()
        
        # Verify the change
        updated_execs = await get_broker_executions_for_order(session, parent_order_id)
        test_exec = next((be for be in updated_execs if be.get('id') == test_exec_id), None)
        
        print(f"   ✅ Updated: ID={test_exec_id}, New Status={test_exec.get('status')}")
        print()
    
    print(f"2️⃣ TESTING: Call exit_order with check_live_status=True")
    print("   Expected behavior:")
    print("   ✓ Fetch live broker status (which will show FILLED)")
    print("   ✓ Update DB status from PENDING → FILLED")
    print("   ✓ Make DECISION → EXIT (not CANCEL) based on updated status")
    print()
    
    try:
        start_time = asyncio.get_event_loop().time()
        
        # Call exit_order with live status checking - this should sync status first
        result = await order_manager.exit_order(
            parent_order_id=parent_order_id,
            exit_reason="PENDING_TO_FILLED_SYNC_TEST",
            check_live_status=True  # Key parameter that triggers live sync
        )
        
        end_time = asyncio.get_event_loop().time()
        duration = end_time - start_time
        
        print(f"   ✅ exit_order completed in {duration:.2f} seconds")
        print()
        
    except Exception as e:
        print(f"   ❌ exit_order failed: {e}")
        import traceback
        traceback.print_exc()
        return
    
    print(f"3️⃣ VERIFICATION: Check if live sync worked correctly")
    print()
    
    # Verify the results
    async with AsyncSessionLocal() as session:
        final_execs = await get_broker_executions_for_order(session, parent_order_id)
        test_exec_final = next((be for be in final_execs if be.get('id') == test_exec_id), None)
        
        print(f"📊 FINAL STATUS CHECK:")
        print(f"   Test execution ID={test_exec_id}")
        print(f"   ├─ Status: {test_exec_final.get('status') if test_exec_final else 'NOT_FOUND'}")
        print(f"   ├─ Broker: {test_exec_final.get('broker_id') if test_exec_final else 'N/A'}")
        print(f"   └─ Symbol: {test_exec_final.get('symbol') if test_exec_final else 'N/A'}")
        print()
        
        # Count executions by side and status
        entry_filled = len([be for be in final_execs if be.get('side') == 'ENTRY' and be.get('status') == 'FILLED'])
        entry_pending = len([be for be in final_execs if be.get('side') == 'ENTRY' and be.get('status') == 'PENDING'])
        exit_count = len([be for be in final_execs if be.get('side') == 'EXIT'])
        
        print(f"📈 EXECUTION SUMMARY:")
        print(f"   ENTRY executions:")
        print(f"   ├─ FILLED: {entry_filled}")
        print(f"   └─ PENDING: {entry_pending}")
        print(f"   EXIT executions: {exit_count}")
        print()
        
        print(f"4️⃣ VALIDATION:")
        
        # Validate the scenario worked correctly
        success = True
        
        if test_exec_final and test_exec_final.get('status') == 'FILLED':
            print(f"   ✅ Status sync worked: PENDING → FILLED for test execution")
        else:
            print(f"   ❌ Status sync failed: Expected FILLED, got {test_exec_final.get('status') if test_exec_final else 'NOT_FOUND'}")
            success = False
        
        if entry_filled > 0 and exit_count >= entry_filled:
            print(f"   ✅ Correct action taken: EXIT orders created for FILLED entries")
        else:
            print(f"   ❌ Wrong action: Expected EXIT orders for {entry_filled} FILLED entries, got {exit_count}")
            success = False
        
        print()
        if success:
            print(f"🎯 SCENARIO VALIDATION: ✅ SUCCESS")
            print("   The system correctly:")
            print("   ✓ Detected live status difference (PENDING vs FILLED)")
            print("   ✓ Updated database with live status")
            print("   ✓ Made exit decision based on updated status")
            print("   ✓ Called exit_order (not cancel_order) for FILLED orders")
        else:
            print(f"🎯 SCENARIO VALIDATION: ❌ FAILED")
            print("   Review the issues above")
        
        print()
        print(f"🏁 PENDING → FILLED SYNC TEST COMPLETED")

if __name__ == "__main__":
    asyncio.run(simulate_pending_to_filled_scenario())
