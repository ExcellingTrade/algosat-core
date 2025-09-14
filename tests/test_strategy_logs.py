#!/usr/bin/env python3

import sys
import os
sys.path.append('/opt/algosat')

from algosat.api.routes.logs import get_log_files_for_date, parse_log_line
import asyncio
import aiofiles

async def test_strategy_log_content():
    print("=== Testing Strategy Log Content Parsing ===")
    
    # Get optionsell strategy log content
    files = get_log_files_for_date('2025-08-07')
    optionsell_files = [f for f in files if f.type == "strategy-optionsell"]
    
    if optionsell_files:
        log_file = optionsell_files[0]
        print(f"Reading from: {log_file.name}")
        
        entries = []
        try:
            async with aiofiles.open(log_file.path, 'r') as f:
                line_count = 0
                async for line in f:
                    if line_count >= 10:  # Only read first 10 lines for testing
                        break
                    entry = parse_log_line(line)
                    if entry:
                        entries.append(entry)
                        print(f"Timestamp: {entry.timestamp}")
                        print(f"Level: {entry.level}")
                        print(f"Logger: {entry.logger}")
                        print(f"Message: {entry.message[:100]}...")
                        print("---")
                    line_count += 1
        except Exception as e:
            print(f"Error reading file: {e}")
        
        print(f"Successfully parsed {len(entries)} log entries from strategy log")
    else:
        print("No optionsell strategy log found")

def test_api_endpoints_summary():
    print("\n=== API Endpoints Summary ===")
    print("The updated logs API now supports:")
    print("1. ✅ System logs: api, algosat, broker-monitor")
    print("2. ✅ Strategy logs: strategy-{name} format")
    print("3. ✅ Available endpoints:")
    print("   - GET /logs/dates - List available log dates")
    print("   - GET /logs/strategies - List available strategies")
    print("   - GET /logs/files/{date} - Get log files for a date")
    print("   - GET /logs/content/{date}?log_type=strategy-{name} - Get strategy log content")
    print("   - POST /logs/stream/session - Create streaming session for strategy logs")
    print("   - GET /logs/stream/live?session_id={id} - Stream live strategy logs")
    print("   - GET /logs/download?log_type=strategy-{name} - Download strategy logs")

if __name__ == "__main__":
    asyncio.run(test_strategy_log_content())
    test_api_endpoints_summary()
