#!/usr/bin/env python3
"""
Test the new logger implementation without rollover
"""
import sys
import os
sys.path.append('/opt/algosat')

from algosat.common.logger import get_logger

def test_new_logger():
    print("=== Testing New Logger Implementation (No Rollover) ===")
    
    # Test different types of loggers
    main_logger = get_logger('test_main')
    api_logger = get_logger('api.test')
    broker_logger = get_logger('broker_monitor')
    
    # Generate multiple log entries
    for i in range(20):
        main_logger.info(f"Main logger test entry {i+1}")
        api_logger.info(f"API logger test entry {i+1}")
        broker_logger.info(f"Broker monitor test entry {i+1}")
    
    print("✓ Generated 60 test log entries (20 per logger type)")
    
    # Check the resulting files
    import glob
    from pathlib import Path
    
    logs_dir = Path("/opt/algosat/logs")
    today = "2025-07-27"  # Current date
    date_dir = logs_dir / today
    
    print(f"\n=== Files in {date_dir} after test ===")
    if date_dir.exists():
        for log_file in sorted(date_dir.glob("*.log*")):
            size = log_file.stat().st_size
            line_count = 0
            try:
                with open(log_file, 'r') as f:
                    line_count = sum(1 for _ in f)
            except:
                pass
            print(f"  - {log_file.name}: {size} bytes, {line_count} lines")
    
    # Check for any rollover files (should be none)
    rollover_files = list(date_dir.glob("*.log.*")) if date_dir.exists() else []
    if rollover_files:
        print(f"\n❌ WARNING: Found {len(rollover_files)} unexpected rollover files:")
        for rf in rollover_files:
            print(f"  - {rf.name}")
    else:
        print("\n✅ NO rollover files found - working correctly!")

if __name__ == "__main__":
    test_new_logger()
