#!/usr/bin/env python3
"""
Test script to verify logger rollover behavior
"""
import sys
import os
sys.path.append('/opt/algosat')

from algosat.common.logger import get_logger

def test_logger_rollover():
    print("=== Testing Logger Rollover ===")
    
    # Get different types of loggers
    main_logger = get_logger('test_main')
    api_logger = get_logger('api.test') 
    broker_logger = get_logger('broker_monitor')
    
    # Generate some test log entries
    for i in range(10):
        main_logger.info(f"Test main log entry {i+1}")
        api_logger.info(f"Test API log entry {i+1}")
        broker_logger.info(f"Test broker monitor log entry {i+1}")
    
    print("✓ Generated test log entries")
    
    # Check which files were created
    import glob
    from pathlib import Path
    
    logs_dir = Path("/opt/algosat/logs")
    today = "2025-07-25"
    date_dir = logs_dir / today
    
    print(f"\n=== Files in {date_dir} ===")
    if date_dir.exists():
        for log_file in sorted(date_dir.glob("*.log*")):
            size = log_file.stat().st_size
            print(f"  - {log_file.name} ({size} bytes)")
    
    print("\n=== Testing Log Type Filtering ===")
    # Test the log filtering logic
    log_files = []
    
    if date_dir.exists():
        for log_file in date_dir.glob("*.log*"):
            filename = log_file.name
            log_type = None
            
            if filename.startswith("api-") and filename.endswith(".log"):
                log_type = "api"
            elif filename.startswith("algosat-") and filename.endswith(".log"):
                log_type = "algosat"
            elif filename.startswith("broker_monitor-") and filename.endswith(".log"):
                log_type = "broker-monitor"
            elif ".log." in filename:
                # Rollover file
                if filename.startswith("api-"):
                    log_type = "api"
                elif filename.startswith("algosat-"):
                    log_type = "algosat"
                elif filename.startswith("broker_monitor-"):
                    log_type = "broker-monitor"
            
            if log_type:
                log_files.append((filename, log_type))
    
    # Group by type
    api_files = [f for f, t in log_files if t == 'api']
    algosat_files = [f for f, t in log_files if t == 'algosat']
    broker_files = [f for f, t in log_files if t == 'broker-monitor']
    
    print(f"  - API files: {len(api_files)}")
    for f in api_files:
        print(f"    * {f}")
        
    print(f"  - Algosat files: {len(algosat_files)}")
    for f in algosat_files:
        print(f"    * {f}")
        
    print(f"  - Broker monitor files: {len(broker_files)}")
    for f in broker_files:
        print(f"    * {f}")

if __name__ == "__main__":
    test_logger_rollover()
