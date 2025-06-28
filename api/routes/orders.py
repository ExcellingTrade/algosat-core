from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Dict, Any, List, Optional

from algosat.core.db import (
    get_all_orders, 
    get_orders_by_symbol, 
    get_orders_by_broker, 
    get_orders_by_broker_and_strategy,
    get_order_by_id,
    get_broker_executions_by_order_id,
    get_granular_executions_by_order_id,
    get_executions_summary_by_order_id,
    get_orders_summary_by_symbol,
    get_orders_by_strategy_symbol_id,
    get_strategy_symbol_by_name
)
from algosat.api.schemas import (
    OrderListResponse, 
    OrderDetailResponse, 
    BrokerExecutionResponse,
    GranularExecutionResponse,
    ExecutionSummaryResponse,
    OrdersSummaryResponse
)
from algosat.api.dependencies import get_db
from algosat.api.auth_dependencies import get_current_user
from algosat.core.security import EnhancedInputValidator, InvalidInputError
from algosat.common.logger import get_logger

router = APIRouter(dependencies=[Depends(get_current_user)])
input_validator = EnhancedInputValidator()
logger = get_logger("api.orders")

@router.get("/", response_model=List[OrderListResponse])
async def list_orders(
    broker_name: Optional[str] = Query(None, description="Filter orders by broker name"),
    strategy_config_id: Optional[int] = Query(None, description="Filter orders by strategy config ID"),
    db=Depends(get_db), 
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    List all orders or filter by broker and/or strategy.
    
    Available filters:
    - No filters: Returns all orders
    - broker_name only: Returns orders for specific broker
    - broker_name + strategy_config_id: Returns orders for specific broker and strategy config
    
    Returns basic order information including symbol, broker, status, and pricing.
    """
    try:
        # Validate input parameters
        validated_broker = None
        validated_strategy_config_id = None
        
        if broker_name:
            validated_broker = input_validator.validate_and_sanitize(
                broker_name, "broker_name", expected_type=str, max_length=256, 
                pattern=r"^[a-zA-Z0-9_-]+$"
            )
        
        if strategy_config_id:
            validated_strategy_config_id = input_validator.validate_integer(strategy_config_id, "strategy_config_id", min_value=1)
        
        # Execute query based on filters
        if validated_broker and validated_strategy_config_id:
            # Filter by both broker and strategy config
            rows = await get_orders_by_broker_and_strategy(db, validated_broker, validated_strategy_config_id)
        elif validated_broker:
            # Filter by broker only
            rows = await get_orders_by_broker(db, validated_broker)
        else:
            # No filters - get all orders
            rows = await get_all_orders(db)
        
        # Debug logging
        print(f"DEBUG: rows returned from db: {len(rows) if rows else 0}")
        if rows:
            print(f"DEBUG: first row: {rows[0]}")
        
        orders = [OrderListResponse(**row) for row in rows]
        print(f"DEBUG: orders after schema conversion: {len(orders)}")
        
        return sorted(orders, key=lambda o: o.signal_time or "", reverse=True)
        
    except InvalidInputError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error in list_orders: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve orders")

@router.get("/{order_id}", response_model=OrderDetailResponse)
async def get_order(
    order_id: int, 
    db=Depends(get_db), 
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Get detailed information for a specific order.
    Returns complete order details including strategy information, all prices, and timing data.
    """
    try:
        # Validate order_id
        validated_order_id = input_validator.validate_and_sanitize(
            order_id, "order_id", expected_type=int
        )
        
        row = await get_order_by_id(db, validated_order_id)
        if not row:
            raise HTTPException(status_code=404, detail="Order not found")
        
        return OrderDetailResponse(**row)
        
    except InvalidInputError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get_order: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve order details")

@router.get("/{order_id}/executions", response_model=List[BrokerExecutionResponse])
async def get_broker_executions(
    order_id: int,
    db=Depends(get_db),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    DEPRECATED: Legacy broker executions endpoint.
    Use /orders/{order_id}/granular-executions for new granular execution data.
    """
    try:
        executions = await get_broker_executions_by_order_id(db, order_id)
        return executions
    except Exception as e:
        logger.error(f"Error in get_broker_executions: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve broker executions")

@router.get("/{order_id}/granular-executions", response_model=List[GranularExecutionResponse])
async def get_granular_executions(
    order_id: int,
    side: Optional[str] = Query(None, description="Filter by execution side: ENTRY or EXIT"),
    db=Depends(get_db),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Get granular execution records for a given logical order.
    Each record represents an actual fill/execution with real traded price and quantity.
    
    Args:
        order_id: Logical order ID from orders table
        side: Optional filter by 'ENTRY' or 'EXIT'
    """
    try:
        # Validate side parameter
        if side and side.upper() not in ['ENTRY', 'EXIT']:
            raise HTTPException(status_code=400, detail="Invalid side parameter. Use 'ENTRY' or 'EXIT'")
        
        executions = await get_granular_executions_by_order_id(db, order_id, side)
        
        # Convert to response models
        return [GranularExecutionResponse(
            id=ex['id'],
            parent_order_id=ex['parent_order_id'],
            broker_id=ex['broker_id'],
            broker_order_id=ex['broker_order_id'],
            side=ex['side'],
            execution_price=float(ex['execution_price']),
            executed_quantity=ex['executed_quantity'],
            execution_time=ex.get('execution_time'),
            execution_id=ex.get('execution_id'),
            is_partial_fill=ex.get('is_partial_fill', False),
            sequence_number=ex.get('sequence_number'),
            symbol=ex.get('symbol'),
            order_type=ex.get('order_type'),
            notes=ex.get('notes'),
            status=ex['status'],
            created_at=ex['created_at']
        ) for ex in executions]
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get_granular_executions: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve granular executions")

@router.get("/{order_id}/execution-summary", response_model=ExecutionSummaryResponse)
async def get_execution_summary(
    order_id: int,
    db=Depends(get_db),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Get execution summary for an order including VWAP calculations and P&L.
    
    This endpoint provides:
    - All entry and exit executions
    - Entry and exit VWAP prices
    - Total quantities
    - Realized and unrealized P&L
    """
    try:
        summary = await get_executions_summary_by_order_id(db, order_id)
        
        # Convert execution records to response models
        entry_executions = [GranularExecutionResponse(
            id=ex['id'],
            parent_order_id=ex['parent_order_id'],
            broker_id=ex['broker_id'],
            broker_order_id=ex['broker_order_id'],
            side=ex['side'],
            execution_price=float(ex['execution_price']),
            executed_quantity=ex['executed_quantity'],
            execution_time=ex.get('execution_time'),
            execution_id=ex.get('execution_id'),
            is_partial_fill=ex.get('is_partial_fill', False),
            sequence_number=ex.get('sequence_number'),
            symbol=ex.get('symbol'),
            order_type=ex.get('order_type'),
            notes=ex.get('notes'),
            status=ex['status'],
            created_at=ex['created_at']
        ) for ex in summary['entry_executions']]
        
        exit_executions = [GranularExecutionResponse(
            id=ex['id'],
            parent_order_id=ex['parent_order_id'],
            broker_id=ex['broker_id'],
            broker_order_id=ex['broker_order_id'],
            side=ex['side'],
            execution_price=float(ex['execution_price']),
            executed_quantity=ex['executed_quantity'],
            execution_time=ex.get('execution_time'),
            execution_id=ex.get('execution_id'),
            is_partial_fill=ex.get('is_partial_fill', False),
            sequence_number=ex.get('sequence_number'),
            symbol=ex.get('symbol'),
            order_type=ex.get('order_type'),
            notes=ex.get('notes'),
            status=ex['status'],
            created_at=ex['created_at']
        ) for ex in summary['exit_executions']]
        
        return ExecutionSummaryResponse(
            order_id=order_id,
            entry_executions=entry_executions,
            exit_executions=exit_executions,
            entry_vwap=summary['entry_vwap'],
            exit_vwap=summary['exit_vwap'],
            entry_qty=summary['entry_qty'],
            exit_qty=summary['exit_qty'],
            realized_pnl=summary['realized_pnl'],
            unrealized_pnl=summary['unrealized_pnl']
        )
        
    except Exception as e:
        logger.error(f"Error in get_execution_summary: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve execution summary")

@router.get("/by-symbol/{symbol}", response_model=List[OrderListResponse])
async def get_orders_by_symbol_endpoint(
    symbol: str,
    db=Depends(get_db), 
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Get all orders for a specific symbol.
    Returns orders filtered by strategy_symbol_id for trade analysis.
    """
    try:
        # Validate symbol parameter
        validated_symbol = input_validator.validate_and_sanitize(
            symbol, "symbol", expected_type=str, max_length=100,
            pattern=r"^[a-zA-Z0-9_\-\.]+$"
        )
        
        # First, get the strategy_symbol record
        strategy_symbol = await get_strategy_symbol_by_name(db, validated_symbol)
        
        if not strategy_symbol:
            # Symbol not found in strategy_symbols table
            print(f"DEBUG: strategy symbol '{validated_symbol}' not found")
            return []
        
        # Get orders by strategy_symbol_id
        rows = await get_orders_by_strategy_symbol_id(db, strategy_symbol['id'])
        
        # Debug logging
        print(f"DEBUG: orders for strategy_symbol_id {strategy_symbol['id']} (symbol: '{validated_symbol}'): {len(rows) if rows else 0}")
        if rows:
            print(f"DEBUG: first order: {rows[0]}")
        
        orders = [OrderListResponse(**row) for row in rows]
        return sorted(orders, key=lambda o: o.signal_time or "", reverse=True)
        
    except InvalidInputError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error in get_orders_by_symbol_endpoint: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve orders by symbol")

@router.get("/summary/{symbol}", response_model=OrdersSummaryResponse)
async def get_orders_summary_endpoint(
    symbol: str,
    db=Depends(get_db), 
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Get summary statistics for orders of a specific symbol.
    Returns aggregated trade data including total P&L, trade counts, etc.
    """
    try:
        # Validate symbol parameter
        validated_symbol = input_validator.validate_and_sanitize(
            symbol, "symbol", expected_type=str, max_length=100,
            pattern=r"^[a-zA-Z0-9_\-\.]+$"
        )
        
        summary = await get_orders_summary_by_symbol(db, validated_symbol)
        
        # Debug logging
        print(f"DEBUG: orders summary for symbol '{validated_symbol}': {summary}")
        
        return OrdersSummaryResponse(**summary)
        
    except InvalidInputError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error in get_orders_summary_endpoint: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve orders summary")
