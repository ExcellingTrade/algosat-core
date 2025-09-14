#!/usr/bin/env python3
"""
Test the improved strategy-aware logging with dynamic routing.
"""

import os
import sys
sys.path.insert(0, '/opt/algosat/algosat')

from common.logger import get_logger, set_strategy_context

def test_dynamic_routing():
    """Test that logs dynamically route based on current strategy context."""
    print("🧪 Testing Dynamic Strategy-Aware Logging")
    print("=" * 50)
    
    # Create loggers for different modules (like in real app)
    data_manager_logger = get_logger("data_manager")
    order_manager_logger = get_logger("order_manager") 
    broker_manager_logger = get_logger("broker_manager")
    strategy_logger = get_logger("algosat.strategies.option_buy")
    
    print("📝 Loggers created for: data_manager, order_manager, broker_manager, strategy")
    
    # Test 1: No strategy context - should go to default files
    print("\n🔍 Test 1: No strategy context (default routing)")
    data_manager_logger.info("Data manager log - no context")
    order_manager_logger.info("Order manager log - no context")
    
    # Test 2: Set OptionBuy context - all should route to optionbuy file
    print("🔍 Test 2: OptionBuy strategy context")
    with set_strategy_context("optionbuy"):
        data_manager_logger.info("Data manager log - optionbuy context")
        order_manager_logger.info("Order manager log - optionbuy context")
        broker_manager_logger.info("Broker manager log - optionbuy context")
        strategy_logger.info("Strategy log - optionbuy context")
    
    # Test 3: Set OptionSell context - should switch to optionsell file
    print("🔍 Test 3: OptionSell strategy context")
    with set_strategy_context("optionsell"):
        data_manager_logger.info("Data manager log - optionsell context")
        order_manager_logger.info("Order manager log - optionsell context")
        strategy_logger.info("Strategy log - optionsell context")
    
    # Test 4: Back to no context - should return to default
    print("🔍 Test 4: Back to no context")
    data_manager_logger.info("Data manager log - back to default")
    
    print("\n✅ Dynamic routing test completed!")
    print("🔍 Check log files in /opt/algosat/logs/2025-08-06/")

if __name__ == "__main__":
    test_dynamic_routing()
