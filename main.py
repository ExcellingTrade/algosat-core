# algosat/main.py

import asyncio
from core.db import create_table_ddl
from core.dbschema import strategies, strategy_configs, trade_logs, broker_credentials
from core.strategy_manager import run_poll_loop
from brokers.factory import get_broker
from brokers.broker_auth import auth_broker, auth_all_enabled_brokers, validate_broker_credentials
from common.broker_utils import get_broker_credentials, upsert_broker_credentials
from common.logger import get_logger
from common.default_broker_configs import DEFAULT_BROKER_CONFIGS # Import the default configs

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
    logger.info("Initializing broker configurations...")
    
    # Ensure broker_credentials table exists
    await create_table_ddl(broker_credentials)
    
    # Initialize each broker configuration
    for broker_key in BROKERS_TO_SETUP:
        logger.info(f"Setting up broker configuration: {broker_key}")
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
            logger.info(f"Saving initial configuration for {broker_key}")
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
        logger.info(f"Checking credentials for broker: {broker_key}")
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
            logger.info(f"No credential updates needed for {broker_key}")
            results[broker_key] = False
            
    return results

async def _start():
    """
    Main entry point for the application.
    """
    # 1) Ensure all necessary tables exist
    logger.info("🔄 Creating tables if they don't exist…")
    await create_table_ddl(strategies)
    await create_table_ddl(strategy_configs)
    await create_table_ddl(trade_logs)
    
    # 2) Initialize broker configurations
    await initialize_brokers()
    
    # 3) Prompt for any missing credentials
    await prompt_for_missing_credentials()
    
    # 4) Authenticate all enabled brokers
    logger.info("Authenticating enabled brokers...")
    auth_results = await auth_all_enabled_brokers()
    
    if not auth_results:
        logger.info("No enabled brokers found. Skipping broker authentication.")
    else:
        for broker_name, (success, message) in auth_results.items():
            if success:
                logger.info(f"Authentication successful for {broker_name}: {message}")
                
                # Get the broker instance to demonstrate profile retrieval
                broker = get_broker(broker_name)
                profile = await broker.get_profile()
                logger.info(f"Profile for {broker_name}: {profile}")
                 
                # Show positions for the broker
                positions = await broker.get_positions()
                logger.info(f"Positions for {broker_name}: {positions}")
                print("*"*50)   
            else:
                logger.warning(f"Authentication failed for {broker_name}: {message}")
    
    # 5) Start the strategy polling loop
    logger.info("🚀 All brokers processed. Entering poll loop...")
    # quit()
    # await run_poll_loop()

if __name__ == "__main__":
    asyncio.run(_start())