from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional
from pydantic import ValidationError

from algosat.core.db import (
    get_all_smart_levels,
    get_smart_level_by_id,
    create_smart_level,
    update_smart_level,
    delete_smart_level,
    get_strategy_symbol_by_id,  # To validate strategy_symbol_id exists
)
from algosat.api.schemas import (
    SmartLevelCreate,
    SmartLevelUpdate,
    SmartLevelResponse,
)
from algosat.api.dependencies import get_db
from algosat.api.auth_dependencies import get_current_user
from algosat.core.security import EnhancedInputValidator, InvalidInputError
from algosat.common.logger import get_logger

logger = get_logger("api.smart_levels")

# Require authentication for all endpoints in this router
router = APIRouter(dependencies=[Depends(get_current_user)])
input_validator = EnhancedInputValidator()

def validate_smart_level_targets(entry_level: float, bullish_target: Optional[float], bearish_target: Optional[float]):
    """Validate that targets are on the correct side of entry level."""
    if bullish_target is not None and bullish_target <= entry_level:
        raise HTTPException(
            status_code=400, 
            detail=f"Bullish target ({bullish_target}) must be above entry level ({entry_level})"
        )
    
    if bearish_target is not None and bearish_target >= entry_level:
        raise HTTPException(
            status_code=400, 
            detail=f"Bearish target ({bearish_target}) must be below entry level ({entry_level})"
        )

@router.get("/", response_model=List[SmartLevelResponse])
async def list_smart_levels(
    strategy_symbol_id: Optional[int] = Query(None, description="Filter by strategy symbol ID"),
    db=Depends(get_db)
):
    """Get all smart levels, optionally filtered by strategy_symbol_id."""
    try:
        if strategy_symbol_id is not None:
            validated_strategy_symbol_id = input_validator.validate_integer(
                strategy_symbol_id, "strategy_symbol_id", min_value=1
            )
        else:
            validated_strategy_symbol_id = None
            
        smart_levels = await get_all_smart_levels(db, validated_strategy_symbol_id)
        return [SmartLevelResponse(**smart_level) for smart_level in smart_levels]
    except Exception as e:
        logger.error(f"Error in list_smart_levels: {e}")
        raise

@router.get("/{smart_level_id}", response_model=SmartLevelResponse)
async def get_smart_level(smart_level_id: int, db=Depends(get_db)):
    """Get a specific smart level by ID."""
    try:
        validated_smart_level_id = input_validator.validate_integer(
            smart_level_id, "smart_level_id", min_value=1
        )
        
        smart_level = await get_smart_level_by_id(db, validated_smart_level_id)
        if not smart_level:
            raise HTTPException(status_code=404, detail="Smart level not found")
            
        return SmartLevelResponse(**smart_level)
    except Exception as e:
        logger.error(f"Error in get_smart_level: {e}")
        raise

@router.post("/", response_model=SmartLevelResponse)
async def create_smart_level_endpoint(smart_level: SmartLevelCreate, db=Depends(get_db)):
    """Create a new smart level."""
    try:
        # Validate that strategy_symbol_id exists
        strategy_symbol = await get_strategy_symbol_by_id(db, smart_level.strategy_symbol_id)
        if not strategy_symbol:
            raise HTTPException(
                status_code=404, 
                detail=f"Strategy symbol with ID {smart_level.strategy_symbol_id} not found"
            )
        
        # Validate targets against entry level
        validate_smart_level_targets(
            smart_level.entry_level, 
            smart_level.bullish_target, 
            smart_level.bearish_target
        )
        
        # Convert to dict for database insertion
        smart_level_data = smart_level.model_dump()
        
        created_smart_level = await create_smart_level(db, smart_level_data)
        logger.info(f"Smart level created successfully with ID: {created_smart_level['id']}")
        
        return SmartLevelResponse(**created_smart_level)
    except ValidationError as e:
        logger.error(f"Validation error in create_smart_level: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error in create_smart_level: {e}")
        raise

@router.put("/{smart_level_id}", response_model=SmartLevelResponse)
async def update_smart_level_endpoint(
    smart_level_id: int, 
    smart_level_update: SmartLevelUpdate, 
    db=Depends(get_db)
):
    """Update an existing smart level."""
    try:
        validated_smart_level_id = input_validator.validate_integer(
            smart_level_id, "smart_level_id", min_value=1
        )
        
        # Check if smart level exists
        existing_smart_level = await get_smart_level_by_id(db, validated_smart_level_id)
        if not existing_smart_level:
            raise HTTPException(status_code=404, detail="Smart level not found")
        
        # Prepare update data - only include fields that are provided
        update_data = smart_level_update.model_dump(exclude_unset=True)
        
        # If no fields to update, return existing smart level
        if not update_data:
            return SmartLevelResponse(**existing_smart_level)
        
        # Validate targets if entry_level is being updated or targets are being set
        entry_level = update_data.get('entry_level', existing_smart_level['entry_level'])
        bullish_target = update_data.get('bullish_target', existing_smart_level['bullish_target'])
        bearish_target = update_data.get('bearish_target', existing_smart_level['bearish_target'])
        
        validate_smart_level_targets(entry_level, bullish_target, bearish_target)
        
        # Update the smart level
        updated_smart_level = await update_smart_level(db, validated_smart_level_id, update_data)
        if not updated_smart_level:
            raise HTTPException(status_code=404, detail="Smart level not found")
            
        logger.info(f"Smart level {validated_smart_level_id} updated successfully")
        return SmartLevelResponse(**updated_smart_level)
        
    except ValidationError as e:
        logger.error(f"Validation error in update_smart_level: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error in update_smart_level: {e}")
        raise

@router.delete("/{smart_level_id}")
async def delete_smart_level_endpoint(smart_level_id: int, db=Depends(get_db)):
    """Delete a smart level."""
    try:
        validated_smart_level_id = input_validator.validate_integer(
            smart_level_id, "smart_level_id", min_value=1
        )
        
        success = await delete_smart_level(db, validated_smart_level_id)
        if not success:
            raise HTTPException(status_code=404, detail="Smart level not found")
            
        logger.info(f"Smart level {validated_smart_level_id} deleted successfully")
        return {"message": "Smart level deleted successfully", "id": validated_smart_level_id}
        
    except Exception as e:
        logger.error(f"Error in delete_smart_level: {e}")
        raise
