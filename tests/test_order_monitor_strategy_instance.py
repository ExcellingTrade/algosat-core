#!/usr/bin/env python3
"""
Test script to verify OrderMonitor properly uses strategy instance when provided.
This test checks that the strategy instance is prioritized over database strategy lookup.
"""

import asyncio
import sys
import os
from unittest.mock import Mock, AsyncMock, patch

# Add the project root to Python path
sys.path.insert(0, '/opt/algosat')

from algosat.core.order_monitor import OrderMonitor
from algosat.core.data_manager import DataManager
from algosat.core.order_manager import OrderManager
from algosat.core.order_cache import OrderCache
from algosat.common.logger import get_logger

logger = get_logger("TestOrderMonitorStrategyInstance")


class MockStrategy:
    """Mock strategy class to simulate a real strategy instance."""
    
    def __init__(self, strategy_id=1):
        self.id = strategy_id
        self.name = f"MockStrategy_{strategy_id}"
    
    def evaluate_exit(self, order_row):
        """Mock evaluate_exit method that returns False (don't exit)."""
        logger.info(f"MockStrategy.evaluate_exit called with order_row: {order_row}")
        return False


async def test_strategy_instance_usage():
    """Test that OrderMonitor uses strategy instance when provided."""
    
    logger.info("=== Testing OrderMonitor Strategy Instance Usage ===")
    
    # Create mock dependencies
    data_manager = Mock(spec=DataManager)
    data_manager.ensure_broker = AsyncMock()
    
    order_manager = Mock(spec=OrderManager)
    order_cache = Mock(spec=OrderCache)
    
    # Create mock strategy instance
    strategy_instance = MockStrategy(strategy_id=1)
    
    # Create OrderMonitor with strategy instance
    order_monitor = OrderMonitor(
        order_id=123,
        data_manager=data_manager,
        order_manager=order_manager,
        order_cache=order_cache,
        strategy_instance=strategy_instance,
        signal_monitor_seconds=1  # Fast for testing
    )
    
    # Test 1: Verify strategy instance is stored
    assert order_monitor.get_strategy_instance() == strategy_instance
    logger.info("✓ Strategy instance correctly stored in OrderMonitor")
    
    # Test 2: Test call_strategy_method functionality
    with patch.object(strategy_instance, 'evaluate_exit') as mock_evaluate_exit:
        mock_evaluate_exit.return_value = False
        
        result = await order_monitor.call_strategy_method('evaluate_exit', {'order_id': 123})
        assert result == False
        mock_evaluate_exit.assert_called_once_with({'order_id': 123})
        logger.info("✓ call_strategy_method works correctly")
    
    # Test 3: Test strategy property
    strategy_result = await order_monitor.strategy()
    assert strategy_result == strategy_instance
    logger.info("✓ strategy property returns strategy instance when available")
    
    # Test 4: Create OrderMonitor without strategy instance
    order_monitor_no_instance = OrderMonitor(
        order_id=124,
        data_manager=data_manager,
        order_manager=order_manager,
        order_cache=order_cache,
        strategy_instance=None,  # No strategy instance
        signal_monitor_seconds=1
    )
    
    assert order_monitor_no_instance.get_strategy_instance() is None
    logger.info("✓ OrderMonitor without strategy instance works correctly")
    
    # Test 5: Test call_strategy_method returns None when no strategy instance
    result = await order_monitor_no_instance.call_strategy_method('evaluate_exit', {'order_id': 124})
    assert result is None
    logger.info("✓ call_strategy_method returns None when no strategy instance")
    
    logger.info("=== All OrderMonitor Strategy Instance Tests Passed! ===")


async def test_signal_monitor_logic():
    """Test that _signal_monitor method properly uses strategy instance."""
    
    logger.info("=== Testing _signal_monitor Strategy Instance Logic ===")
    
    # Create mock dependencies
    data_manager = Mock(spec=DataManager)
    data_manager.ensure_broker = AsyncMock()
    
    order_manager = Mock(spec=OrderManager)
    order_cache = Mock(spec=OrderCache)
    
    # Create mock strategy instance
    strategy_instance = MockStrategy(strategy_id=1)
    
    # Create OrderMonitor with strategy instance
    order_monitor = OrderMonitor(
        order_id=125,
        data_manager=data_manager,
        order_manager=order_manager,
        order_cache=order_cache,
        strategy_instance=strategy_instance,
        signal_monitor_seconds=1
    )
    
    # Mock the _get_order_and_strategy method
    mock_order_row = {'id': 125, 'status': 'OPEN'}
    mock_strategy_symbol = {'symbol': 'NIFTY50'}
    mock_strategy_config = {'id': 1, 'trade': '{}'}
    mock_db_strategy = {'id': 1, 'name': 'DatabaseStrategy'}
    
    with patch.object(order_monitor, '_get_order_and_strategy') as mock_get_order_strategy:
        mock_get_order_strategy.return_value = (
            mock_order_row, 
            mock_strategy_symbol, 
            mock_strategy_config, 
            mock_db_strategy
        )
        
        # Mock the evaluate_exit method to return False (don't exit)
        with patch.object(strategy_instance, 'evaluate_exit') as mock_evaluate_exit:
            mock_evaluate_exit.return_value = False
            
            # Start the monitor (it should call _signal_monitor)
            # We'll stop it after one iteration
            async def stop_after_delay():
                await asyncio.sleep(0.1)  # Let it run one iteration
                order_monitor.stop()
            
            # Run both the monitor and the stopper
            await asyncio.gather(
                order_monitor._signal_monitor(),
                stop_after_delay(),
                return_exceptions=True
            )
            
            # Verify that our strategy instance's evaluate_exit was called
            mock_evaluate_exit.assert_called_with(mock_order_row)
            logger.info("✓ _signal_monitor correctly used strategy instance")
    
    logger.info("=== _signal_monitor Strategy Instance Logic Tests Passed! ===")


async def main():
    """Run all tests."""
    try:
        await test_strategy_instance_usage()
        await test_signal_monitor_logic()
        logger.info("🎉 All tests completed successfully!")
    except Exception as e:
        logger.error(f"❌ Test failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
