#!/usr/bin/env python3
"""
Test get_broker_risk_summary to see what data it returns
"""

import asyncio
import sys
import os
sys.path.append('/opt/algosat')

from algosat.core.db import get_broker_risk_summary, AsyncSessionLocal

async def test_broker_risk_summary():
    """Test what get_broker_risk_summary actually returns"""
    print("🧪 TESTING get_broker_risk_summary DATA STRUCTURE")
    print("=" * 55)
    
    try:
        async with AsyncSessionLocal() as session:
            risk_data = await get_broker_risk_summary(session)
            
            print(f"📋 Risk data structure:")
            print(f"Total brokers: {risk_data.get('total_brokers', 0)}")
            print(f"Brokers data type: {type(risk_data.get('brokers', []))}")
            print(f"Number of brokers: {len(risk_data.get('brokers', []))}")
            print()
            
            print("📊 Broker details:")
            for i, broker in enumerate(risk_data.get('brokers', [])):
                print(f"  Broker {i+1}:")
                print(f"    ID: {broker.get('id')}")
                print(f"    broker_name: {broker.get('broker_name')}")  # This should exist
                print(f"    max_loss: {broker.get('max_loss')}")
                print(f"    max_profit: {broker.get('max_profit')}")
                print(f"    is_enabled: {broker.get('is_enabled')}")
                print(f"    trade_execution_enabled: {broker.get('trade_execution_enabled')}")
                print(f"    status: {broker.get('status')}")
                print()
            
            print("✅ get_broker_risk_summary test completed!")
            
    except Exception as e:
        print(f"❌ Error testing get_broker_risk_summary: {e}")
        import traceback
        traceback.print_exc()

async def main():
    await test_broker_risk_summary()

if __name__ == "__main__":
    asyncio.run(main())
