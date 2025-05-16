"""
broker_auth.py

This module provides centralized authentication functionality for all supported brokers.
It handles the daily authentication process and token refreshing for each broker.

Features:
- Automatic broker detection and authentication
- Token validation and refresh
- Credential storage and retrieval
- Scheduled re-authentication for brokers that require daily login

Usage:
- Import auth_all_enabled_brokers() to authenticate all enabled brokers
- Import auth_broker(broker_name) to authenticate a specific broker
"""

import asyncio
from typing import Dict, List, Optional, Any, Tuple

from common.logger import get_logger
from common.broker_utils import get_broker_credentials, upsert_broker_credentials
from brokers.factory import get_broker, BROKER_REGISTRY

logger = get_logger("broker_auth")

async def auth_broker(broker_name: str) -> Tuple[bool, str, Optional[Any]]:
    """
    Authenticate a specific broker by name.
    
    Args:
        broker_name: The name of the broker to authenticate (e.g., 'fyers', 'angel')
        
    Returns:
        Tuple of (success: bool, message: str, broker_instance: Optional[Any])
    """
    try:
        # Get broker config from database
        broker_config = await get_broker_credentials(broker_name)
        
        if not broker_config:
            return False, f"No configuration found for broker: {broker_name}", None
            
        # Skip if broker is not enabled
        if not broker_config.get("is_enabled", False):
            logger.info(f"Broker {broker_name} is not enabled. Skipping authentication.")
            return False, f"Broker {broker_name} is not enabled", None
        
        # Get the broker instance
        broker_instance = get_broker(broker_name)
        if not broker_instance:
            return False, f"Failed to initialize broker instance for {broker_name}", None
        
        # Perform login
        logger.info(f"Authenticating broker: {broker_name}")
        login_successful = await broker_instance.login()
        
        if login_successful:
            logger.info(f"Authentication successful for broker: {broker_name}")
            # Store the successful broker instance for future use
            return True, f"Successfully authenticated {broker_name}", broker_instance
        else:
            logger.error(f"Authentication failed for broker: {broker_name}")
            return False, f"Authentication failed for {broker_name}", None
            
    except Exception as e:
        logger.error(f"Error during authentication of broker {broker_name}: {e}", exc_info=True)
        return False, f"Error during authentication: {str(e)}", None

async def auth_all_enabled_brokers() -> Dict[str, Tuple[bool, str, Optional[Any]]]:
    """
    Authenticate all brokers that are enabled in the database.
    
    Returns:
        Dictionary mapping broker names to tuples of (success: bool, message: str, broker_instance: Optional[Any])
    """
    results = {}
    enabled_brokers = []
    
    # Get all available broker names from the registry
    broker_names = list(BROKER_REGISTRY.keys())
    logger.info(f"Found {len(broker_names)} broker(s) in registry: {', '.join(broker_names)}")
    
    # First, identify which brokers are enabled
    for broker_name in broker_names:
        broker_config = await get_broker_credentials(broker_name)
        if broker_config and broker_config.get("is_enabled", False):
            enabled_brokers.append(broker_name)
    
    logger.info(f"Found {len(enabled_brokers)} enabled broker(s): {', '.join(enabled_brokers) if enabled_brokers else 'None'}")
    
    # Authenticate only enabled brokers
    for broker_name in enabled_brokers:
        success, message, broker = await auth_broker(broker_name)
        results[broker_name] = (success, message, broker)
    
    # Summarize results
    successful = [name for name, (success, _, _) in results.items() if success]
    failed = [name for name, (success, _, _) in results.items() if not success]
    
    if successful:
        logger.info(f"Successfully authenticated brokers: {', '.join(successful)}")
    if failed:
        logger.warning(f"Failed to authenticate brokers: {', '.join(failed)}")
        
    return results

# For testing
if __name__ == "__main__":
    async def test():
        # Test auth_all_enabled_brokers
        results = await auth_all_enabled_brokers()
        print("Authentication results:", results)
        
    asyncio.run(test())
