"""
This script checks the current broker credentials structure in the database.
It prints out the current structure for inspection.
"""
import asyncio
import sys
import os
import json

# Add the parent directory to the Python path to allow importing modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select
from core.db import AsyncSessionLocal
from core.dbschema import broker_credentials
from common.logger import get_logger

logger = get_logger("check_broker_credentials")

async def check_credentials():
    """
    Check the current broker credentials structure in the database.
    Prints the structure of each broker's credentials.
    """
    logger.info("Checking broker credentials structure")
    
    async with AsyncSessionLocal() as session:
        # Get all broker entries
        stmt = select(broker_credentials)
        result = await session.execute(stmt)
        brokers = [row._mapping for row in result.all()]
        
        if not brokers:
            logger.info("No brokers found in the database")
            return
        
        for broker in brokers:
            broker_name = broker["broker_name"]
            logger.info(f"\n{'='*50}\nBroker: {broker_name}")
            
            # Print all fields except credentials
            for key, value in broker.items():
                if key != "credentials":
                    logger.info(f"{key}: {value}")
            
            # Print credentials structure without actual values
            creds = broker["credentials"]
            logger.info("\nCredentials structure:")
            
            if "credentials" in creds:
                logger.warning("WARNING: Nested 'credentials' field detected!")
                logger.info("Top level credentials keys:")
                for key in creds.keys():
                    logger.info(f"- {key}")
                
                logger.info("\nNested credentials keys:")
                nested_creds = creds.get("credentials", {})
                for key in nested_creds.keys():
                    logger.info(f"- {key}")
            else:
                logger.info("Credentials keys:")
                for key in creds.keys():
                    logger.info(f"- {key}")
            
            logger.info(f"{'='*50}\n")
    
    logger.info("Credential check completed")

if __name__ == "__main__":
    asyncio.run(check_credentials())
