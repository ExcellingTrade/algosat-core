#!/usr/bin/env python3

import sys
import os
sys.path.append('/opt/algosat')

from algosat.api.routes.logs import get_log_files_for_date, get_available_log_dates

def test_logs():
    print("=== Available Log Dates ===")
    dates = get_available_log_dates()
    print(f"Available dates: {dates}")
    
    if dates:
        latest_date = dates[0]
        print(f"\n=== Log Files for {latest_date} ===")
        files = get_log_files_for_date(latest_date)
        
        for f in files:
            print(f"Name: {f.name}")
            print(f"Type: {f.type}")
            print(f"Size: {f.size} bytes")
            print(f"Path: {f.path}")
            print("---")
        
        # Group by type
        print(f"\n=== Summary by Type ===")
        types = {}
        for f in files:
            if f.type not in types:
                types[f.type] = []
            types[f.type].append(f.name)
        
        for log_type, file_names in types.items():
            print(f"{log_type}: {file_names}")
        
        # Test strategy extraction
        print(f"\n=== Available Strategies ===")
        strategies = set()
        for f in files:
            if f.type.startswith("strategy-"):
                strategy_name = f.type.replace("strategy-", "")
                strategies.add(strategy_name)
        
        print(f"Strategies found: {sorted(list(strategies))}")

def test_specific_strategy_logs():
    print(f"\n=== Testing Strategy-Specific Log Filtering ===")
    files = get_log_files_for_date('2025-08-07')
    
    # Test filtering by strategy
    for strategy in ['optionsell', 'optionbuy', 'swinghighlowbuy','swinghighlowsell']:
        strategy_files = [f for f in files if f.type == f"strategy-{strategy}"]
        print(f"Strategy '{strategy}': {len(strategy_files)} files")
        for f in strategy_files:
            print(f"  - {f.name} ({f.size} bytes)")

if __name__ == "__main__":
    test_logs()
    test_specific_strategy_logs()
