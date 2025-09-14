#!/usr/bin/env python3
"""
Test script for logs API functionality
"""
import sys
import os
sys.path.append('/opt/algosat')

from algosat.api.routes.logs import get_log_files_for_date, get_available_log_dates

def test_logs_api():
    print("=== Testing Logs API ===")
    
    # Test available dates
    print("\n1. Testing get_available_log_dates():")
    try:
        dates = get_available_log_dates()
        print(f"Found {len(dates)} available dates:")
        for date in dates[:5]:  # Show first 5
            print(f"  - {date}")
    except Exception as e:
        print(f"Error: {e}")
    
    # Test log files for specific date
    print("\n2. Testing get_log_files_for_date('2025-07-25'):")
    try:
        files = get_log_files_for_date('2025-07-25')
        print(f"Found {len(files)} log files:")
        for file in files:
            print(f"  - {file.name} (type: {file.type}, size: {file.size} bytes)")
    except Exception as e:
        print(f"Error: {e}")
    
    # Test filtering by type
    print("\n3. Testing filtering by log type:")
    try:
        files = get_log_files_for_date('2025-07-25')
        
        api_files = [f for f in files if f.type == 'api']
        algosat_files = [f for f in files if f.type == 'algosat']
        broker_files = [f for f in files if f.type == 'broker-monitor']
        
        print(f"  - API files: {len(api_files)}")
        for f in api_files:
            print(f"    * {f.name}")
            
        print(f"  - Algosat files: {len(algosat_files)}")
        for f in algosat_files:
            print(f"    * {f.name}")
            
        print(f"  - Broker monitor files: {len(broker_files)}")
        for f in broker_files:
            print(f"    * {f.name}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_logs_api()
