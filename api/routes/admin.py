from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, Any

from algosat.core.db import reset_database_tables
from algosat.api.dependencies import get_db
from algosat.api.auth_dependencies import get_current_user
from algosat.common.logger import get_logger

logger = get_logger("api.admin")

# Require authentication for all endpoints in this router
router = APIRouter(dependencies=[Depends(get_current_user)])

@router.post("/resetdb", response_model=Dict[str, Any])
async def reset_database(
    db=Depends(get_db),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Reset the database by clearing entries from orders and broker_executions tables.
    
    This endpoint:
    - Deletes all records from broker_executions table
    - Deletes all records from orders table
    - Maintains proper deletion sequence to handle foreign key dependencies
    
    Returns:
        dict: Summary of deleted records including counts
    """
    try:
        # Check if user has admin role (optional - you can remove this if not needed)
        # if current_user.get('role') != 'admin':
        #     raise HTTPException(status_code=403, detail="Admin access required")
        
        logger.info(f"Database reset initiated by user: {current_user.get('username', 'unknown')}")
        
        # Perform the database reset
        result = await reset_database_tables(db)
        
        logger.info(f"Database reset completed. Summary: {result}")
        
        return {
            "status": "success",
            "message": "Database reset completed successfully",
            "summary": result
        }
        
    except Exception as e:
        logger.error(f"Database reset failed: {e}")
        raise HTTPException(
            status_code=500, 
            detail=f"Database reset failed: {str(e)}"
        )
