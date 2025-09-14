#!/usr/bin/env python3
"""
Simple test script for logs directory structure
"""
import os
import re
from pathlib import Path
from datetime import datetime

LOGS_BASE_DIR = Path("/opt/algosat/logs")

def test_log_structure():
    print("=== Testing Log Directory Structure ===")
    
    # Check for date directories
    print("\n1. Available date directories:")
    if LOGS_BASE_DIR.exists():
        for item in LOGS_BASE_DIR.iterdir():
            if item.is_dir() and re.match(r'\d{4}-\d{2}-\d{2}', item.name):
                print(f"  - {item.name}")
                
                # List files in date directory
                for log_file in item.glob("*.log*"):
                    size = log_file.stat().st_size
                    print(f"    * {log_file.name} ({size} bytes)")
    
    # Test log type detection
    print("\n2. Testing log type detection:")
    today = "2025-07-25"
    date_dir = LOGS_BASE_DIR / today
    
    if date_dir.exists():
        for log_file in date_dir.glob("*.log*"):
            filename = log_file.name
            log_type = "unknown"
            
            if filename.startswith("api-") and filename.endswith(".log"):
                log_type = "api"
            elif filename.startswith("algosat-") and filename.endswith(".log"):
                log_type = "algosat"  
            elif filename.startswith("broker_monitor-") and filename.endswith(".log"):
                log_type = "broker-monitor"
            
            print(f"  - {filename} -> {log_type}")
    
    # Test rollover file detection
    print("\n3. Testing rollover file patterns:")
    rollover_pattern = r"(api|algosat|broker_monitor)-(\d{4}-\d{2}-\d{2})\.log\.(\d+)"
    
    for log_file in LOGS_BASE_DIR.rglob("*.log.*"):
        match = re.match(rollover_pattern, log_file.name)
        if match:
            file_type = match.group(1)
            file_date = match.group(2)
            rollover_num = match.group(3)
            normalized_type = "broker-monitor" if file_type == "broker_monitor" else file_type
            print(f"  - {log_file.name} -> type: {normalized_type}, date: {file_date}, rollover: {rollover_num}")

if __name__ == "__main__":
    test_log_structure()
