"""
Database helper functions for re-entry tracking
"""

import logging
from sqlalchemy import text
from algosat.core.db import AsyncSessionLocal

logger = logging.getLogger(__name__)

async def create_re_entry_tracking(parent_order_id: int, pullback_level: float):
    """
    Create a new re-entry tracking record for a parent order.
    
    Args:
        parent_order_id: The ID of the parent order
        pullback_level: The calculated 50% pullback level
        
    Returns:
        bool: True if record created successfully, False otherwise
    """
    try:
        async with AsyncSessionLocal() as session:
            query = """
                INSERT INTO re_entry_tracking (parent_order_id, pullback_level, pullback_touched, re_entry_attempted)
                VALUES (:parent_order_id, :pullback_level, FALSE, FALSE)
                ON CONFLICT (parent_order_id) DO NOTHING
            """
            await session.execute(text(query), {
                "parent_order_id": parent_order_id,
                "pullback_level": pullback_level
            })
            await session.commit()
            
            logger.info(f"✅ Re-entry tracking record created: parent_order_id={parent_order_id}, pullback_level={pullback_level}")
            return True
            
    except Exception as e:
        logger.error(f"❌ Error creating re-entry tracking record: {e}", exc_info=True)
        return False

# Alias for backward compatibility
create_re_entry_tracking_record = create_re_entry_tracking

async def get_re_entry_tracking(parent_order_id: int):
    """
    Get re-entry tracking record for a parent order.
    
    Args:
        parent_order_id: The ID of the parent order
        
    Returns:
        dict: Re-entry tracking record or None if not found
    """
    try:
        async with AsyncSessionLocal() as session:
            query = """
                SELECT parent_order_id, pullback_level, pullback_touched, re_entry_attempted, created_at, updated_at
                FROM re_entry_tracking 
                WHERE parent_order_id = :parent_order_id
            """
            result = await session.execute(text(query), {"parent_order_id": parent_order_id})
            record = result.fetchone()
            
            if record:
                return {
                    "parent_order_id": record.parent_order_id,
                    "pullback_level": float(record.pullback_level),
                    "pullback_touched": record.pullback_touched,
                    "re_entry_attempted": record.re_entry_attempted,
                    "created_at": record.created_at,
                    "updated_at": record.updated_at
                }
            else:
                logger.debug(f"No re-entry tracking record found for parent_order_id={parent_order_id}")
                return None
                
    except Exception as e:
        logger.error(f"❌ Error getting re-entry tracking record: {e}", exc_info=True)
        return None

# Alias for backward compatibility
get_re_entry_tracking_record = get_re_entry_tracking

async def update_pullback_touched(parent_order_id: int):
    """
    Update pullback_touched flag to True for a parent order.
    Uses atomic check to prevent race conditions.
    
    Args:
        parent_order_id: The ID of the parent order
        
    Returns:
        bool: True if updated successfully, False if already touched or error
    """
    try:
        async with AsyncSessionLocal() as session:
            query = """
                UPDATE re_entry_tracking 
                SET pullback_touched = TRUE, 
                    pullback_touched_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE parent_order_id = :parent_order_id 
                  AND pullback_touched = FALSE
            """
            result = await session.execute(text(query), {"parent_order_id": parent_order_id})
            await session.commit()
            
            if result.rowcount > 0:
                logger.info(f"✅ Pullback touched updated for parent_order_id={parent_order_id}")
                return True
            else:
                logger.warning(f"⚠️ Pullback already touched or no record found for parent_order_id={parent_order_id}")
                return False
                
    except Exception as e:
        logger.error(f"❌ Error updating pullback_touched: {e}", exc_info=True)
        return False

async def update_re_entry_attempted(parent_order_id: int, re_entry_order_id: int = None):
    """
    Update re_entry_attempted flag to True for a parent order.
    Uses atomic check to prevent race conditions and ensure one-time re-entry.
    
    Args:
        parent_order_id: The ID of the parent order
        re_entry_order_id: The ID of the re-entry order (optional)
        
    Returns:
        bool: True if updated successfully, False if already attempted or error
    """
    try:
        async with AsyncSessionLocal() as session:
            if re_entry_order_id:
                query = """
                    UPDATE re_entry_tracking 
                    SET re_entry_attempted = TRUE, 
                        re_entry_order_id = :re_entry_order_id,
                        re_entry_attempted_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE parent_order_id = :parent_order_id 
                      AND re_entry_attempted = FALSE
                """
                params = {
                    "parent_order_id": parent_order_id,
                    "re_entry_order_id": re_entry_order_id
                }
            else:
                query = """
                    UPDATE re_entry_tracking 
                    SET re_entry_attempted = TRUE, 
                        re_entry_attempted_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE parent_order_id = :parent_order_id 
                      AND re_entry_attempted = FALSE
                """
                params = {"parent_order_id": parent_order_id}
            
            result = await session.execute(text(query), params)
            await session.commit()
            
            if result.rowcount > 0:
                logger.info(f"✅ Re-entry attempted updated for parent_order_id={parent_order_id}")
                return True
            else:
                logger.warning(f"⚠️ Re-entry already attempted or no record found for parent_order_id={parent_order_id}")
                return False
                
    except Exception as e:
        logger.error(f"❌ Error updating re_entry_attempted: {e}", exc_info=True)
        return False

async def cleanup_old_re_entry_records(days_old: int = 30):
    """
    Cleanup old re-entry tracking records to prevent database bloat.
    
    Args:
        days_old: Remove records older than this many days
        
    Returns:
        int: Number of records deleted
    """
    try:
        async with AsyncSessionLocal() as session:
            query = """
                DELETE FROM re_entry_tracking 
                WHERE created_at < CURRENT_TIMESTAMP - INTERVAL '%s days'
            """ % days_old
            
            result = await session.execute(text(query))
            await session.commit()
            
            deleted_count = result.rowcount
            logger.info(f"🧹 Cleaned up {deleted_count} old re-entry tracking records (older than {days_old} days)")
            return deleted_count
            
    except Exception as e:
        logger.error(f"❌ Error cleaning up old re-entry records: {e}", exc_info=True)
        return 0
