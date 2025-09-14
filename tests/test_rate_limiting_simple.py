#!/usr/bin/env python3
"""
Simple test script for rate limiting with proper module imports.
Run with: python -m pytest test_rate_limiting_simple.py -v
or: python test_rate_limiting_simple.py
"""

import sys
import os
import asyncio
import time

# Add current directory to path so we can import algosat modules
sys.path.insert(0, os.path.dirname(__file__))

def test_imports():
    """Test that all modules can be imported correctly."""
    print("Testing imports...")
    
    try:
        from algosat.core.rate_limiter import get_rate_limiter, RateConfig
        print("✓ Rate limiter imported successfully")
    except ImportError as e:
        print(f"✗ Rate limiter import failed: {e}")
        return False
    
    try:
        from algosat.core.async_retry import get_retry_config, RetryConfig
        print("✓ Async retry imported successfully")
    except ImportError as e:
        print(f"✗ Async retry import failed: {e}")
        return False
    
    return True

async def test_rate_limiter_basic():
    """Test basic rate limiter functionality."""
    print("\n=== Testing Basic Rate Limiter ===")
    
    try:
        from algosat.core.rate_limiter import get_rate_limiter, RateConfig
        
        # Get rate limiter instance
        rate_limiter = await get_rate_limiter()
        print("✓ Rate limiter instance created")
        
        # Configure test broker
        config = RateConfig(rps=3, burst=3)
        rate_limiter.configure_broker("test_broker", config)
        print("✓ Test broker configured with 3 rps")
        
        # Test rate limiting with timing
        print("Testing rate limiting (should take ~1 second for 3 calls at 3 rps)...")
        start_time = time.time()
        
        for i in range(3):
            async with rate_limiter.acquire("test_broker"):
                elapsed = time.time() - start_time
                print(f"  Call {i+1} completed at {elapsed:.2f}s")
        
        total_elapsed = time.time() - start_time
        print(f"✓ All calls completed in {total_elapsed:.2f}s")
        
        # Get and display stats
        stats = rate_limiter.get_stats()
        if "test_broker" in stats:
            broker_stats = stats["test_broker"]
            print(f"✓ Stats - Calls: {broker_stats['call_count']}, Tokens: {broker_stats['current_tokens']:.1f}")
        
        return True
        
    except Exception as e:
        print(f"✗ Rate limiter test failed: {e}")
        return False

async def test_retry_functionality():
    """Test retry functionality."""
    print("\n=== Testing Retry Functionality ===")
    
    try:
        from algosat.core.async_retry import async_retry_with_rate_limit, RetryConfig
        
        # Create a function that fails twice then succeeds
        attempt_count = 0
        async def test_function():
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count <= 2:
                raise ValueError(f"Simulated failure #{attempt_count}")
            return f"Success on attempt {attempt_count}"
        
        # Configure retry
        retry_config = RetryConfig(
            max_attempts=5,
            initial_delay=0.1,  # Short delay for testing
            backoff=1.5
        )
        
        print("Testing retry mechanism (function fails twice then succeeds)...")
        start_time = time.time()
        
        result = await async_retry_with_rate_limit(test_function, config=retry_config)
        
        elapsed = time.time() - start_time
        print(f"✓ Retry successful: {result}")
        print(f"✓ Completed in {elapsed:.2f}s after {attempt_count} attempts")
        
        return True
        
    except Exception as e:
        print(f"✗ Retry test failed: {e}")
        return False

async def test_rate_limit_with_retry():
    """Test combined rate limiting and retry functionality."""
    print("\n=== Testing Rate Limiting with Retry ===")
    
    try:
        from algosat.core.rate_limiter import get_rate_limiter, RateConfig
        from algosat.core.async_retry import async_retry_with_rate_limit, RetryConfig
        
        # Get rate limiter and configure broker
        rate_limiter = await get_rate_limiter()
        rate_limiter.configure_broker("retry_test_broker", RateConfig(rps=5, burst=5))
        
        # Create a function that uses rate limiting
        call_count = 0
        async def rate_limited_function():
            nonlocal call_count
            call_count += 1
            async with rate_limiter.acquire("retry_test_broker"):
                if call_count == 1:
                    raise ConnectionError("Simulated connection error")
                return f"Success on call {call_count}"
        
        # Configure retry with rate limiting
        retry_config = RetryConfig(
            max_attempts=3,
            initial_delay=0.1,
            rate_limit_broker="retry_test_broker",
            rate_limit_tokens=1
        )
        
        print("Testing combined rate limiting and retry...")
        start_time = time.time()
        
        result = await async_retry_with_rate_limit(rate_limited_function, config=retry_config)
        
        elapsed = time.time() - start_time
        print(f"✓ Combined test successful: {result}")
        print(f"✓ Completed in {elapsed:.2f}s with {call_count} calls")
        
        return True
        
    except Exception as e:
        print(f"✗ Combined test failed: {e}")
        return False

async def main():
    """Run all tests."""
    print("Starting Rate Limiting Implementation Tests")
    print("=" * 50)
    
    # Test imports first
    if not test_imports():
        print("\n✗ Import tests failed, stopping")
        return False
    
    # Run async tests
    tests = [
        test_rate_limiter_basic,
        test_retry_functionality,
        test_rate_limit_with_retry
    ]
    
    results = []
    for test in tests:
        try:
            result = await test()
            results.append(result)
        except Exception as e:
            print(f"✗ Test {test.__name__} failed with exception: {e}")
            results.append(False)
    
    # Summary
    print("\n" + "=" * 50)
    passed = sum(results)
    total = len(results)
    print(f"Test Summary: {passed}/{total} tests passed")
    
    if passed == total:
        print("✓ All tests passed! Rate limiting implementation is working correctly.")
        return True
    else:
        print("✗ Some tests failed. Please check the implementation.")
        return False

if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
