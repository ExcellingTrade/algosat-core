#!/usr/bin/env python3
"""
Test the actual strategy context mapping from database values.
"""

import os
import sys
sys.path.insert(0, '/opt/algosat/algosat')

from common.logger import get_logger, set_strategy_context

def test_database_strategy_contexts():
    """Test with the actual strategy_key values from the database."""
    print("🔍 Testing with actual database strategy_key values...")
    
    # Database values -> expected lowercase contexts -> expected log files
    strategy_mappings = [
        ("OptionBuy", "optionbuy", "optionbuy-2025-08-06.log"),
        ("OptionSell", "optionsell", "optionsell-2025-08-06.log"),
        ("SwingHighLowBuy", "swinghighlowbuy", "swinghighlowbuy-2025-08-06.log"),
        ("SwingHighLowSell", "swinghighlowsell", "swinghighlowsell-2025-08-06.log")
    ]
    
    print("🎯 Expected mappings:")
    for db_key, lowercase_context, expected_file in strategy_mappings:
        print(f"   {db_key} -> {lowercase_context} -> {expected_file}")
    
    print("\n📝 Testing actual logging with these contexts...")
    
    for db_key, lowercase_context, expected_file in strategy_mappings:
        print(f"\n🧪 Testing {db_key} strategy...")
        
        # Test with the lowercase context (as strategy_runner.py does)
        with set_strategy_context(lowercase_context):
            logger = get_logger("test_strategy")
            logger.info(f"Test log entry for {db_key} strategy (context: {lowercase_context})")
            print(f"   ✅ Logged test message for {lowercase_context}")
    
    print("\n🔍 Now check /opt/algosat/logs/2025-08-06/ for new log files!")

if __name__ == "__main__":
    test_database_strategy_contexts()
