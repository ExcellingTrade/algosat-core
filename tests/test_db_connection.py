#!/usr/bin/env python3
"""
Simple test to check database connectivity and basic table structure.
"""

import asyncio
import sys
import os

# Add the project root to Python path
sys.path.insert(0, '/opt/algosat')

async def test_db_connection():
    try:
        from algosat.core.db import AsyncSessionLocal
        from sqlalchemy import text
        
        print("Testing database connection...")
        async with AsyncSessionLocal() as session:
            result = await session.execute(text("SELECT 1 as test"))
            test_value = result.fetchone()[0]
            print(f"✅ Database connection successful. Test value: {test_value}")
            
            # Check if tables exist
            print("\\nChecking table structure...")
            
            # Check orders table
            try:
                result = await session.execute(text("SELECT COUNT(*) FROM orders"))
                orders_count = result.fetchone()[0]
                print(f"✅ Orders table exists with {orders_count} records")
            except Exception as e:
                print(f"❌ Orders table issue: {e}")
            
            # Check broker_executions table
            try:
                result = await session.execute(text("SELECT COUNT(*) FROM broker_executions"))
                executions_count = result.fetchone()[0]
                print(f"✅ Broker_executions table exists with {executions_count} records")
            except Exception as e:
                print(f"❌ Broker_executions table issue: {e}")
                
            # Check table columns
            try:
                result = await session.execute(text("PRAGMA table_info(broker_executions)"))
                columns = result.fetchall()
                print(f"\\n📋 Broker_executions columns ({len(columns)} total):")
                for col in columns:
                    print(f"  - {col[1]} ({col[2]})")
            except Exception as e:
                print(f"❌ Could not get table info: {e}")
                
        return True
        
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🧪 Testing database connectivity...")
    success = asyncio.run(test_db_connection())
    if success:
        print("\\n🎉 Database test completed successfully!")
    else:
        print("\\n💥 Database test failed!")
        sys.exit(1)
