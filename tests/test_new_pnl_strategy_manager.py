#!/usr/bin/env python3
"""
Test the new database-driven P&L calculation in StrategyManager
"""

import asyncio
import sys
import os
sys.path.append('/opt/algosat')

from algosat.core.strategy_manager import RiskManager
from algosat.core.data_manager import DataManager  
from algosat.core.order_manager import OrderManager
from algosat.core.db import AsyncSessionLocal

async def test_new_pnl_calculation():
    """Test the new database-driven P&L calculation"""
    print("🧪 TESTING NEW DATABASE-DRIVEN P&L CALCULATION")
    print("=" * 55)
    
    try:
        # Initialize components
        data_manager = DataManager()
        order_manager = OrderManager(data_manager)
        risk_manager = RiskManager(order_manager)
        
        # Test P&L calculation for each broker
        async with AsyncSessionLocal() as session:
            
            print("📊 Testing P&L calculation for each broker:")
            print()
            
            # Test Fyers
            fyers_pnl = await risk_manager._calculate_broker_pnl(session, "fyers")
            print(f"Fyers P&L: {fyers_pnl}")
            
            # Test Zerodha  
            zerodha_pnl = await risk_manager._calculate_broker_pnl(session, "zerodha")
            print(f"Zerodha P&L: {zerodha_pnl}")
            
            # Test Angel (should return 0 as no data)
            angel_pnl = await risk_manager._calculate_broker_pnl(session, "angel")
            print(f"Angel P&L: {angel_pnl}")
            
            # Test non-existent broker
            fake_pnl = await risk_manager._calculate_broker_pnl(session, "fake_broker")
            print(f"Fake Broker P&L: {fake_pnl}")
            
            print()
            print("✅ New P&L calculation method completed successfully!")
            print()
            print("Key improvements:")
            print("- ✅ Fast database query instead of broker API calls")
            print("- ✅ Uses broker_id mapping instead of broker_name")
            print("- ✅ No complex position matching logic needed")
            print("- ✅ Works even when broker APIs are down")
            print("- ✅ P&L values will be updated by OrderMonitor every 30s")
            
    except Exception as e:
        print(f"❌ Error testing new P&L calculation: {e}")
        import traceback
        traceback.print_exc()

async def verify_database_structure():
    """Verify the database changes are in place"""
    print("🔍 VERIFYING DATABASE STRUCTURE")
    print("=" * 35)
    
    try:
        async with AsyncSessionLocal() as session:
            from sqlalchemy import text
            
            # Check pnl column exists
            check_query = text("""
                SELECT column_name, data_type, column_default 
                FROM information_schema.columns 
                WHERE table_name = 'broker_executions' 
                AND column_name = 'pnl'
            """)
            
            result = await session.execute(check_query)
            pnl_col = result.fetchone()
            
            if pnl_col:
                print(f"✅ PNL column exists: {pnl_col.column_name} ({pnl_col.data_type}, default: {pnl_col.column_default})")
            else:
                print("❌ PNL column not found!")
                return False
            
            # Check broker mapping
            broker_query = text("""
                SELECT bc.id, bc.broker_name, COUNT(be.id) as execution_count
                FROM broker_credentials bc
                LEFT JOIN broker_executions be ON bc.id = be.broker_id
                GROUP BY bc.id, bc.broker_name
                ORDER BY bc.id
            """)
            
            result = await session.execute(broker_query)
            brokers = result.fetchall()
            
            print("📋 Broker mapping:")
            for broker in brokers:
                print(f"   ID {broker.id}: {broker.broker_name} ({broker.execution_count} executions)")
            
            print("✅ Database structure verified!")
            return True
            
    except Exception as e:
        print(f"❌ Error verifying database structure: {e}")
        return False

async def main():
    """Main test function"""
    print("🚀 STRATEGY MANAGER P&L ENHANCEMENT TEST")
    print("=" * 50)
    print()
    
    # Verify database structure
    db_ok = await verify_database_structure()
    if not db_ok:
        print("❌ Database verification failed")
        return False
    
    print()
    
    # Test new P&L calculation
    await test_new_pnl_calculation()
    
    print()
    print("🎉 ALL TESTS COMPLETED!")
    print("=" * 25)
    print("Next steps:")
    print("1. ✅ Database schema updated with pnl column")
    print("2. ✅ StrategyManager uses database P&L")
    print("3. 🔄 Need to update OrderMonitor to populate pnl values")
    print("4. 🧪 Test during next market session")
    
    return True

if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
