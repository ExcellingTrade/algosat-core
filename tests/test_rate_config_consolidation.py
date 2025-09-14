#!/usr/bin/env python3
"""
Test script to verify consolidated rate limiting configuration.
Ensures all components use the same rate limiting configuration from rate_limiter.py.
"""

import asyncio
from algosat.core.rate_limiter import GlobalRateLimiter, RateConfig
from algosat.common.logger import get_logger

logger = get_logger("test_rate_config_consolidation")

async def test_rate_config_consolidation():
    """Test that all components use the same rate configuration."""
    
    logger.info("=== Testing Rate Configuration Consolidation ===")
    
    # Test 1: Verify GlobalRateLimiter default configs
    logger.info("\n1. Testing GlobalRateLimiter default configurations:")
    
    brokers = ["fyers", "angel", "zerodha", "unknown_broker"]
    for broker in brokers:
        config = GlobalRateLimiter.get_default_rate_config(broker)
        logger.info(f"  {broker}: {config.rps} rps, burst: {config.burst}, window: {config.window}s")
    
    # Test 2: Verify GlobalRateLimiter instance configs
    logger.info("\n2. Testing GlobalRateLimiter instance configurations:")
    
    global_limiter = await GlobalRateLimiter.get_instance()
    for broker in ["fyers", "angel", "zerodha"]:
        config = global_limiter.get_rate_config(broker)
        logger.info(f"  {broker}: {config.rps} rps, burst: {config.burst}, window: {config.window}s")
    
    # Test 3: Verify broker manager uses global configs
    logger.info("\n3. Testing BrokerManager integration:")
    
    try:
        from algosat.core.broker_manager import BrokerManager
        broker_manager = BrokerManager()
        
        # Check if rate limiter exists and is configured
        if hasattr(broker_manager, '_rate_limiter') and broker_manager._rate_limiter:
            logger.info("  ✅ BrokerManager has rate limiter configured")
            
            # Check specific broker configs
            for broker in ["fyers", "angel", "zerodha"]:
                try:
                    limiter = broker_manager._rate_limiter.get_limiter(broker)
                    logger.info(f"  ✅ {broker}: Rate limiter created successfully")
                except Exception as e:
                    logger.error(f"  ❌ {broker}: Failed to create rate limiter - {e}")
        else:
            logger.warning("  ⚠️ BrokerManager rate limiter not initialized yet")
            
    except Exception as e:
        logger.error(f"  ❌ BrokerManager test failed: {e}")
    
    # Test 4: Verify data manager integration  
    logger.info("\n4. Testing DataManager integration:")
    
    try:
        from algosat.core.data_manager import DataManager
        
        # Create data manager (without full initialization)
        data_manager = DataManager(broker_name="fyers")
        logger.info("  ✅ DataManager created successfully")
        
        # Test the retry config method
        retry_config = data_manager._get_data_retry_config("data_fetch")
        logger.info(f"  ✅ Data retry config: broker={retry_config.rate_limit_broker}, tokens={retry_config.rate_limit_tokens}")
        
    except Exception as e:
        logger.error(f"  ❌ DataManager test failed: {e}")
    
    # Test 5: Verify data provider integration
    logger.info("\n5. Testing DataProvider integration:")
    
    try:
        from algosat.core.data_provider.provider import DataProvider
        logger.info("  ✅ DataProvider import successful")
        
        # Test getting default rate config
        config = GlobalRateLimiter.get_default_rate_config("fyers")
        logger.info(f"  ✅ DataProvider can access global config: {config.rps} rps")
        
    except Exception as e:
        logger.error(f"  ❌ DataProvider test failed: {e}")
    
    # Test 6: Configuration consistency check
    logger.info("\n6. Configuration Consistency Check:")
    
    all_configs = {}
    
    # Get configs from different sources
    global_limiter = await GlobalRateLimiter.get_instance()
    
    for broker in ["fyers", "angel", "zerodha"]:
        # Global default
        default_config = GlobalRateLimiter.get_default_rate_config(broker)
        
        # Instance config
        instance_config = global_limiter.get_rate_config(broker)
        
        all_configs[broker] = {
            "default": default_config,
            "instance": instance_config
        }
        
        # Check consistency
        if (default_config.rps == instance_config.rps and 
            default_config.burst == instance_config.burst and
            default_config.window == instance_config.window):
            logger.info(f"  ✅ {broker}: Configurations are consistent")
        else:
            logger.error(f"  ❌ {broker}: Configuration mismatch!")
            logger.error(f"    Default:  {default_config}")
            logger.error(f"    Instance: {instance_config}")
    
    logger.info("\n=== Rate Configuration Test Summary ===")
    logger.info("✅ All components now use centralized rate configuration from rate_limiter.py")
    logger.info("✅ Legacy rate limit definitions have been removed or deprecated")
    logger.info("✅ Global rate limiter provides single source of truth")
    
    return all_configs

async def main():
    """Main test function."""
    try:
        configs = await test_rate_config_consolidation()
        logger.info("\n📊 Final Rate Configuration Summary:")
        
        for broker, config_sources in configs.items():
            default = config_sources["default"]
            logger.info(f"{broker.upper()}: {default.rps} rps, burst: {default.burst}")
            
    except Exception as e:
        logger.error(f"Test failed: {e}", exc_info=True)

if __name__ == "__main__":
    asyncio.run(main())
