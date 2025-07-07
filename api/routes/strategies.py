from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Dict, Any, List, Optional

from algosat.core.db import (
    get_all_strategies,
    get_strategy_by_id,
    update_strategy,
    enable_strategy,
    disable_strategy,
    get_strategy_configs_by_strategy_id,
    get_strategy_config_by_id,
    update_strategy_config,
    create_strategy_config,
    delete_strategy_config,
    add_strategy_symbol,
    list_strategy_symbols,
    set_strategy_symbol_status,
    get_strategy_symbol_by_id,
    update_strategy_symbol,
    delete_strategy_symbol,
    get_strategy_symbol_trade_stats,
    get_trades_for_symbol,
)
from algosat.api.schemas import (
    StrategyListResponse,
    StrategyDetailResponse,
    StrategyUpdate,
    StrategyConfigListResponse,
    StrategyConfigDetailResponse,
    StrategyConfigCreate,
    StrategyConfigUpdate,
    StrategyConfigResponse,
    StrategySymbolCreate,
    StrategySymbolResponse,
    StrategySymbolWithConfigResponse,
)
from algosat.api.dependencies import get_db
from algosat.api.auth_dependencies import get_current_user
from algosat.core.security import EnhancedInputValidator, InvalidInputError
from algosat.common.logger import get_logger

logger = get_logger("api.strategies")

# Require authentication for all endpoints in this router
router = APIRouter(dependencies=[Depends(get_current_user)])
input_validator = EnhancedInputValidator()

@router.get("/", response_model=List[StrategyListResponse])
async def list_strategies(db=Depends(get_db)):
    try:
        strategies = [StrategyListResponse(**row) for row in await get_all_strategies(db)]
        return sorted(strategies, key=lambda s: s.id)
    except Exception as e:
        logger.error(f"Error in list_strategies: {e}")
        raise

@router.get("/{strategy_id}", response_model=StrategyDetailResponse)
async def get_strategy(strategy_id: int, db=Depends(get_db)):
    try:
        validated_strategy_id = input_validator.validate_integer(strategy_id, "strategy_id", min_value=1)
        row = await get_strategy_by_id(db, validated_strategy_id)
        if not row:
            raise HTTPException(status_code=404, detail="Strategy not found")
        return StrategyDetailResponse(**row)
    except Exception as e:
        logger.error(f"Error in get_strategy: {e}")
        raise

@router.put("/{strategy_id}", response_model=StrategyDetailResponse)
async def update_strategy_endpoint(strategy_id: int, strategy_update: StrategyUpdate, db=Depends(get_db)):
    """
    Update a strategy's editable fields (name, order_type, product_type).
    """
    try:
        validated_strategy_id = input_validator.validate_integer(strategy_id, "strategy_id", min_value=1)
        
        # Check if strategy exists
        existing_strategy = await get_strategy_by_id(db, validated_strategy_id)
        if not existing_strategy:
            raise HTTPException(status_code=404, detail="Strategy not found")
        
        # Prepare update data - only include fields that are provided
        update_data = {}
        # Note: name field is not editable for strategies
        
        if strategy_update.order_type is not None:
            update_data['order_type'] = strategy_update.order_type.value
        
        if strategy_update.product_type is not None:
            update_data['product_type'] = strategy_update.product_type.value
        
        # If no fields to update, return existing strategy
        if not update_data:
            return StrategyDetailResponse(**existing_strategy)
        
        # Update the strategy
        updated_strategy = await update_strategy(db, validated_strategy_id, update_data)
        logger.info(f"Strategy {validated_strategy_id} updated successfully with data: {update_data}")
        return StrategyDetailResponse(**updated_strategy)
    
    except HTTPException:
        raise
    except InvalidInputError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating strategy {strategy_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to update strategy")

@router.put("/{strategy_id}/enable", response_model=StrategyDetailResponse)
async def enable_strategy_endpoint(strategy_id: int, db=Depends(get_db)):
    """
    Enable a strategy by setting enabled=True.
    """
    try:
        validated_strategy_id = input_validator.validate_integer(strategy_id, "strategy_id", min_value=1)
        
        # Check if strategy exists
        existing_strategy = await get_strategy_by_id(db, validated_strategy_id)
        if not existing_strategy:
            raise HTTPException(status_code=404, detail="Strategy not found")
        
        # Enable the strategy
        updated_strategy = await enable_strategy(db, validated_strategy_id)
        logger.info(f"Strategy {validated_strategy_id} enabled successfully")
        return StrategyDetailResponse(**updated_strategy)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error enabling strategy {strategy_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to enable strategy")

@router.put("/{strategy_id}/disable", response_model=StrategyDetailResponse)
async def disable_strategy_endpoint(strategy_id: int, db=Depends(get_db)):
    """
    Disable a strategy by setting enabled=False.
    """
    try:
        validated_strategy_id = input_validator.validate_integer(strategy_id, "strategy_id", min_value=1)
        
        # Check if strategy exists
        existing_strategy = await get_strategy_by_id(db, validated_strategy_id)
        if not existing_strategy:
            raise HTTPException(status_code=404, detail="Strategy not found")
        
        # Disable the strategy
        updated_strategy = await disable_strategy(db, validated_strategy_id)
        logger.info(f"Strategy {validated_strategy_id} disabled successfully")
        return StrategyDetailResponse(**updated_strategy)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error disabling strategy {strategy_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to disable strategy")

@router.get("/{strategy_id}/configs", response_model=List[StrategyConfigListResponse])
async def list_strategy_configs_for_strategy(strategy_id: int, db=Depends(get_db)):
    try:
        validated_strategy_id = input_validator.validate_integer(strategy_id, "strategy_id", min_value=1)
        configs = [StrategyConfigListResponse(**row) for row in await get_strategy_configs_by_strategy_id(db, validated_strategy_id)]
        return sorted(configs, key=lambda c: c.id)
    except Exception as e:
        logger.error(f"Error in list_strategy_configs_for_strategy: {e}")
        raise

@router.post("/{strategy_id}/configs", response_model=StrategyConfigResponse)
async def create_strategy_config_for_strategy(strategy_id: int, config: StrategyConfigCreate, db=Depends(get_db)):
    """
    Create a new strategy config for the given strategy.
    """
    try:
        validated_strategy_id = input_validator.validate_integer(strategy_id, "strategy_id", min_value=1)
        
        # Verify strategy exists
        strategy = await get_strategy_by_id(db, validated_strategy_id)
        if not strategy:
            raise HTTPException(status_code=404, detail="Strategy not found")
        
        # Create the config
        config_data = {
            'name': config.name,
            'description': config.description,
            'exchange': config.exchange,
            'instrument': config.instrument,
            'trade': config.trade,
            'indicators': config.indicators
        }
        result = await create_strategy_config(
            session=db,
            strategy_id=validated_strategy_id,
            config_data=config_data
        )
        
        return StrategyConfigResponse(**result)
    except InvalidInputError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating strategy config: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/{strategy_id}/configs/{config_id}", response_model=StrategyConfigDetailResponse)
async def get_strategy_config_detail_for_strategy(strategy_id: int, config_id: int, db=Depends(get_db)):
    """
    Get config details for a specific config belonging to a strategy.
    """
    validated_strategy_id = input_validator.validate_integer(strategy_id, "strategy_id", min_value=1)
    validated_config_id = input_validator.validate_integer(config_id, "config_id", min_value=1)
    row = await get_strategy_config_by_id(db, validated_config_id)
    if not row:
        raise HTTPException(status_code=404, detail="Strategy config not found")
    if hasattr(row, "_mapping"):
        row = dict(row._mapping)
    if row.get("strategy_id") != validated_strategy_id:
        raise HTTPException(status_code=404, detail="Config does not belong to this strategy")
    return StrategyConfigDetailResponse(**row)

@router.put("/{strategy_id}/configs/{config_id}", response_model=StrategyConfigDetailResponse)
async def update_strategy_config_for_strategy(strategy_id: int, config_id: int, update: StrategyConfigUpdate, db=Depends(get_db)):
    """
    Update a strategy config, enforcing that the config belongs to the given strategy.
    """
    validated_strategy_id = input_validator.validate_integer(strategy_id, "strategy_id", min_value=1)
    validated_config_id = input_validator.validate_integer(config_id, "config_id", min_value=1)
    # Fetch current config
    row = await get_strategy_config_by_id(db, validated_config_id)
    if not row:
        raise HTTPException(status_code=404, detail="Strategy config not found")
    if hasattr(row, "_mapping"):
        row = dict(row._mapping)
    if row.get("strategy_id") != validated_strategy_id:
        raise HTTPException(status_code=404, detail="Config does not belong to this strategy")
    
    # Prepare update data
    update_data = {}
    
    # Handle basic field updates
    if update.name is not None:
        update_data["name"] = update.name
    if update.description is not None:
        update_data["description"] = update.description
    if update.exchange is not None:
        update_data["exchange"] = update.exchange
    if update.instrument is not None:
        update_data["instrument"] = update.instrument
    
    # Handle trade configuration updates (replace fully)
    if update.trade is not None:
        update_data["trade"] = update.trade  # Full replace
    
    # Handle indicators configuration updates (replace fully)
    if update.indicators is not None:
        update_data["indicators"] = update.indicators  # Full replace
    
    updated = await update_strategy_config(db, validated_config_id, update_data)
    if hasattr(updated, "_mapping"):
        updated = dict(updated._mapping)
    return StrategyConfigDetailResponse(**updated)

@router.delete("/{strategy_id}/configs/{config_id}")
async def delete_strategy_config_for_strategy(strategy_id: int, config_id: int, db=Depends(get_db)):
    """
    Delete a strategy config, enforcing that the config belongs to the given strategy.
    """
    validated_strategy_id = input_validator.validate_integer(strategy_id, "strategy_id", min_value=1)
    validated_config_id = input_validator.validate_integer(config_id, "config_id", min_value=1)
    
    # Fetch current config to verify it belongs to the strategy
    row = await get_strategy_config_by_id(db, validated_config_id)
    if not row:
        raise HTTPException(status_code=404, detail="Strategy config not found")
    if hasattr(row, "_mapping"):
        row = dict(row._mapping)
    if row.get("strategy_id") != validated_strategy_id:
        raise HTTPException(status_code=404, detail="Config does not belong to this strategy")
    
    # Delete the config
    deleted = await delete_strategy_config(db, validated_config_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Strategy config not found")
    
    return {"message": "Strategy config deleted successfully", "config_id": validated_config_id}

@router.post("/{strategy_id}/symbols", response_model=StrategySymbolResponse)
async def add_symbol_to_strategy(strategy_id: int, symbol: StrategySymbolCreate, db=Depends(get_db)):
    """
    Add a symbol to a strategy with config assignment.
    """
    if symbol.strategy_id != strategy_id:
        raise HTTPException(status_code=400, detail="strategy_id mismatch")
    result = await add_strategy_symbol(db, symbol.strategy_id, symbol.symbol, symbol.config_id, symbol.status)
    return StrategySymbolResponse(**result)

@router.get("/{strategy_id}/symbols", response_model=List[StrategySymbolWithConfigResponse])
async def get_symbols_for_strategy(strategy_id: int, db=Depends(get_db)):
    """
    List all symbols for a given strategy with config information and trade statistics.
    """
    # Get basic symbol data
    rows = await list_strategy_symbols(db, strategy_id)
    
    # Get configs for this strategy to add config names
    configs = await get_strategy_configs_by_strategy_id(db, strategy_id)
    config_map = {config['id']: config for config in configs}
    
    # Enhance each symbol with config info and trade statistics
    enhanced_symbols = []
    for row in rows:
        symbol_data = dict(row)
        
        # Add config information
        config = config_map.get(symbol_data['config_id'], {})
        symbol_data['config_name'] = config.get('name', f"Config {symbol_data['config_id']}")
        symbol_data['config_description'] = config.get('description')
        
        # Add enabled field based on status
        symbol_data['enabled'] = symbol_data.get('status') == 'active'
        
        # Get trade statistics for this symbol
        try:
            trade_stats = await get_strategy_symbol_trade_stats(db, symbol_data['id'])
            symbol_data['live_trades'] = trade_stats['live_trade_count']
            symbol_data['live_pnl'] = trade_stats['live_pnl']
            symbol_data['total_trades'] = trade_stats['total_trade_count']
            symbol_data['total_pnl'] = trade_stats['total_pnl']
            symbol_data['all_trades'] = trade_stats['all_trade_count']
            # For backward compatibility with UI
            symbol_data['trade_count'] = trade_stats['all_trade_count']
            symbol_data['current_pnl'] = trade_stats['total_pnl']
        except Exception as e:
            logger.error(f"Error fetching trade stats for symbol {symbol_data['id']}: {e}")
            symbol_data['live_trades'] = 0
            symbol_data['live_pnl'] = 0.0
            symbol_data['total_trades'] = 0
            symbol_data['total_pnl'] = 0.0
            symbol_data['all_trades'] = 0
            symbol_data['trade_count'] = 0
            symbol_data['current_pnl'] = 0.0
        
        enhanced_symbols.append(StrategySymbolWithConfigResponse(**symbol_data))
    
    return enhanced_symbols

@router.put("/symbols/{symbol_id}/status", response_model=StrategySymbolResponse)
async def toggle_symbol_status(symbol_id: int, db=Depends(get_db)):
    """
    Toggle the status of a strategy symbol (active <-> inactive).
    """
    # First get the current status
    from algosat.core.dbschema import strategy_symbols
    from sqlalchemy import select
    
    stmt = select(strategy_symbols).where(strategy_symbols.c.id == symbol_id)
    result = await db.execute(stmt)
    row = result.first()
    
    if not row:
        raise HTTPException(status_code=404, detail="Strategy symbol not found")
    
    # Toggle the status
    current_status = row.status
    new_status = 'inactive' if current_status == 'active' else 'active'
    
    result = await set_strategy_symbol_status(db, symbol_id, new_status)
    return StrategySymbolResponse(**result)

@router.put("/symbols/{symbol_id}/enable", response_model=StrategySymbolResponse)
async def enable_symbol(symbol_id: int, db=Depends(get_db)):
    """
    Enable a strategy symbol.
    """
    result = await set_strategy_symbol_status(db, symbol_id, 'active')
    if not result:
        raise HTTPException(status_code=404, detail="Strategy symbol not found")
    return StrategySymbolResponse(**result)

@router.put("/symbols/{symbol_id}/disable", response_model=StrategySymbolResponse)
async def disable_symbol(symbol_id: int, db=Depends(get_db)):
    """
    Disable a strategy symbol.
    """
    result = await set_strategy_symbol_status(db, symbol_id, 'inactive')
    if not result:
        raise HTTPException(status_code=404, detail="Strategy symbol not found")
    return StrategySymbolResponse(**result)

@router.get("/symbols/{symbol_id}", response_model=StrategySymbolResponse)
async def get_strategy_symbol(symbol_id: int, db=Depends(get_db)):
    """
    Get a strategy symbol by ID.
    """
    result = await get_strategy_symbol_by_id(db, symbol_id)
    if not result:
        raise HTTPException(status_code=404, detail="Strategy symbol not found")
    return StrategySymbolResponse(**result)

@router.put("/symbols/{symbol_id}", response_model=StrategySymbolResponse)
async def update_strategy_symbol_route(symbol_id: int, update_data: dict, db=Depends(get_db)):
    """
    Update a strategy symbol.
    """
    result = await update_strategy_symbol(db, symbol_id, update_data)
    if not result:
        raise HTTPException(status_code=404, detail="Strategy symbol not found")
    return StrategySymbolResponse(**result)

@router.delete("/symbols/{symbol_id}")
async def delete_strategy_symbol_route(symbol_id: int, db=Depends(get_db)):
    """
    Delete a strategy symbol.
    """
    result = await delete_strategy_symbol(db, symbol_id)
    if not result:
        raise HTTPException(status_code=404, detail="Strategy symbol not found")
    return {"message": "Strategy symbol deleted successfully", "symbol_id": symbol_id}

@router.get("/symbols/{symbol_id}/stats")
async def get_symbol_trade_stats(symbol_id: int, db=Depends(get_db)):
    """
    Get trade statistics for a specific strategy symbol.
    Returns live trades (open) and total trades (completed) with P&L data.
    """
    try:
        validated_symbol_id = input_validator.validate_integer(symbol_id, "symbol_id", min_value=1)
        
        # Check if symbol exists
        symbol = await get_strategy_symbol_by_id(db, validated_symbol_id)
        if not symbol:
            raise HTTPException(status_code=404, detail="Strategy symbol not found")
        
        # Get trade statistics
        stats = await get_strategy_symbol_trade_stats(db, validated_symbol_id)
        
        return {
            "symbol_id": validated_symbol_id,
            "live_trades": stats["live_trade_count"],
            "live_pnl": stats["live_pnl"],
            "total_trades": stats["total_trade_count"],
            "total_pnl": stats["total_pnl"],
            "all_trades": stats["all_trade_count"],
            "enabled": symbol["status"] == "active"
        }
    except Exception as e:
        logger.error(f"Error in get_symbol_trade_stats: {e}")
        raise

@router.get("/symbols/{symbol_id}/trades")
async def get_symbol_trades(
    symbol_id: int, 
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    date: Optional[str] = Query(None, description="Date filter in YYYY-MM-DD format"),
    db=Depends(get_db)
):
    """
    Get detailed trade history for a specific strategy symbol with broker execution details.
    """
    try:
        validated_symbol_id = input_validator.validate_integer(symbol_id, "symbol_id", min_value=1)
        validated_limit = input_validator.validate_integer(limit, "limit", min_value=1, max_value=1000)
        validated_offset = input_validator.validate_integer(offset, "offset", min_value=0)
        
        # Validate date if provided
        parsed_date = None
        if date:
            parsed_date = input_validator.validate_date(date)
        
        # Check if symbol exists
        symbol = await get_strategy_symbol_by_id(db, validated_symbol_id)
        if not symbol:
            raise HTTPException(status_code=404, detail="Strategy symbol not found")
        
        # Get trades with broker execution details
        trades = await get_trades_for_symbol(db, validated_symbol_id, validated_limit, validated_offset, parsed_date)
        
        return {
            "symbol_id": validated_symbol_id,
            "trades": trades,
            "total_trades": len(trades)
        }
    except Exception as e:
        logger.error(f"Error in get_symbol_trades: {e}")
        raise
