# algosat/main.py

import asyncio
from core.db import init_db, engine
from core.db import seed_default_strategies_and_configs
from core.dbschema import strategies, strategy_configs, broker_credentials
from core.strategy_manager import run_poll_loop
from brokers.factory import get_broker
from brokers.broker_auth import auth_all_enabled_brokers
from common.broker_utils import get_broker_credentials, upsert_broker_credentials
from common.logger import get_logger
from common.default_broker_configs import DEFAULT_BROKER_CONFIGS # Import the default configs
from common.default_strategy_configs import DEFAULT_STRATEGY_CONFIGS
from sqlalchemy import select
from datetime import datetime
# from core.data_manager import CacheManager
from core.data_provider.provider import DataProvider

logger = get_logger(__name__)

BROKERS_TO_SETUP = ["zerodha"]  # Define which brokers to initialize

async def initialize_brokers():
    """
    Initialize broker configurations in the database.
    This ensures the broker_credentials table exists and all brokers have
    a configuration entry with their required fields.
    
    Returns:
        bool: True if initialization was successful
    """
    logger.debug("Initializing broker configurations...")
    # Initialize each broker configuration
    for broker_key in BROKERS_TO_SETUP:
        logger.debug(f"Setting up broker configuration: {broker_key}")
        full_config = await get_broker_credentials(broker_key)
        needs_initial_save = False

        # If no configuration exists, use default
        if not full_config:
            logger.info(f"No configuration found for {broker_key}. Initializing with default settings.")
            full_config = DEFAULT_BROKER_CONFIGS.get(broker_key)
            if not full_config:
                logger.error(f"No default configuration available for broker: {broker_key}. Skipping.")
                continue
                
            # Ensure 'credentials' exists
            if "credentials" not in full_config:
                full_config["credentials"] = {}
                
            needs_initial_save = True
            
        # Ensure all required fields exist
        if "credentials" not in full_config:
            full_config["credentials"] = {}
        if "required_auth_fields" not in full_config:
            full_config["required_auth_fields"] = []
            
        # If a save is needed, save the config
        if needs_initial_save:
            logger.debug(f"Saving initial configuration for {broker_key}")
            await upsert_broker_credentials(broker_key, full_config)
            
    logger.info("Broker configurations initialized")
    return True

async def prompt_for_missing_credentials():
    """
    Prompt the user for any missing required credentials for all brokers.
    Updates the database with the new credentials.
    
    Returns:
        dict: A dictionary of broker names and whether their credentials were updated
    """
    results = {}
    
    for broker_key in BROKERS_TO_SETUP:
        logger.debug(f"Checking credentials for broker: {broker_key}")
        full_config = await get_broker_credentials(broker_key)
        
        if not full_config:
            logger.warning(f"No configuration found for {broker_key}. Skipping credential check.")
            results[broker_key] = False
            continue
            
        # Get current credentials and required fields
        current_credentials = full_config.get("credentials", {})
        required_fields = full_config.get("required_auth_fields", [])
        
        if not required_fields:
            logger.warning(f"No required authentication fields defined for {broker_key}. Skipping.")
            results[broker_key] = False
            continue
            
        # Check for missing credentials
        credentials_updated = False
        for field in required_fields:
            if not current_credentials.get(field):
                # Prompt the user for the missing credential
                value = input(f"Enter {field} for broker {broker_key}: ")
                if value:
                    current_credentials[field] = value
                    credentials_updated = True
                    
        # If credentials were updated, save them back to the database
        if credentials_updated:
            full_config["credentials"] = current_credentials
            await upsert_broker_credentials(broker_key, full_config)
            logger.info(f"Credentials updated for {broker_key}")
            results[broker_key] = True
        else:
            logger.debug(f"No credential updates needed for {broker_key}")
            results[broker_key] = False
            
    return results


if __name__ == "__main__":
    import asyncio

    async def main():
        # 1) Ensure database schema exists
        logger.info("🔄 Initializing database schema…")
        await init_db()

        # 2) Seed default strategies and configs
        logger.debug("Seeding default strategies and configs...")
        await seed_default_strategies_and_configs()

        # 3) Initialize broker configurations
        await initialize_brokers()

        # 4) Prompt for any missing credentials
        await prompt_for_missing_credentials()

        # 5) Authenticate all enabled brokers
        logger.info("Authenticating enabled brokers...")
        auth_results = await auth_all_enabled_brokers()
        for broker_name, (success, message, broker) in auth_results.items():
            if success:
                logger.info(f"Authentication successful for {broker_name}: {message}")
                # Use the already-authenticated instance:
                profile = await broker.get_profile()
                logger.info(f"Profile for {broker_name}: {profile}")
                positions = await broker.get_positions()
                logger.info(f"Positions for {broker_name}: {positions}")
            else:
                logger.warning(f"Authentication failed for {broker_name}: {message}")

        # 6) Start the strategy polling loop
        logger.info("🚀 All brokers processed. Entering poll loop...")
        await run_poll_loop()

    asyncio.run(main())