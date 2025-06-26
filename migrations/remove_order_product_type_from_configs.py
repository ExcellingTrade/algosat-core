"""
Migration: Remove order_type and product_type from strategy_configs table

These fields should only exist at the strategy level, not at the config level.
"""

import asyncio
from sqlalchemy import text
from algosat.core.db import engine
from algosat.common.logger import get_logger

logger = get_logger("migration.remove_order_product_type")

async def migrate_remove_order_product_type():
    """
    Remove order_type and product_type columns from strategy_configs table.
    These fields will only exist at the strategy level.
    """
    try:
        async with engine.begin() as conn:
            logger.info("Starting migration to remove order_type and product_type from strategy_configs")
            
            # Check if columns exist before dropping them
            check_order_type = """
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name='strategy_configs' AND column_name='order_type'
            """
            
            check_product_type = """
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name='strategy_configs' AND column_name='product_type'
            """
            
            order_type_exists = await conn.execute(text(check_order_type))
            product_type_exists = await conn.execute(text(check_product_type))
            
            if order_type_exists.first():
                logger.info("Dropping order_type column from strategy_configs")
                await conn.execute(text("ALTER TABLE strategy_configs DROP COLUMN order_type"))
            else:
                logger.info("order_type column already removed from strategy_configs")
            
            if product_type_exists.first():
                logger.info("Dropping product_type column from strategy_configs")
                await conn.execute(text("ALTER TABLE strategy_configs DROP COLUMN product_type"))
            else:
                logger.info("product_type column already removed from strategy_configs")
            
            logger.info("Migration completed successfully")
            
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(migrate_remove_order_product_type())
