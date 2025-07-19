from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Dict, Any, List, Optional

from algosat.core.db import (
    get_all_orders, 
    get_orders_by_symbol, 
    get_orders_by_broker, 
    get_orders_by_broker_and_strategy,
    get_order_by_id,
    get_broker_executions_for_order,
    # get_granular_executions_for_order,
    get_executions_summary_by_order_id,
    get_orders_summary_by_symbol,
    get_orders_by_strategy_symbol_id,
    get_strategy_symbol_by_name,
    get_orders_pnl_stats,
    get_orders_pnl_stats_by_symbol_id,
    get_strategy_profit_loss_stats,
    get_daily_pnl_history,
    get_per_strategy_statistics
)
from algosat.api.schemas import (
    OrderListResponse, 
    OrderDetailResponse, 
    BrokerExecutionResponse,
    GranularExecutionResponse,
    ExecutionSummaryResponse,
    OrdersSummaryResponse,
    OrdersPnlStatsResponse,
    StrategyStatsResponse,
    DailyPnlHistoryResponse,
    DailyPnlData,
    PerStrategyStatsResponse,
    PerStrategyStatsData
)
from algosat.api.dependencies import get_db, get_order_manager
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

# === Statistics Routes (Must come before /{order_id} to avoid path conflicts) ===

@router.get("/pnl-stats", response_model=OrdersPnlStatsResponse)
async def get_orders_pnl_stats_endpoint(
    symbol: Optional[str] = Query(None, description="Filter by symbol (supports partial match)"),
    date: Optional[str] = Query(None, description="Date filter in YYYY-MM-DD format (defaults to today)"),
    db=Depends(get_db), 
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Get overall and today's P&L statistics from orders.
    
    This endpoint provides:
    - Overall P&L and trade count (all completed trades)
    - Today's P&L and trade count (trades completed today)
    
    Optional filters:
    - symbol: Filter by strike_symbol (supports partial matching)
    - date: Override "today" with a specific date (YYYY-MM-DD format)
    
    Returns P&L statistics for completed/closed trades only.
    """
    try:
        # Validate and parse date if provided
        import datetime
        parsed_date = None
        if date:
            parsed_date = input_validator.validate_date(date)
        
        # Validate symbol if provided
        validated_symbol = None
        if symbol:
            validated_symbol = input_validator.validate_symbol(symbol)
        
        stats = await get_orders_pnl_stats(db, symbol=validated_symbol, date=parsed_date)
        
        # Debug logging
        print(f"DEBUG: orders P&L stats for symbol '{validated_symbol}', date '{parsed_date}': {stats}")
        
        return OrdersPnlStatsResponse(**stats)
        
    except InvalidInputError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error in get_orders_pnl_stats_endpoint: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")

@router.get("/strategy-stats", response_model=StrategyStatsResponse)
async def get_strategy_profit_loss_stats_endpoint(
    db=Depends(get_db), 
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Get strategy profit/loss statistics.
    
    This endpoint provides:
    - Number of strategies currently in profit
    - Number of strategies currently in loss
    - Total number of strategies with trades
    
    Statistics are calculated by aggregating P&L from all orders per strategy symbol.
    """
    try:
        stats = await get_strategy_profit_loss_stats(db)
        
        # Debug logging
        print(f"DEBUG: strategy stats: {stats}")
        
        return StrategyStatsResponse(**stats)
        
    except Exception as e:
        logger.error(f"Error in get_strategy_profit_loss_stats_endpoint: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")

@router.get("/daily-pnl-history", response_model=DailyPnlHistoryResponse)
async def get_daily_pnl_history_endpoint(
    days: int = Query(30, description="Number of days to look back (default 30)", ge=1, le=365),
    db=Depends(get_db), 
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Get daily P&L history for charting and performance analysis.
    
    This endpoint provides:
    - Daily P&L for each trading day
    - Number of trades per day  
    - Cumulative P&L progression
    
    Parameters:
    - days: Number of days to look back (1-365, default 30)
    
    Returns historical daily P&L data suitable for charting.
    """
    try:
        daily_data = await get_daily_pnl_history(db, days=days)
        
        # Convert to response format
        history = [DailyPnlData(**data) for data in daily_data if data.get('date')]
        
        # Debug logging
        print(f"DEBUG: daily P&L history for {days} days: {len(history)} data points")
        
        return DailyPnlHistoryResponse(
            history=history,
            total_days=len(history)
        )
        
    except Exception as e:
        logger.error(f"Error in get_daily_pnl_history_endpoint: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")

@router.get("/per-strategy-stats", response_model=PerStrategyStatsResponse)
async def get_per_strategy_stats_endpoint(
    db=Depends(get_db), 
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Get per-strategy statistics.
    
    This endpoint provides for each strategy:
    - Live P&L (Today's P&L)
    - Overall P&L (All-time P&L)
    - Total number of trades
    - Win rate percentage
    
    Returns comprehensive statistics for all strategies with trading activity.
    """
    try:
        stats_data = await get_per_strategy_statistics(db)
        
        # Convert to response format
        strategies = [PerStrategyStatsData(**data) for data in stats_data]
        
        # Debug logging
        print(f"DEBUG: per-strategy stats: {len(strategies)} strategies")
        
        return PerStrategyStatsResponse(
            strategies=strategies,
            total_strategies=len(strategies)
        )
        
    except Exception as e:
        logger.error(f"Error in get_per_strategy_stats_endpoint: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")

@router.get("/pnl-stats/by-symbol-id/{strategy_symbol_id}", response_model=OrdersPnlStatsResponse)
async def get_orders_pnl_stats_by_symbol_id_endpoint(
    strategy_symbol_id: int,
    date: Optional[str] = Query(None, description="Date filter in YYYY-MM-DD format (defaults to today)"),
    db=Depends(get_db), 
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Get overall and today's P&L statistics for a specific strategy symbol ID.
    
    This endpoint provides:
    - Overall P&L and trade count (all completed trades)
    - Today's P&L and trade count (trades completed today)
    
    Path parameter:
    - strategy_symbol_id: The ID of the strategy symbol to filter by
    
    Optional query parameter:
    - date: Override "today" with a specific date (YYYY-MM-DD format)
    
    Returns P&L statistics for completed/closed trades only.
    This is more accurate than filtering by symbol name as it directly matches orders.
    """
    try:
        # Validate and parse date if provided
        import datetime
        parsed_date = None
        if date:
            parsed_date = input_validator.validate_date(date)
        
        # Validate strategy_symbol_id
        if strategy_symbol_id <= 0:
            raise HTTPException(status_code=400, detail="Invalid strategy_symbol_id")
        
        stats = await get_orders_pnl_stats_by_symbol_id(db, strategy_symbol_id=strategy_symbol_id, date=parsed_date)
        
        # Debug logging
        print(f"DEBUG: orders P&L stats for strategy_symbol_id '{strategy_symbol_id}', date '{parsed_date}': {stats}")
        
        return OrdersPnlStatsResponse(**stats)
        
    except InvalidInputError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error in get_orders_pnl_stats_by_symbol_id_endpoint: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")

# === Individual Order Routes ===

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
        executions = await get_broker_executions_for_order(db, order_id)
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
        
        executions = await get_granular_executions_for_order(db, order_id, side)
        
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
        raise HTTPException(status_code=500, detail="Internal Server Error")

# === Order Exit Endpoints ===

@router.post("/{order_id}/exit")
async def exit_order(
    order_id: int,
    exit_reason: Optional[str] = Query(None, description="Reason for exiting the order"),
    ltp: Optional[float] = Query(None, description="Last traded price to use as exit price"),
    order_manager = Depends(get_order_manager),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Exit a single order by order ID.
    
    This endpoint will:
    - For FILLED orders: Place exit orders with brokers
    - For PARTIALLY_FILLED orders: Place exit orders and cancel remaining quantity
    - For AWAITING_ENTRY/PENDING orders: Cancel the orders
    - For REJECTED/FAILED orders: No action needed
    
    Args:
        order_id: The order ID to exit
        exit_reason: Optional reason for the exit
        ltp: Optional last traded price to use as exit price
        
    Returns:
        Success message with order ID
    """
    try:
        # Validate order_id
        if order_id <= 0:
            raise HTTPException(status_code=400, detail="Invalid order_id")
        
        # Validate ltp if provided
        if ltp is not None and ltp <= 0:
            raise HTTPException(status_code=400, detail="LTP must be a positive number")
        
        # Call OrderManager to exit the order
        await order_manager.exit_order(
            parent_order_id=order_id,
            exit_reason=exit_reason,
            ltp=ltp
        )
        
        logger.info(f"Order {order_id} exit initiated successfully. Reason: {exit_reason}")
        
        return {
            "success": True,
            "message": f"Order {order_id} exit initiated successfully",
            "order_id": order_id,
            "exit_reason": exit_reason
        }
        
    except Exception as e:
        logger.error(f"Error in exit_order endpoint for order_id {order_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to exit order: {str(e)}")

@router.post("/exit-all")
async def exit_all_orders(
    exit_reason: Optional[str] = Query(None, description="Reason for exiting all orders"),
    strategy_id: Optional[int] = Query(None, description="Optional strategy ID to filter orders by"),
    order_manager = Depends(get_order_manager),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Exit all open orders, optionally filtered by strategy.
    
    This endpoint will:
    - Query all open orders from the database (optionally filtered by strategy_id)
    - For each open order, call the exit_order logic:
      - FILLED orders: Place exit orders with brokers
      - PARTIALLY_FILLED orders: Place exit orders and cancel remaining quantity
      - AWAITING_ENTRY/PENDING orders: Cancel the orders
      - REJECTED/FAILED orders: No action needed
    
    Args:
        exit_reason: Optional reason for exiting all orders
        strategy_id: Optional strategy ID to filter orders by. If provided, only orders 
                    belonging to this strategy will be exited.
        
    Returns:
        Success message with count of orders processed
    """
    try:
        # Call OrderManager to exit all orders
        await order_manager.exit_all_orders(exit_reason=exit_reason, strategy_id=strategy_id)
        
        filter_desc = f" for strategy {strategy_id}" if strategy_id else ""
        logger.info(f"Exit all orders initiated successfully{filter_desc}. Reason: {exit_reason}")
        
        return {
            "success": True,
            "message": f"Exit all orders initiated successfully{filter_desc}",
            "exit_reason": exit_reason,
            "strategy_id": strategy_id
        }
        
    except Exception as e:
        logger.error(f"Error in exit_all_orders endpoint: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to exit all orders: {str(e)}")
