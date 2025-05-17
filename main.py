# algosat/main.py

import asyncio
from core.db import init_db, engine
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
    logger.info("Initializing broker configurations...")
    
    
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

async def seed_strategies_and_configs():
    """
    Seed the strategies and strategy_configs tables with default strategies and configs if empty.
    """
    async with engine.begin() as conn:
        # Check if strategies table is empty
        result = await conn.execute(select(strategies))
        existing = result.first()
        if existing:
            logger.info("Strategies table already populated. Skipping seeding.")
            return
        logger.info("Seeding default strategies and configs...")
        # Insert strategies
        strategy_key_to_id = {}
        now = datetime.now()
        for key, default_cfg in DEFAULT_STRATEGY_CONFIGS.items():
            ins = strategies.insert().values(
                key=key,
                name=key,
                enabled=True,
                created_at=now,
                updated_at=now,
            )
            res = await conn.execute(ins)
            # SQLAlchemy 1.4+ returns inserted_primary_key
            strategy_id = res.inserted_primary_key[0] if hasattr(res, 'inserted_primary_key') else None
            strategy_key_to_id[key] = strategy_id
        # Insert strategy configs for OptionBuy and OptionSell only
        for key in ["OptionBuy", "OptionSell"]:
            cfg = DEFAULT_STRATEGY_CONFIGS[key]
            if not cfg:
                continue
            ins_cfg = strategy_configs.insert().values(
                strategy_id=strategy_key_to_id[key],
                symbol=cfg["symbol"],
                exchange=cfg["exchange"],
                params=cfg["params"],
                is_default=True,
                enabled=True,
                created_at=now,
                updated_at=now,
            )
            await conn.execute(ins_cfg)
        logger.info("Default strategies and configs seeded.")

if __name__ == "__main__":
    import asyncio

    async def main():
        # 1) Ensure database schema exists
        logger.info("🔄 Initializing database schema…")
        await init_db()

        # 2) Seed default strategies and configs
        await seed_strategies_and_configs()

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
        # await run_poll_loop()
        # Example: using CacheManager if you want, else just call DataProvider with no broker
        # from core.data_manager import CacheManager
        # cache = CacheManager()
        dp = DataProvider()  # Don't pass a broker—let DataProvider pick from DB config
        try:
            test_chain = await dp.get_option_chain("NSE:NIFTYBANK-INDEX", 40)
            print(test_chain['data']['optionsChain'])
            logger.info(f"Test fetch via DataProvider: retrieved {len(test_chain['data']['optionsChain'])} entries")
        except Exception as e:
            logger.error(f"DataProvider test failed: {e}", exc_info=True)

    asyncio.run(main())