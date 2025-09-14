#!/usr/bin/env python3
"""
Test script for the new rate limiting implementation.
Tests both DataProvider and BrokerManager rate limiting coordination.
"""

import asyncio
import time
import logging
import sys
import os

# Add the algosat directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'algosat'))

from typing import Dict, Any
from algosat.core.rate_limiter import get_rate_limiter, RateConfig
from algosat.core.async_retry import async_retry_with_rate_limit, RetryConfig

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("rate_limit_test")

class MockBroker:
    """Mock broker for testing."""
    
    def __init__(self, name: str, failure_rate: float = 0.0):
        self.name = name
        self.call_count = 0
        self.failure_rate = failure_rate
    
    async def get_order_details(self):
        """Mock get_order_details method."""
        self.call_count += 1
        logger.info(f"[{self.name}] get_order_details call #{self.call_count}")
        
        # Simulate occasional failures
        if self.failure_rate > 0 and (self.call_count % int(1/self.failure_rate)) == 0:
            raise Exception(f"Simulated failure for {self.name}")
        
        await asyncio.sleep(0.1)  # Simulate API call time
        return [{"order_id": f"order_{self.call_count}", "status": "complete"}]
    
    async def get_positions(self):
        """Mock get_positions method."""
        self.call_count += 1
        logger.info(f"[{self.name}] get_positions call #{self.call_count}")
        
        await asyncio.sleep(0.1)  # Simulate API call time
        return [{"symbol": "NIFTY", "quantity": 100}]
    
    async def place_order(self, order_request):
        """Mock place_order method."""
        self.call_count += 1
        logger.info(f"[{self.name}] place_order call #{self.call_count}")
        
        await asyncio.sleep(0.2)  # Simulate longer API call time
        return {"status": True, "order_id": f"order_{self.call_count}"}

async def test_rate_limiter_basic():
    """Test basic rate limiter functionality."""
    logger.info("=== Testing Basic Rate Limiter ===")
    
    rate_limiter = await get_rate_limiter()
    
    # Configure test broker
    rate_limiter.configure_broker("test_broker", RateConfig(rps=2, burst=3))
    
    # Test rapid calls
    start_time = time.time()
    for i in range(5):
        async with rate_limiter.acquire("test_broker"):
            logger.info(f"Call {i+1} at {time.time() - start_time:.2f}s")
    
    elapsed = time.time() - start_time
    logger.info(f"5 calls completed in {elapsed:.2f}s (expected ~2.5s for 2 rps)")
    
    # Print stats
    stats = rate_limiter.get_stats()
    logger.info(f"Rate limiter stats: {stats}")

async def test_retry_with_rate_limiting():
    """Test retry mechanism with rate limiting."""
    logger.info("=== Testing Retry with Rate Limiting ===")
    
    # Mock function that fails twice then succeeds
    call_count = 0
    async def failing_function():
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise Exception(f"Failure #{call_count}")
        return f"Success on attempt {call_count}"
    
    retry_config = RetryConfig(
        max_attempts=5,
        initial_delay=0.5,
        backoff=1.5,
        rate_limit_broker="test_broker",
        rate_limit_tokens=1
    )
    
    start_time = time.time()
    result = await async_retry_with_rate_limit(failing_function, config=retry_config)
    elapsed = time.time() - start_time
    
    logger.info(f"Result: {result}")
    logger.info(f"Completed in {elapsed:.2f}s with {call_count} attempts")

async def test_concurrent_broker_calls():
    """Test concurrent calls to different brokers."""
    logger.info("=== Testing Concurrent Broker Calls ===")
    
    rate_limiter = await get_rate_limiter()
    
    # Configure different brokers with different limits
    rate_limiter.configure_broker("fyers", RateConfig(rps=5, burst=5))
    rate_limiter.configure_broker("angel", RateConfig(rps=3, burst=3))
    rate_limiter.configure_broker("zerodha", RateConfig(rps=2, burst=2))
    
    # Create mock brokers
    brokers = {
        "fyers": MockBroker("fyers"),
        "angel": MockBroker("angel"), 
        "zerodha": MockBroker("zerodha")
    }
    
    # Simulate concurrent operations
    async def make_broker_calls(broker_name: str, broker: MockBroker, num_calls: int):
        tasks = []
        for i in range(num_calls):
            async def single_call():
                async with rate_limiter.acquire(broker_name):
                    return await broker.get_order_details()
            tasks.append(single_call())
        return await asyncio.gather(*tasks)
    
    start_time = time.time()
    
    # Run concurrent calls to all brokers
    results = await asyncio.gather(
        make_broker_calls("fyers", brokers["fyers"], 10),
        make_broker_calls("angel", brokers["angel"], 6),
        make_broker_calls("zerodha", brokers["zerodha"], 4)
    )
    
    elapsed = time.time() - start_time
    logger.info(f"Concurrent calls completed in {elapsed:.2f}s")
    
    # Print call counts
    for name, broker in brokers.items():
        logger.info(f"{name}: {broker.call_count} calls made")
    
    # Print final stats
    stats = rate_limiter.get_stats()
    for broker_name, broker_stats in stats.items():
        logger.info(f"{broker_name} stats: {broker_stats}")

async def test_data_provider_simulation():
    """Test data provider style operations."""
    logger.info("=== Testing Data Provider Simulation ===")
    
    rate_limiter = await get_rate_limiter()
    rate_limiter.configure_broker("fyers", RateConfig(rps=10, burst=12))
    
    broker = MockBroker("fyers")
    
    # Simulate option chain and history calls
    async def get_option_chain(symbol: str):
        retry_config = RetryConfig(
            max_attempts=3,
            initial_delay=1.0,
            rate_limit_broker="fyers",
            rate_limit_tokens=1
        )
        
        async def _fetch():
            return await broker.get_order_details()  # Using this as mock data fetch
        
        return await async_retry_with_rate_limit(_fetch, config=retry_config)
    
    # Make multiple data requests
    symbols = ["NIFTY", "BANKNIFTY", "RELIANCE", "TCS", "HDFC"]
    
    start_time = time.time()
    results = await asyncio.gather(*[get_option_chain(symbol) for symbol in symbols])
    elapsed = time.time() - start_time
    
    logger.info(f"Data provider calls completed in {elapsed:.2f}s")
    logger.info(f"Results count: {len(results)}")

async def test_broker_manager_simulation():
    """Test broker manager style operations."""
    logger.info("=== Testing Broker Manager Simulation ===")
    
    rate_limiter = await get_rate_limiter()
    
    # Configure with trading limits (more conservative)
    rate_limiter.configure_broker("fyers", RateConfig(rps=8, burst=9))
    rate_limiter.configure_broker("angel", RateConfig(rps=4, burst=5))
    
    brokers = {
        "fyers": MockBroker("fyers", failure_rate=0.1),  # 10% failure rate
        "angel": MockBroker("angel", failure_rate=0.2)   # 20% failure rate
    }
    
    # Simulate broker manager operations
    async def broker_operation(broker_name: str, broker: MockBroker, operation: str):
        retry_config = RetryConfig(
            max_attempts=3,
            initial_delay=1.0,
            backoff=2.0,
            rate_limit_broker=broker_name,
            rate_limit_tokens=1,
            exceptions=(Exception,)  # Retry all exceptions for testing
        )
        
        async def _operation():
            if operation == "place_order":
                return await broker.place_order({"symbol": "NIFTY", "side": "BUY"})
            elif operation == "get_positions":
                return await broker.get_positions()
            else:
                return await broker.get_order_details()
        
        try:
            return await async_retry_with_rate_limit(_operation, config=retry_config)
        except Exception as e:
            logger.error(f"Operation {operation} failed for {broker_name}: {e}")
            return None
    
    # Simulate concurrent broker manager operations
    operations = []
    for broker_name, broker in brokers.items():
        for op in ["place_order", "get_positions", "get_order_details"]:
            for i in range(3):  # 3 of each operation per broker
                operations.append(broker_operation(broker_name, broker, op))
    
    start_time = time.time()
    results = await asyncio.gather(*operations, return_exceptions=True)
    elapsed = time.time() - start_time
    
    successful = sum(1 for r in results if r is not None and not isinstance(r, Exception))
    logger.info(f"Broker manager operations: {successful}/{len(results)} successful in {elapsed:.2f}s")
    
    # Print broker call counts
    for name, broker in brokers.items():
        logger.info(f"{name}: {broker.call_count} total calls made")

async def main():
    """Run all tests."""
    logger.info("Starting Rate Limiting Tests")
    
    try:
        await test_rate_limiter_basic()
        await asyncio.sleep(1)  # Brief pause between tests
        
        await test_retry_with_rate_limiting()
        await asyncio.sleep(1)
        
        await test_concurrent_broker_calls()
        await asyncio.sleep(1)
        
        await test_data_provider_simulation()
        await asyncio.sleep(1)
        
        await test_broker_manager_simulation()
        
        logger.info("All tests completed successfully!")
        
    except Exception as e:
        logger.error(f"Test failed: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())
