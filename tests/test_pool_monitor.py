#!/usr/bin/env python3
"""
Database connection pool monitor utility
"""

import sys
import asyncio
from datetime import datetime

# Add the algosat directory to the Python path
sys.path.insert(0, '/opt/algosat')

async def monitor_pool():
    """Monitor database connection pool status"""
    print('🔌 Database Connection Pool Monitor')
    print('=' * 50)
    
    try:
        from algosat.core.db import engine
        
        # Get pool status
        pool = engine.pool
        
        print(f'📊 Pool Configuration:')
        print(f'  - Pool Size: {pool.size()}')
        print(f'  - Max Overflow: {pool._max_overflow}')
        print(f'  - Current Checked Out: {pool.checkedout()}')
        print(f'  - Current Checked In: {pool.checkedin()}')
        print(f'  - Current Overflow: {pool.overflow()}')
        # print(f'  - Current Invalid: {pool.invalidated()}')  # This method doesn't exist
        
        total_available = pool.size() + pool._max_overflow
        current_used = pool.checkedout() + pool.overflow()
        
        print(f'\n📈 Pool Utilization:')
        print(f'  - Total Available: {total_available}')
        print(f'  - Currently Used: {current_used}')
        print(f'  - Available: {total_available - current_used}')
        print(f'  - Utilization: {(current_used / total_available * 100):.1f}%')
        
        # Test a simple connection
        print(f'\n🔍 Testing connection...')
        from algosat.core.db import AsyncSessionLocal
        async with AsyncSessionLocal() as session:
            from sqlalchemy import text
            result = await session.execute(text("SELECT 1 as test"))
            test_val = result.scalar()
            print(f'  ✅ Connection test passed: {test_val}')
            
        print(f'\n📊 Pool Status After Test:')
        print(f'  - Checked Out: {pool.checkedout()}')
        print(f'  - Checked In: {pool.checkedin()}')
        print(f'  - Overflow: {pool.overflow()}')
        
    except Exception as e:
        print(f'❌ Error monitoring pool: {e}')
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(monitor_pool())
