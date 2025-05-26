from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Dict, Any, List, Optional

from algosat.core.db import get_all_orders, get_order_by_id, get_orders_by_broker, get_orders_by_broker_and_strategy
from algosat.api.schemas import OrderListResponse, OrderDetailResponse
from algosat.api.dependencies import get_db, get_current_user
from algosat.core.security import EnhancedInputValidator, InvalidInputError

router = APIRouter()
input_validator = EnhancedInputValidator()

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
            validated_strategy_config_id = input_validator.validate_and_sanitize(
                strategy_config_id, "strategy_config_id", expected_type=int, min_value=1
            )
        
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
            order_id, "order_id", expected_type=int, min_value=1
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
        raise HTTPException(status_code=500, detail="Failed to retrieve order details")
