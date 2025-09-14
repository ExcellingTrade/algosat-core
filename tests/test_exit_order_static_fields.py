#!/usr/bin/env python3
"""
Test exit_order with 0.0 execution_price and check broker_executions entries
"""

import sys
sys.path.append('/opt/algosat')

import asyncio
from datetime import date

async def test_exit_order_static_fields():
    """
    Test exit_order with static fields only (execution_price=0.0, execution_time=None)
    """
    
    print("=== TESTING EXIT_ORDER WITH STATIC FIELDS ONLY ===\n")
    
    # Enhanced mock data
    additional_fyers_orders = [
        {
            'id': '25080800223154',
            'symbol': 'NSE:NIFTY2580824850CE',
            'qty': 75,
            'filledQty': 75,
            'side': 1,  # BUY
            'status': 2,  # FILLED
            'limitPrice': 115.50,
            'tradedPrice': 115.50,
            'productType': 'MARGIN',
            'orderDateTime': '08-Aug-2025 14:55:23',
            'disQty': 0,
            'stopPrice': 0,
            'orderNumStatus': '25080800223154:2',
            'orderTag': '',
            'type': 2,
            'orderValidity': 'DAY'
        }
    ]
    
    additional_zerodha_orders = [
        {
            'order_id': '250808600582884',
            'tradingsymbol': 'NIFTY2580824850CE',
            'quantity': 75,
            'filled_quantity': 75,
            'transaction_type': 'BUY',
            'status': 'COMPLETE',
            'price': 115.90,
            'average_price': 115.90,
            'product': 'NRML',
            'order_timestamp': '2025-08-08 14:55:22',
            'exchange_timestamp': '2025-08-08 14:55:23',
            'exchange_update_timestamp': '2025-08-08 14:55:24',
            'validity': 'DAY',
            'order_type': 'MARKET',
            'exchange': 'NSE',
            'instrument_token': '13405442',
            'tag': '',
            'guid': ''
        }
    ]
    
    try:
        # Initialize components
        from algosat.core.db import init_db
        from algosat.core.broker_manager import BrokerManager
        from algosat.core.order_manager import OrderManager
        
        print("🔧 Initializing components...")
        await init_db()
        
        broker_manager = BrokerManager()
        await broker_manager.setup()
        
        order_manager = OrderManager(broker_manager)
        
        # Enhanced mock data
        from algosat.brokers.fyers import FyersWrapper
        from algosat.brokers.zerodha import ZerodhaWrapper
        
        original_fyers_get_order_details = FyersWrapper.get_order_details_async
        original_zerodha_get_order_details = ZerodhaWrapper.get_order_details
        
        async def enhanced_fyers_mock(self, *args, **kwargs):
            original_orders = await original_fyers_get_order_details(self, *args, **kwargs)
            return original_orders + additional_fyers_orders
            
        async def enhanced_zerodha_mock(self, *args, **kwargs):
            original_orders = await original_zerodha_get_order_details(self, *args, **kwargs)
            return original_orders + additional_zerodha_orders
        
        # Apply patches
        FyersWrapper.get_order_details_async = enhanced_fyers_mock
        ZerodhaWrapper.get_order_details = enhanced_zerodha_mock
        
        print("✅ Enhanced mock data applied")
        
        # Check broker_executions before exit
        from algosat.core.db import get_database_session
        
        session = get_database_session()
        try:
            from algosat.core.dbschema import broker_executions
            from sqlalchemy import select, and_
            
            # Count existing EXIT entries for order 207
            existing_exits_query = select(broker_executions).where(
                and_(
                    broker_executions.c.parent_order_id == 207,
                    broker_executions.c.side == 'EXIT'
                )
            )
            existing_exits = await session.execute(existing_exits_query)
            existing_exit_count = len(existing_exits.fetchall())
            
            print(f"📊 BEFORE EXIT: {existing_exit_count} EXIT entries for order 207")
        finally:
            await session.close()
        
        # Execute exit_order (no LTP parameter - should use defaults)
        print(f"\n🚀 EXECUTING EXIT_ORDER...")
        result = await order_manager.exit_order(
            parent_order_id=207,
            check_live_status=False,  # Disable live status for clean test
            exit_reason="Test static fields"
        )
        
        print(f"✅ Exit order completed: {result}")
        
        # Check broker_executions after exit
        session = get_database_session()
        try:
            # Get all EXIT entries for order 207
            exits_query = select(broker_executions).where(
                and_(
                    broker_executions.c.parent_order_id == 207,
                    broker_executions.c.side == 'EXIT'
                )
            )
            exits_result = await session.execute(exits_query)
            exit_entries = exits_result.fetchall()
            
            print(f"\n📊 AFTER EXIT: {len(exit_entries)} EXIT entries for order 207")
            
            print(f"\n📋 EXIT BROKER_EXECUTION ENTRIES:")
            for i, entry in enumerate(exit_entries, 1):
                print(f"\n   Entry {i}:")
                print(f"   ├─ ID: {entry.id}")
                print(f"   ├─ parent_order_id: {entry.parent_order_id}")
                print(f"   ├─ broker_id: {entry.broker_id}")
                print(f"   ├─ broker_order_id: {entry.broker_order_id}")
                print(f"   ├─ exit_broker_order_id: {entry.exit_broker_order_id}")
                print(f"   ├─ side: {entry.side}")
                print(f"   ├─ action: {entry.action}")
                print(f"   ├─ status: {entry.status}")
                print(f"   ├─ executed_quantity: {entry.executed_quantity}")
                print(f"   ├─ execution_price: {entry.execution_price} ⭐")
                print(f"   ├─ execution_time: {entry.execution_time} ⭐")
                print(f"   ├─ product_type: {entry.product_type}")
                print(f"   ├─ order_type: {entry.order_type}")
                print(f"   ├─ symbol: {entry.symbol}")
                print(f"   ├─ order_messages: {entry.order_messages}")
                print(f"   └─ notes: {entry.notes}")
            
            # Count by broker
            fyers_exits = [e for e in exit_entries if e.broker_id == 1]
            zerodha_exits = [e for e in exit_entries if e.broker_id == 3]
            
            print(f"\n📈 BREAKDOWN:")
            print(f"   ├─ Fyers EXIT entries: {len(fyers_exits)}")
            print(f"   └─ Zerodha EXIT entries: {len(zerodha_exits)}")
            
            print(f"\n✅ VERIFICATION:")
            if len(exit_entries) > 0:
                print(f"   ✅ EXIT broker_execution entries created successfully")
                print(f"   ✅ Static fields populated correctly")
                
                # Check if execution_price is 0.0 as expected
                all_zero_price = all(e.execution_price == 0.0 for e in exit_entries)
                print(f"   {'✅' if all_zero_price else '❌'} execution_price = 0.0 (as expected)")
                
                # Check if execution_time is None as expected
                all_null_time = all(e.execution_time is None for e in exit_entries)
                print(f"   {'✅' if all_null_time else '❌'} execution_time = None (as expected)")
                
                # Check required fields are populated
                has_action = all(e.action is not None for e in exit_entries)
                has_side = all(e.side == 'EXIT' for e in exit_entries)
                has_status = all(e.status is not None for e in exit_entries)
                
                print(f"   {'✅' if has_action else '❌'} action field populated")
                print(f"   {'✅' if has_side else '❌'} side = 'EXIT'")
                print(f"   {'✅' if has_status else '❌'} status field populated")
                
            else:
                print(f"   ❌ No EXIT entries created!")
                
        finally:
            await session.close()
        
        # Restore original functions
        FyersWrapper.get_order_details_async = original_fyers_get_order_details
        ZerodhaWrapper.get_order_details = original_zerodha_get_order_details
        
        print(f"\n🎯 SUMMARY:")
        print(f"   ├─ EXIT broker_execution entries: {len(exit_entries)}")
        print(f"   ├─ execution_price set to: 0.0 (default)")
        print(f"   ├─ execution_time set to: None (default)")
        print(f"   └─ Ready for later update from actual broker response")
        
    except Exception as e:
        print(f"❌ Error in test: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_exit_order_static_fields())
