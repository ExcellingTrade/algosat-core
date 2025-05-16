"""
This script fixes the broker credentials in the database.
It ensures that the credentials are stored properly according to the required fields.
"""
import asyncio
import sys
import os

# Add the parent directory to the Python path to allow importing modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select, text
from core.db import AsyncSessionLocal, create_table_ddl
from core.dbschema import broker_credentials
from common.default_broker_configs import DEFAULT_BROKER_CONFIGS
from common.logger import get_logger
from common.broker_utils import get_broker_credentials, upsert_broker_credentials

logger = get_logger("fix_broker_credentials")

async def fix_credentials():
    """
    Fix the broker credentials in the database.
    1. Ensure table exists
    2. Check if credentials have nested 'credentials' field
    3. Fix the structure if needed
    """
    logger.info("Starting broker credentials fix")
    
    # Ensure the broker_credentials table exists
    await create_table_ddl(broker_credentials)
    
    # Get all broker names from the registry
    broker_names = list(DEFAULT_BROKER_CONFIGS.keys())
    logger.info(f"Processing {len(broker_names)} broker(s): {', '.join(broker_names)}")
    
    async with AsyncSessionLocal() as session:
        # First, get all existing broker entries
        stmt = select(broker_credentials)
        result = await session.execute(stmt)
        existing_brokers = [row._mapping for row in result.all()]
        
        for broker in existing_brokers:
            broker_name = broker["broker_name"]
            creds = broker["credentials"]
            
            logger.info(f"Checking broker: {broker_name}")
            
            # Check if we have nested credentials
            if "credentials" in creds:
                logger.warning(f"Found nested credentials for {broker_name}, fixing...")
                
                # Extract the nested credentials
                nested_creds = creds.pop("credentials", {})
                
                # Create a new clean config
                default_config = DEFAULT_BROKER_CONFIGS.get(broker_name, {}).copy()
                
                # Update the default config with the values from the database
                for key, value in broker.items():
                    if key != "credentials":
                        default_config[key] = value
                
                # Place the credentials directly in the credentials field
                default_config["credentials"] = nested_creds
                
                # Save back to the database
                await upsert_broker_credentials(broker_name, default_config)
                logger.info(f"Fixed broker {broker_name}")
            else:
                logger.info(f"Broker {broker_name} credentials structure looks good")
    
    logger.info("Broker credentials fix completed")

if __name__ == "__main__":
    asyncio.run(fix_credentials())
