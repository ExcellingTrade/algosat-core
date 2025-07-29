# core/order_manager.py
"""
OrderManager: Responsible for managing the lifecycle of orders across all brokers that are trade enabled and live/authenticated.
"""
from typing import Optional, Dict, Any, List # Added typing imports
from algosat.core.db import get_order_by_id, get_trade_enabled_brokers, AsyncSessionLocal, insert_order, get_broker_by_name
from algosat.brokers.factory import get_broker
from algosat.common.logger import get_logger
from algosat.core.dbschema import trade_logs
from algosat.core.broker_manager import BrokerManager
from algosat.core.order_request import OrderRequest, OrderStatus, Side, OrderType, ExecutionSide
from algosat.core.dbschema import orders as orders_table
from algosat.models.strategy_config import StrategyConfig
from algosat.models.order_aggregate import OrderAggregate, BrokerOrder
from sqlalchemy import text
import json
import numpy as np
import pandas as pd
from datetime import datetime
from algosat.core.time_utils import to_ist
import pytz
from enum import Enum

logger = get_logger("OrderManager")

# Fyers status code mapping (example, update as per Fyers API)
FYERS_STATUS_MAP = {
    1: OrderStatus.CANCELLED,      # 1 = Cancelled
    2: OrderStatus.FILLED,        # 2 = Traded / Filled
    3: OrderStatus.PENDING,       # 3 = For future use (treat as Pending)
    4: OrderStatus.PENDING,       # 4 = Transit (treat as Pending)
    5: OrderStatus.REJECTED,      # 5 = Rejected
    6: OrderStatus.PENDING,       # 6 = Pending
    # Add more mappings as per Fyers API
}

FYERS_ORDER_TYPE_MAP = {
    1: "Limit",      # 1 => Limit Order
    2: "Market",     # 2 => Market Order
    3: "SL-M",       # 3 => Stop Order (SL-M)
    4: "SL-L",       # 4 => Stoplimit Order (SL-L)
}


# Zerodha status mapping (partial, based on image)
ZERODHA_STATUS_MAP = {
    "PUT ORDER REQ RECEIVED": OrderStatus.AWAITING_ENTRY,
    "AMO REQ RECEIVED": OrderStatus.AWAITING_ENTRY,
    "VALIDATION PENDING": OrderStatus.PENDING,
    "OPEN PENDING": OrderStatus.PENDING,
    "MODIFY VALIDATION PENDING": OrderStatus.PENDING,
    "MODIFY PENDING": OrderStatus.PENDING,
    "TRIGGER PENDING": OrderStatus.TRIGGER_PENDING,
    "CANCEL PENDING": OrderStatus.PENDING,
    "OPEN": OrderStatus.OPEN,
    "COMPLETE": OrderStatus.FILLED,
    "CANCELLED": OrderStatus.CANCELLED,
    "REJECTED": OrderStatus.REJECTED,
    # Add more as needed
}

class OrderManager:
    def __init__(self, broker_manager: BrokerManager):
        self.broker_manager: BrokerManager = broker_manager

    @staticmethod
    def extract_strategy_config_id(config: StrategyConfig | dict) -> int | None:
        """
        Extract strategy_config_id from a StrategyConfig dataclass, dict, or ORM row.
        """
        if isinstance(config, StrategyConfig):
            return config.id
        # Direct attribute or key
        for key in ("strategy_config_id", "id"):  # prefer explicit field if present
            if isinstance(config, dict) and key in config:
                return config[key]
            if hasattr(config, key):
                return getattr(config, key)
        # Nested under 'config' attribute or key
        for key in ("config",):
            nested = None
            if isinstance(config, dict) and key in config:
                nested = config[key]
            elif hasattr(config, key):
                nested = getattr(config, key)
            if nested:
                for subkey in ("strategy_config_id", "id"):
                    if isinstance(nested, dict) and subkey in nested:
                        return nested[subkey]
                    if hasattr(nested, subkey):
                        return getattr(nested, subkey)
        return None

    async def place_order(
        self,
        config: StrategyConfig,
        order_payload: OrderRequest,
        strategy_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Places an order by building a canonical OrderRequest and delegating to BrokerManager for broker routing.
        Inserts one row in orders (logical trade), and one row per broker in broker_executions.
        Returns the logical order id (orders.id) as canonical reference.

        Args:
            config: The strategy configuration (StrategyConfig instance).
            order_payload: The OrderRequest object detailing the order.
            strategy_name: Optional name of the strategy placing the order.

        Returns:
            A dictionary containing the overall status and individual broker responses.
        """
        if not isinstance(config, StrategyConfig):
            logger.error("OrderManager.place_order: config must be a StrategyConfig instance.")
            return {
                "overall_status": "error",
                "message": "Invalid config type.",
                "broker_responses": {}
            }
        if not isinstance(order_payload, OrderRequest):
            logger.error("OrderManager.place_order: order_payload must be an OrderRequest instance.")
            return {
                "overall_status": "error",
                "message": "Invalid order_payload type.",
                "broker_responses": {}
            }
        # Do NOT overwrite order_payload.side here; keep BUY/SELL for orders table and broker API
        # Only use ENTRY/EXIT in broker_executions
        # Check for split
        max_nse_qty = None
        if hasattr(config, 'trade') and isinstance(config.trade, dict):
            max_nse_qty = config.trade.get('max_nse_qty', config.trade.get('max_nse_qtty', 900))
        if max_nse_qty and order_payload.quantity > max_nse_qty:
            return await self.split_and_place_order(config, order_payload, max_nse_qty, strategy_name, check_margin=check_margin)
        # 1. Insert logical order row (orders)
        async with AsyncSessionLocal() as session:
            order_id = await self._insert_and_get_order_id(
                config=config,
                order_payload=order_payload,
                broker_name=None,
                result=None,
                parent_order_id=None
            )
            if not order_id:
                logger.error("Failed to insert logical order row.")
                return None
            # 2. Place order(s) with brokers
            check_margin = config.trade.get('check_margin', False)
            
            broker_responses = await self.broker_manager.place_order(order_payload, strategy_name=strategy_name, check_margin=check_margin)
            # 3. Insert broker_executions rows
            for broker_name, response in broker_responses.items():
                action = str(getattr(order_payload, 'side', None) or response.get('side', None) or 'BUY').upper()
                await self._insert_broker_execution(session, order_id, broker_name, response, side=ExecutionSide.ENTRY.value, action=action)
            await session.commit()
        # Return enhanced response with traded_price
        return {
            "order_id": order_id,
            "traded_price": 0.0,  # Default value for now, will be updated per broker later
            "status": "AWAITING_ENTRY",  # Initial status
            "broker_responses": broker_responses
        }

    async def split_and_place_order(
        self,
        config: StrategyConfig,
        order_payload: OrderRequest,
        max_nse_qty: int,
        strategy_name: Optional[str] = None,
        check_margin: bool = False,
    ) -> Dict[str, Any]:
        """
        Split the order into chunks if the quantity exceeds max_nse_qty and place each chunk as a separate order.
        Each split order is inserted as a separate broker_executions entry (per split).
        """
        logger.info(f"Splitting order for symbol={order_payload.symbol}, total_qty={order_payload.quantity}, max_nse_qty={max_nse_qty}")
        trigger_price_diff = 0.0
        if hasattr(config, 'trade') and isinstance(config.trade, dict):
            trigger_price_diff = config.trade.get('trigger_price_diff', 0.0)
        total_qty = order_payload.quantity
        responses = []
        original_price = getattr(order_payload, 'price', 0) or order_payload.extra.get('entry_price', 0)
        max_price_increase = 2.00
        price_increment = 0.20
        current_price = original_price
        qty_left = total_qty
        slice_num = 0
        async with AsyncSessionLocal() as session:
            parent_order_id = await self._insert_and_get_order_id(
                config=config,
                order_payload=order_payload,
                broker_name=None,
                result=None,
                parent_order_id=None
            )
            if not parent_order_id:
                logger.error("Failed to insert logical order row for split order.")
                return None
            while qty_left > 0:
                qty = min(qty_left, max_nse_qty)
                trigger_price = (current_price - trigger_price_diff) if order_payload.side == Side.BUY else (current_price + trigger_price_diff)
                slice_payload = self.create_slice_payload(order_payload, qty, current_price, trigger_price, "ENTRY")
                broker_responses = await self.broker_manager.place_order(slice_payload, strategy_name=strategy_name, check_margin=check_margin)
                for broker_name, response in broker_responses.items():
                    # Insert a broker_executions row for this split order
                    action = str(getattr(order_payload, 'side', None) or response.get('side', None) or 'BUY').upper()
                    await self._insert_broker_execution(
                        session,
                        parent_order_id,
                        broker_name,
                        response,
                        side=ExecutionSide.ENTRY.value,
                        action=action
                    )
                    responses.append({
                        'broker_name': broker_name,
                        'response': response,
                        'slice_num': slice_num
                    })
                if getattr(order_payload, 'order_type', None) != OrderType.MARKET:
                    if (current_price - original_price) < max_price_increase:
                        current_price = min(original_price + max_price_increase, current_price + price_increment)
                qty_left -= qty
                slice_num += 1
            await session.commit()
        return {'order_id': parent_order_id, 'slices': responses}

    async def _set_parent_order_id(self, order_id, parent_order_id):
        """
        Update the parent_order_id of an order row after insert.
        """
        from algosat.core.db import AsyncSessionLocal, update_rows_in_table
        from algosat.core.dbschema import orders
        async with AsyncSessionLocal() as session:
            await update_rows_in_table(
                target_table=orders,
                condition=orders.c.id == order_id,
                new_values={"parent_order_id": parent_order_id}
            )

    async def _insert_and_get_order_id(
        self,
        config: StrategyConfig,
        order_payload: OrderRequest,
        broker_name: Optional[str],
        result: Optional[dict],
        parent_order_id: Optional[int],
    ) -> Optional[int]:
        """
        Insert order into DB and return the local order_id. Sets parent_order_id if provided.
        Handles both success and failure cases, storing raw broker response if failed.
        """
        def to_native(val):
            if isinstance(val, np.generic):
                return val.item()
            # Ensure Enums are converted to their values *before* other checks
            if hasattr(val, 'value') and isinstance(val, (Side, OrderType)): # More specific check for our enums
                return val.value
            if hasattr(val, 'name') and isinstance(val, (Side, OrderType)): # Fallback for name if value isn't the target (though .value is standard)
                 return val.name
            import pandas as pd
            if isinstance(val, (pd.Timestamp, np.datetime64)):
                if hasattr(val, 'to_pydatetime'):
                    return val.to_pydatetime()
                else:
                    return pd.to_datetime(val).to_pydatetime()
            return val

        def ensure_utc_aware(val):
            import pandas as pd
            if isinstance(val, (pd.Timestamp, np.datetime64)):
                if hasattr(val, 'to_pydatetime'):
                    val = val.to_pydatetime()
                else:
                    val = pd.to_datetime(val).to_pydatetime()
            if isinstance(val, datetime):
                if val.tzinfo is None:
                    # Assume IST if naive, convert to UTC
                    val = pytz.timezone("Asia/Kolkata").localize(val)
                return val.astimezone(pytz.UTC)
            return val

        async with AsyncSessionLocal() as sess:
            # Only set broker_id if broker_name is provided (for broker_executions, not logical order)
            strategy_config_id = config.id if isinstance(config, StrategyConfig) else self.extract_strategy_config_id(config)
            if not strategy_config_id:
                logger.error(f"[OrderManager] Could not extract strategy_config_id from config: {repr(config)}. Order will not be inserted.")
                return None
            # --- Use symbol_id directly from config (already contains strategy_symbols.id) ---
            strategy_symbol_id = getattr(config, 'symbol_id', None)
            if not strategy_symbol_id:
                logger.error(f"[OrderManager] Could not extract strategy_symbol_id from config: {repr(config)}. Config must have symbol_id field. Order will not be inserted.")
                return None
            
            # Log for clarity: underlying vs strike symbol distinction
            underlying_symbol = getattr(config, 'symbol', 'Unknown')  # e.g., "NIFTY50" 
            strike_symbol = getattr(order_payload, 'symbol', 'Unknown')  # e.g., "NIFTY50-25JUN25-23400-CE"
            logger.debug(f"[OrderManager] Order for underlying={underlying_symbol}, strike={strike_symbol}, strategy_symbol_id={strategy_symbol_id}")
            # --- Build order_data for logical order (orders table) ---
            order_data = {
                "strategy_symbol_id": strategy_symbol_id,
                "strike_symbol": strike_symbol,  # NEW: Store the actual tradeable strike symbol
                "pnl": 0.0,  # NEW: Initialize PnL to 0 (will be updated when order is closed)
                "candle_range": order_payload.extra.get("candle_range"),
                "entry_price": order_payload.extra.get("entry_price", order_payload.price),
                "stop_loss": order_payload.extra.get("stop_loss"),
                "target_price": order_payload.extra.get("target_price"),
                "signal_time": ensure_utc_aware(order_payload.extra.get("signal_time")),
                "entry_time": ensure_utc_aware(order_payload.extra.get("entry_time")),
                "exit_time": ensure_utc_aware(order_payload.extra.get("exit_time")),
                "exit_price": order_payload.extra.get("exit_price"),
                "status": order_payload.extra.get("status", "AWAITING_ENTRY").value if hasattr(order_payload.extra.get("status", "AWAITING_ENTRY"), 'value') else str(order_payload.extra.get("status", "AWAITING_ENTRY")),
                "reason": order_payload.extra.get("reason"),
                "atr": order_payload.extra.get("atr"),
                "supertrend_signal": order_payload.extra.get("supertrend_signal"),
                "lot_qty": order_payload.extra.get("lot_qty"),
                "side": order_payload.side.value if hasattr(order_payload.side, 'value') else str(order_payload.side),
                "signal_direction": order_payload.extra.get("signal_direction"),
                "qty": order_payload.quantity,
                "entry_spot_price": order_payload.extra.get("entry_spot_price"),
                "entry_spot_swing_high": order_payload.extra.get("entry_spot_swing_high"),
                "entry_spot_swing_low": order_payload.extra.get("entry_spot_swing_low"),
                "stoploss_spot_level": order_payload.extra.get("stoploss_spot_level"),
                "target_spot_level": order_payload.extra.get("target_spot_level"),
                "entry_rsi": order_payload.extra.get("entry_rsi"),
                "expiry_date": ensure_utc_aware(order_payload.extra.get("expiry_date")),
            }
            inserted = await insert_order(sess, order_data)
            return inserted["id"] if inserted else None

    @staticmethod
    def to_enum_value(val):
        """
        Utility to extract the value from an Enum or return the value as-is.
        """
        if hasattr(val, 'value'):
            return val.value
        return val

    def build_broker_exec_data(self, *, parent_order_id, broker_id, broker_order_id, side, status, executed_quantity=0, execution_price=0.0, product_type=None, order_type=None, order_messages=None, action=None, raw_execution_data=None, symbol=None, execution_time=None, notes=None):
        """
        Utility to build the broker execution data dict for DB insert.
        """
        # Additional safety check for boolean status values
        if isinstance(status, bool):
            status = "FAILED" if status is False else "PENDING"
            logger.warning(f"OrderManager: build_broker_exec_data converted boolean status to string: {status}")
        
        return dict(
            parent_order_id=parent_order_id,
            broker_id=broker_id,
            broker_order_id=broker_order_id,
            side=side,
            action=action or side,
            status=OrderManager.to_enum_value(status),
            executed_quantity=executed_quantity,
            execution_price=execution_price,
            product_type=product_type,
            order_type=order_type,
            order_messages=order_messages,
            raw_execution_data=raw_execution_data,
            symbol=symbol,
            execution_time=execution_time,
            notes=notes
        )

    def validate_broker_fields(self, broker_id, symbol, context_msg=""):
        """
        Utility to log warnings/errors for missing broker_id or symbol.
        """
        if broker_id is None:
            logger.warning(f"OrderManager: Missing broker_id. {context_msg}")
        if not symbol:
            logger.warning(f"OrderManager: Missing symbol. {context_msg}")

    def create_slice_payload(self, order_payload, qty, price, trigger_price, side):
        """
        Utility to create a sliced order payload for split_and_place_order.
        """
        return order_payload.copy(update={
            'quantity': qty,
            'price': price,
            'trigger_price': trigger_price,
            'side': side
        })

    async def _insert_broker_execution(self, session, parent_order_id, broker_name, response, side=ExecutionSide.ENTRY.value, action=None):
        try:
            from algosat.core.dbschema import broker_executions
            broker_id = response.get("broker_id")
            if broker_id is None:
                broker_id = await self._get_broker_id(broker_name)
            order_id = response.get("order_id")
            order_message = response.get("order_message")
            status_val = response.get("status", "FAILED")
            
            # Convert boolean status to proper string status
            if isinstance(status_val, bool):
                status_val = "FAILED" if status_val is False else "PENDING"
                logger.warning(f"OrderManager: Converted boolean status to string: {response.get('status')} -> {status_val} for broker_name={broker_name}")
            
            product_type = response.get("product_type")
            order_type = response.get("order_type")
            exec_price = response.get("execPrice", 0.0)
            exec_quantity = response.get("execQuantity", 0)
            action_val = action or response.get("side", "BUY")
            broker_exec_data = self.build_broker_exec_data(
                parent_order_id=parent_order_id,
                broker_id=broker_id,
                broker_order_id=order_id,
                side=side,
                action=action_val,
                status=status_val,
                executed_quantity=exec_quantity,
                execution_price=exec_price,
                product_type=product_type,
                order_type=order_type,
                order_messages=order_message,
                raw_execution_data=response
            )
            await session.execute(broker_executions.insert().values(**broker_exec_data))
        except Exception as e:
            logger.error(f"_insert_broker_execution failed for broker_name={broker_name}, parent_order_id={parent_order_id}: {e}", exc_info=True)

    async def _insert_exit_broker_execution(self, session, *, parent_order_id, broker_id, broker_order_id, side, status, executed_quantity, execution_price, product_type, order_type, order_messages, symbol, execution_time, notes, action=None, exit_reason=None):
        """
        Helper to build and insert a broker_executions row for EXIT/cancel actions.
        """
        from algosat.core.dbschema import broker_executions
        broker_exec_data = self.build_broker_exec_data(
            parent_order_id=parent_order_id,
            broker_id=broker_id,
            broker_order_id=broker_order_id,
            side=side,
            status=status,
            executed_quantity=executed_quantity,
            execution_price=execution_price,
            product_type=product_type,
            order_type=order_type,
            order_messages=order_messages,
            action=action,
            raw_execution_data=None,
            symbol=symbol,
            execution_time=execution_time,
            notes=notes
        )
        await session.execute(broker_executions.insert().values(**broker_exec_data))


    async def exit_all_orders(self, exit_reason: str = None, strategy_id: int = None):
        """
        Exit all open orders by querying the orders table for orders with open statuses
        and calling exit_order for each of them.
        
        Args:
            exit_reason: Optional reason for exiting all orders
            strategy_id: Optional strategy ID to filter orders by. If provided, only orders 
                        belonging to this strategy will be exited.
        """
        from algosat.core.db import AsyncSessionLocal, get_orders_by_strategy_id
        from algosat.core.dbschema import orders
        from sqlalchemy import select
        
        # Define open order statuses
        open_statuses = [
            "OPEN",
            'AWAITING_ENTRY',
            'PENDING', 
            # 'PARTIALLY_FILLED',
            # 'PARTIAL',
            # 'FILLED'  # Include FILLED as they may need to be exited
        ]
        
        async with AsyncSessionLocal() as session:
            if strategy_id:
                # Query for open orders filtered by strategy_id
                open_orders = await get_orders_by_strategy_id(
                    session=session,
                    strategy_id=strategy_id,
                    status_filter=open_statuses
                )
                filter_desc = f" for strategy {strategy_id}"
            else:
                # Query for all open orders
                stmt = select(orders).where(orders.c.status.in_(open_statuses))
                result = await session.execute(stmt)
                open_orders = [dict(row._mapping) for row in result.fetchall()]
                filter_desc = ""
            
            if not open_orders:
                logger.info(f"OrderManager: No open orders found to exit{filter_desc}.")
                return
            
            logger.info(f"OrderManager: Found {len(open_orders)} open orders to exit{filter_desc}. Reason: {exit_reason}")
            
            # Exit each order
            for order in open_orders:
                order_id = order['id']
                order_status = order['status']
                symbol = order.get('strike_symbol') or order.get('symbol', 'Unknown')
                
                try:
                    logger.info(f"OrderManager: Exiting order {order_id} (symbol={symbol}, status={order_status})")
                    await self.exit_order(
                        parent_order_id=order_id,
                        exit_reason=exit_reason or "Exit all orders requested"
                    )
                    logger.info(f"OrderManager: Successfully initiated exit for order {order_id}")
                except Exception as e:
                    logger.error(f"OrderManager: Failed to exit order {order_id}: {e}", exc_info=True)
                    continue
            
            logger.info(f"OrderManager: Completed exit_all_orders for {len(open_orders)} orders{filter_desc}")

    async def insert_granular_execution(
        self,
        parent_order_id: int,
        broker_id: int,
        broker_order_id: str,
        side: ExecutionSide,
        execution_price: float,
        executed_quantity: int,
        symbol: str = None,
        execution_time: datetime = None,
        execution_id: str = None,
        is_partial_fill: bool = False,
        sequence_number: int = None,
        order_type: str = None,
        notes: str = None,
        raw_execution_data: dict = None
    ):
        """
        Insert a granular execution record for each actual fill/execution.
        This is the new method for tracking individual executions.
        
        Args:
            parent_order_id: ID from orders table
            broker_id: ID from broker_credentials table
            broker_order_id: Single broker order ID for this execution
            side: ExecutionSide.ENTRY or ExecutionSide.EXIT
            execution_price: Actual traded price
            executed_quantity: Actual executed quantity
            symbol: Symbol for this execution (useful for multi-symbol strategies)
            execution_time: When the execution happened
            execution_id: Broker's trade/execution ID if available
            is_partial_fill: True if this was a partial fill
            sequence_number: For ordering multiple executions
            order_type: MARKET, LIMIT, SL, etc.
            notes: Additional notes (e.g., "BO SL leg", "Manual exit")
            raw_execution_data: Complete broker response
        """
        # Input validation
        if not isinstance(parent_order_id, int) or parent_order_id <= 0:
            raise ValueError("parent_order_id must be a positive integer")
        
        if not isinstance(broker_id, int) or broker_id <= 0:
            raise ValueError("broker_id must be a positive integer")
        
        if not broker_order_id or not isinstance(broker_order_id, str):
            raise ValueError("broker_order_id must be a non-empty string")
        
        if not isinstance(side, ExecutionSide):
            raise ValueError("side must be an ExecutionSide enum")
        
        if not isinstance(execution_price, (int, float)) or execution_price <= 0:
            raise ValueError("execution_price must be a positive number")
        
        if not isinstance(executed_quantity, int) or executed_quantity <= 0:
            raise ValueError("executed_quantity must be a positive integer")
        
        from algosat.core.dbschema import broker_executions
        
        execution_data = {
            "parent_order_id": parent_order_id,
            "broker_id": broker_id,
            "broker_order_id": broker_order_id,
            "side": side.value if isinstance(side, ExecutionSide) else side,
            "execution_price": float(execution_price),
            "executed_quantity": int(executed_quantity),
            "symbol": symbol,
            "execution_time": execution_time or datetime.utcnow(),
            "execution_id": execution_id,
            "is_partial_fill": bool(is_partial_fill),
            "sequence_number": sequence_number,
            "order_type": order_type,
            "notes": notes,
            "status": "FILLED",  # Default status for successful executions
            "raw_execution_data": raw_execution_data
        }
        
        try:
            async with AsyncSessionLocal() as session:
                await session.execute(broker_executions.insert().values(**execution_data))
                await session.commit()
                logger.info(f"Recorded {side.value} execution: order_id={broker_order_id}, price={execution_price}, qty={executed_quantity}")
        except Exception as e:
            logger.error(f"Failed to insert granular execution: {e}", exc_info=True)
            raise

    async def get_granular_executions(self, parent_order_id: int, side: ExecutionSide = None):
        """
        Get all granular executions for a logical order.
        
        Args:
            parent_order_id: ID from orders table
            side: Optional filter by ExecutionSide.ENTRY or ExecutionSide.EXIT
            
        Returns:
            List of execution records
        """
        from algosat.core.dbschema import broker_executions
        from sqlalchemy import select, and_
        
        async with AsyncSessionLocal() as session:
            conditions = [broker_executions.c.parent_order_id == parent_order_id]
            if side:
                conditions.append(broker_executions.c.side == side.value)
            
            stmt = select(broker_executions).where(and_(*conditions)).order_by(
                broker_executions.c.execution_time,
                broker_executions.c.sequence_number
            )
            result = await session.execute(stmt)
            return [dict(row._mapping) for row in result.fetchall()]

    async def calculate_vwap_for_executions(self, executions: List[dict]) -> tuple[float, int]:
        """
        Calculate Volume Weighted Average Price for a list of executions.
        
        Args:
            executions: List of execution records
            
        Returns:
            tuple: (vwap_price, total_quantity)
        """
        if not executions:
            return 0.0, 0
        
        total_value = 0.0
        total_quantity = 0
        
        for execution in executions:
            price = float(execution['execution_price'])
            qty = int(execution['executed_quantity'])
            total_value += price * qty
            total_quantity += qty
        
        vwap = total_value / total_quantity if total_quantity > 0 else 0.0
        return vwap, total_quantity

    async def update_order_aggregated_prices(self, parent_order_id: int):
        """
        Update the orders table with aggregated ENTRY and EXIT prices based on granular executions.
        This should be called whenever new executions are recorded.
        """
        # Get all executions for this order
        entry_executions = await self.get_granular_executions(parent_order_id, ExecutionSide.ENTRY)
        exit_executions = await self.get_granular_executions(parent_order_id, ExecutionSide.EXIT)
        
        # Calculate VWAP for entry and exit
        entry_vwap, entry_qty = await self.calculate_vwap_for_executions(entry_executions)
        exit_vwap, exit_qty = await self.calculate_vwap_for_executions(exit_executions)
        
        # Calculate P&L
        pnl = 0.0
        if entry_vwap > 0 and exit_vwap > 0:
            # For now, assume BUY side (can be enhanced to read actual side from orders table)
            pnl = (exit_vwap - entry_vwap) * min(entry_qty, exit_qty)
        
        # Update orders table
        from algosat.core.db import update_rows_in_table
        from algosat.core.dbschema import orders
        
        update_values = {}
        if entry_vwap > 0:
            update_values["entry_price"] = entry_vwap
        if exit_vwap > 0:
            update_values["exit_price"] = exit_vwap
            update_values["pnl"] = pnl
            # If we have exit executions, update status
            if exit_qty >= entry_qty:
                update_values["status"] = "FILLED"
            else:
                update_values["status"] = "PARTIALLY_FILLED"
        
        if update_values:
            async with AsyncSessionLocal() as session:
                await update_rows_in_table(
                    target_table=orders,
                    condition=orders.c.id == parent_order_id,
                    new_values=update_values
                )
                await session.commit()
                logger.info(f"Updated order {parent_order_id} aggregated prices: entry_vwap={entry_vwap}, exit_vwap={exit_vwap}, pnl={pnl}")

    async def _get_broker_id(self, broker_name):
        async with AsyncSessionLocal() as sess:
            broker_row = await get_broker_by_name(sess, broker_name)
            if broker_row is None:
                logger.warning(f"OrderManager: Could not find broker_id for broker_name={broker_name}")
            return broker_row["id"] if broker_row else None

    async def get_order_status(self, order_id):
        """
        Fetch the order status from the DB for a given order_id.
        """
        from algosat.core.db import AsyncSessionLocal, get_order_by_id # Local import
        async with AsyncSessionLocal() as session:
            order = await get_order_by_id(session, order_id)
            return order.get("status") if order else None

    async def update_order_status_in_db(self, order_id, status):
        """
        Update the order status in the DB for a given order_id.
        """
        from algosat.core.db import AsyncSessionLocal, update_rows_in_table # Local import
        from algosat.core.dbschema import orders # Local import
        async with AsyncSessionLocal() as session:
            await update_rows_in_table(
                target_table=orders,
                condition=orders.c.id == order_id,
                new_values={"status": status.value if hasattr(status, 'value') else str(status)}
            )
            logger.debug(f"Order {order_id} status updated to {status} in DB.")

    async def update_order_stop_loss_in_db(self, order_id: int, stop_loss: float):
        """
        Update the stop_loss value for an order in the DB.
        """
        from algosat.core.db import AsyncSessionLocal, update_rows_in_table
        from algosat.core.dbschema import orders
        async with AsyncSessionLocal() as session:
            await update_rows_in_table(
                target_table=orders,
                condition=orders.c.id == order_id,
                new_values={"stop_loss": stop_loss}
            )
            logger.debug(f"Order {order_id} stop_loss updated to {stop_loss} in DB.")

    async def update_order_pnl_in_db(self, order_id: int, pnl: float):
        """
        Update the PnL value for an order in the DB.
        """
        from algosat.core.db import AsyncSessionLocal, update_rows_in_table
        from algosat.core.dbschema import orders
        try:
            logger.info(f"OrderManager: Starting PnL update for order_id={order_id}, pnl={pnl}")
            await update_rows_in_table(
                target_table=orders,
                condition=orders.c.id == order_id,
                new_values={"pnl": pnl}
            )
            logger.info(f"OrderManager: Successfully updated PnL for order_id={order_id} to {pnl} in DB")
        except Exception as e:
            logger.error(f"OrderManager: Error updating PnL for order_id={order_id}: {e}", exc_info=True)
            raise

    async def update_order_exit_details_in_db(self, order_id: int, exit_price: float, exit_time, pnl: float, status: str):
        """
        Update exit details (exit_price, exit_time, PnL, status) for an order in the DB.
        """
        from algosat.core.db import AsyncSessionLocal, update_rows_in_table
        from algosat.core.dbschema import orders
        async with AsyncSessionLocal() as session:
            await update_rows_in_table(
                target_table=orders,
                condition=orders.c.id == order_id,
                new_values={
                    "exit_price": exit_price,
                    "exit_time": exit_time,
                    "pnl": pnl,
                    "status": status
                }
            )
            logger.debug(f"Order {order_id} exit details updated: exit_price={exit_price}, pnl={pnl}, status={status}")

    async def get_all_broker_order_details(self) -> dict:
        """
        Fetch and normalize order details from all trade-enabled brokers via BrokerManager.
        Returns a dict: broker_name -> list of normalized order dicts (empty list if no orders).
        Assumes broker_manager.get_all_broker_order_details() returns a list of orders per broker.
        """
        broker_orders_raw = await self.broker_manager.get_all_broker_order_details()
        normalized_orders_by_broker = {}
        broker_name_to_id = {}
        async def get_broker_id_cached(broker_name):
            if broker_name in broker_name_to_id:
                return broker_name_to_id[broker_name]
            broker_id = await self._get_broker_id(broker_name)
            broker_name_to_id[broker_name] = broker_id
            return broker_id
        for broker_name, orders in broker_orders_raw.items():
            broker_id = await get_broker_id_cached(broker_name)
            normalized_orders = []
            if not isinstance(orders, list):
                # Defensive: if not a list, skip
                continue
            for o in orders:
                # Fyers normalization
                if broker_name.lower() == "fyers":
                    status = FYERS_STATUS_MAP.get(o.get("status"), str(o.get("status")))
                    order_type = FYERS_ORDER_TYPE_MAP.get(o.get("type"), o.get("type"))
                    normalized_orders.append({
                        "broker_name": broker_name,
                        "broker_id": broker_id,
                        "order_id": o.get("id"),
                        "status": status,
                        "symbol": o.get("symbol"),
                        "qty": o.get("qty", 0),
                        "executed_quantity": o.get("filledQty", 0),
                        "exec_price": o.get("tradedPrice", 0),
                        "product_type": o.get("productType"),
                        "order_type": order_type,
                        # "raw": o
                    })
                # Zerodha normalization
                elif broker_name.lower() == "zerodha":
                    status = ZERODHA_STATUS_MAP.get(o.get("status"), o.get("status"))
                    normalized_orders.append({
                        "broker_name": broker_name,
                        "broker_id": broker_id,
                        "order_id": o.get("order_id"),
                        "status": status,
                        "symbol": o.get("tradingsymbol"),
                        "quantity": o.get("quantity", 0),
                        "executed_quantity": o.get("filled_quantity", 0),
                        "exec_price": o.get("average_price", 0),
                        "product_type": o.get("product"),
                        "order_type": o.get("order_type"),
                        # "raw": o
                    })
                # Fallback normalization for other brokers
                else:
                    normalized_orders.append({
                        "broker_name": broker_name,
                        "broker_id": broker_id,
                        "order_id": o.get("order_id") or o.get("id"),
                        "status": o.get("status"),
                        "symbol": o.get("symbol") or o.get("tradingsymbol"),
                        "raw": o
                    })
            normalized_orders_by_broker[broker_name] = normalized_orders
        return normalized_orders_by_broker
    
    async def update_broker_executions_batch(
        self,
        session,
        updates: List[dict],
        logger_override=None,
    ):
        """
        Batch update broker_executions for a logical order in a single session/commit.
        Each update dict should contain:
            - id: broker_executions.id (PK)
            - update_fields: dict of fields to update (status, execution_price, etc.)
            - prev_status: previous status (from DB) for execution_time logic
        If status changes from AWAITING_ENTRY to FILLED/PARTIAL, set execution_time if not already set.
        """
        from algosat.core.dbschema import broker_executions
        import logging
        _logger = logger_override or logger
        now = datetime.utcnow()
        for upd in updates:
            be_id = upd.get("id")
            update_fields = dict(upd.get("update_fields", {}))
            prev_status = upd.get("prev_status")
            new_status = update_fields.get("status")
            # Only set execution_time if status transitions from AWAITING_ENTRY to FILLED/PARTIAL
            # (and execution_time not already set)
            set_execution_time = False
            # Accept both string and enum
            prev_stat = prev_status.value if hasattr(prev_status, "value") else prev_status
            new_stat = new_status.value if hasattr(new_status, "value") else new_status
            if (
                prev_stat == "AWAITING_ENTRY"
                and new_stat in ("FILLED", "PARTIAL")
            ):
                set_execution_time = True
            if set_execution_time and "execution_time" not in update_fields:
                update_fields["execution_time"] = now
            # Logging
            _logger.info(
                f"[OrderManager] Batch updating broker_execution id={be_id}: {update_fields} (prev_status={prev_stat}, new_status={new_stat})"
            )
            await session.execute(
                broker_executions.update().where(broker_executions.c.id == be_id).values(**update_fields)
            )
        await session.commit()
        # Metric stub: log number of updates for future expansion
        _logger.info(f"[OrderManager] Batch updated {len(updates)} broker_executions in one commit.")

    # Example usage for batch update (for order_monitor refactor)
    async def batch_update_monitor_cycle(self, logical_order_id: int, updates: List[dict]):
        """
        Example method for batch updating broker_executions for a logical order.
        Each update dict should contain:
            - id: broker_executions.id
            - update_fields: dict of fields to update (status, execution_price, etc.)
            - prev_status: previous status (from DB)
        """
        async with AsyncSessionLocal() as session:
            await self.update_broker_executions_batch(session, updates)

    async def batch_update_broker_exec_statuses_in_db(self, batch_updates: list[dict]):
        """
        Batch update broker_executions table for monitor. Each dict in batch_updates should have:
            - broker_exec_id: int
            - status: str
            - execQuantity, execPrice, order_type, product_type, execution_time (optional)
        Only updates fields present in each dict. Logs errors for individual failures, continues with rest.
        """
        from algosat.core.dbschema import broker_executions
        from sqlalchemy import update
        from algosat.core.db import AsyncSessionLocal
        import traceback
        success_count = 0
        fail_count = 0
        async with AsyncSessionLocal() as session:
            for upd in batch_updates:
                be_id = upd.get('broker_exec_id')
                update_fields = {}
                for k in ['status', 'execQuantity', 'execPrice', 'order_type', 'product_type', 'execution_time']:
                    v = upd.get(k)
                    if v is not None:
                        # Map execQuantity/execPrice to DB columns
                        if k == 'execQuantity':
                            update_fields['executed_quantity'] = v
                        elif k == 'execPrice':
                            update_fields['execution_price'] = v
                        else:
                            update_fields[k] = v
                try:
                    if update_fields:
                        await session.execute(
                            update(broker_executions).where(broker_executions.c.id == be_id).values(**update_fields)
                        )
                        success_count += 1
                except Exception as e:
                    logger.error(f"Batch update failed for broker_exec_id={be_id}: {e}\n{traceback.format_exc()}")
                    fail_count += 1
            await session.commit()
        logger.info(f"[OrderManager] Batch broker_exec status update: success={success_count}, failed={fail_count}")

    async def update_broker_exec_status_in_db(self, broker_exec_id, status, executed_quantity=None, quantity=None, execution_price=None, order_type=None, product_type=None, execution_time=None, symbol=None):
        """
        Update the status and optionally execution details of a broker execution in the broker_executions table by broker_exec_id.
        Handles additional fields: execution_time, symbol.
        """
        from algosat.core.db import AsyncSessionLocal, update_rows_in_table
        from algosat.core.dbschema import broker_executions
        update_fields = {"status": status.value if hasattr(status, 'value') else str(status)}
        if executed_quantity is not None:
            update_fields["executed_quantity"] = executed_quantity
            
        if quantity is not None:
            update_fields["quantity"] = quantity

        if execution_price is not None:
            update_fields["execution_price"] = execution_price
        if order_type is not None:
            update_fields["order_type"] = order_type
        if product_type is not None:
            update_fields["product_type"] = product_type
        if execution_time is not None:
            update_fields["execution_time"] = execution_time
        if symbol is not None:
            update_fields["symbol"] = symbol
        logger.info(f"Updating broker execution {broker_exec_id} with fields: {update_fields}")
        async with AsyncSessionLocal() as session:
            await update_rows_in_table(
                target_table=broker_executions,
                condition=broker_executions.c.id == broker_exec_id,
                new_values=update_fields
            )
            logger.debug(f"Broker execution {broker_exec_id} updated: {update_fields}")

    @staticmethod
    def _get_cache_lookup_order_id(broker_order_id, broker_name, product_type):
        """
        Helper to determine cache key for broker order id (handles Fyers intraday hack).
        """
        if (
            product_type
            and product_type.lower() == 'intraday'
            and broker_name
            and broker_name.lower() == 'fyers'
            and broker_order_id
        ):
            return f"{broker_order_id}-BO-1"
        return broker_order_id

    async def exit_order(self, parent_order_id: int, exit_reason: str = None, ltp: float = None):
        """
        Standardized exit: For a logical order, fetch all broker_executions. For each FILLED row, call exit_order. For PARTIALLY_FILLED/PARTIAL, call exit_order then cancel_order. For AWAITING_ENTRY/PENDING, call cancel_order. For REJECTED/FAILED, do nothing.
        After exit/cancel, insert a new broker_executions row with side=EXIT, exit price as LTP (passed in), and update exit_time.
        ltp: If provided, use as exit price. If not provided, will fetch current LTP from the market.
        """
        from algosat.core.db import AsyncSessionLocal, get_broker_executions_for_order, get_order_by_id
        async with AsyncSessionLocal() as session:
            broker_execs = await get_broker_executions_for_order(session, parent_order_id)
            order_row = await get_order_by_id(session, parent_order_id)
            logical_symbol = order_row.get('strike_symbol') # or order_row.get('symbol') if order_row else None
            order_side = order_row.get('side') if order_row else None
            
            # If LTP is not provided, fetch it from the market
            if ltp is None and logical_symbol:
                try:
                    from algosat.core.data_manager import DataManager
                    data_manager = DataManager(broker_manager=self.broker_manager)
                    await data_manager.ensure_broker()
                    
                    ltp_response = await data_manager.get_ltp(logical_symbol)
                    if isinstance(ltp_response, dict):
                        ltp = ltp_response.get(logical_symbol)
                    else:
                        ltp = ltp_response
                    
                    if ltp is not None:
                        logger.info(f"OrderManager: Fetched LTP for symbol {logical_symbol}: {ltp}")
                    else:
                        logger.warning(f"OrderManager: Could not fetch LTP for symbol {logical_symbol}")
                        ltp = 0.0
                except Exception as e:
                    logger.error(f"OrderManager: Error fetching LTP for symbol {logical_symbol}: {e}")
                    ltp = 0.0
            elif ltp is None:
                logger.warning(f"OrderManager: No LTP provided and no symbol available for order {parent_order_id}")
                ltp = 0.0
            
            if not broker_execs:
                logger.warning(f"OrderManager: No broker executions found for parent_order_id={parent_order_id} in exit_order.")
                return
            for be in broker_execs:
                status = (be.get('status') or '').upper()
                broker_id = be.get('broker_id')
                broker_order_id = be.get('broker_order_id')
                symbol = be.get('symbol') or logical_symbol
                product_type = be.get('product_type')
                self.validate_broker_fields(broker_id, symbol, context_msg=f"exit_order (parent_order_id={parent_order_id})")
                if broker_id is None or broker_order_id is None:
                    logger.error(f"OrderManager: Missing broker_id or broker_order_id in broker_execution for parent_order_id={parent_order_id}")
                    continue
                broker_order_id = self._get_cache_lookup_order_id(broker_order_id, be.get('broker_name'), product_type)
                logger.info(f"OrderManager: Processing broker_execution id={be.get('id')} (broker_id={broker_id}, broker_order_id={broker_order_id}, symbol={symbol}, product_type={product_type}, status={status})")
                # Action based on status
                if status in ('REJECTED', 'FAILED'):
                    logger.info(f"OrderManager: Skipping broker_execution id={be.get('id')} with status={status} (no action needed).")
                    # continue
                try:
                    import datetime
                    orig_side = (be.get('action') or '').upper()
                    exit_time = datetime.datetime.now(datetime.timezone.utc)
                    if orig_side == 'BUY':
                            exit_action = 'SELL'
                    elif orig_side == 'SELL':
                        exit_action = 'BUY'
                    else:
                        exit_action = ''
                    if status == 'FILLED':
                        logger.info(f"OrderManager: Initiating exit for broker_execution id={be.get('id')} (broker_id={broker_id}, broker_order_id={broker_order_id}, symbol={symbol}, product_type={product_type}, exit_reason={exit_reason})")
                        exit_resp = await self.broker_manager.exit_order(
                            broker_id,
                            broker_order_id,
                            symbol=symbol,
                            product_type=product_type,
                            exit_reason=exit_reason,
                            side=order_side
                        )
                        
                        logger.info(f"OrderManager: Exit order sent to broker_id={broker_id} for broker_order_id={broker_order_id}. Response: {exit_resp}")
                        await self._insert_exit_broker_execution(
                            session,
                            parent_order_id=parent_order_id,
                            broker_id=broker_id,
                            broker_order_id=broker_order_id,
                            side='EXIT',
                            status='FILLED',
                            action = exit_action,
                            executed_quantity=be.get('executed_quantity', 0),
                            execution_price=ltp or 0.0,
                            product_type=product_type,
                            order_type='MARKET',
                            order_messages=f"Exit order placed. Reason: {exit_reason}",
                            symbol=symbol,
                            execution_time=exit_time,
                            notes=f"Auto exit via OrderManager. Reason: {exit_reason}"
                        )
                    elif status in ('PARTIALLY_FILLED', 'PARTIAL'):
                        logger.info(f"OrderManager: Initiating exit for PARTIALLY_FILLED broker_execution id={be.get('id')} (broker_id={broker_id}, broker_order_id={broker_order_id}, symbol={symbol}, product_type={product_type}, exit_reason={exit_reason})")
                        exit_resp = await self.broker_manager.exit_order(
                            broker_id,
                            broker_order_id,
                            symbol=symbol,
                            product_type=product_type,
                            exit_reason=exit_reason
                        )
                        logger.info(f"OrderManager: Exit order sent to broker_id={broker_id} for broker_order_id={broker_order_id}. Response: {exit_resp}")
                        logger.info(f"OrderManager: Now also sending cancel for PARTIALLY_FILLED broker_execution id={be.get('id')}")
                        cancel_resp = await self.broker_manager.cancel_order(
                            broker_id,
                            broker_order_id,
                            symbol=symbol,
                            product_type=product_type,
                            exit_reason=f"Exit requested for PARTIALLY_FILLED order"
                        )
                        logger.info(f"OrderManager: Cancel order sent to broker_id={broker_id} for broker_order_id={broker_order_id}. Response: {cancel_resp}")
                        await self._insert_exit_broker_execution(
                            session,
                            parent_order_id=parent_order_id,
                            broker_id=broker_id,
                            broker_order_id=broker_order_id,
                            action = exit_action,
                            side='EXIT',
                            status='FILLED',
                            executed_quantity=be.get('executed_quantity', 0),
                            execution_price=ltp or 0.0,
                            product_type=product_type,
                            order_type='MARKET',
                            order_messages=f"Exit and cancel placed for PARTIALLY_FILLED. Reason: {exit_reason}",
                            symbol=symbol,
                            execution_time=exit_time,
                            notes=f"Auto exit+cancel via OrderManager. Reason: {exit_reason}"
                        )
                    elif status in ('AWAITING_ENTRY', 'PENDING'):
                        logger.info(f"OrderManager: Initiating cancel for broker_execution id={be.get('id')} (broker_id={broker_id}, broker_order_id={broker_order_id}, symbol={symbol}, product_type={product_type}, exit_reason={exit_reason})")
                        await self.broker_manager.cancel_order(
                            broker_id,
                            broker_order_id,
                            symbol=symbol,
                            product_type=product_type,
                            cancel_reason=f"Exit requested but status was {status}"
                        )
                        logger.info(f"OrderManager: Cancel order sent to broker_id={broker_id} for broker_order_id={broker_order_id}. Response: {cancel_resp}")
                        await self.update_broker_exec_status_in_db(
                            broker_exec_id=be.get('id'),
                            status='CANCELLED'
                        )
                except Exception as e:
                    logger.error(f"OrderManager: Error exiting/cancelling order for broker_id={broker_id}, broker_order_id={broker_order_id}: {e}")
            
            # # After processing all broker executions, update the main order status to CLOSED
            # # and set exit_price and exit_time
            # try:
            #     import datetime
            #     exit_time = datetime.datetime.now(datetime.timezone.utc)
            #     exit_price = ltp or 0.0
                
            #     # Calculate PnL if we have the necessary data
            #     pnl = 0.0
            #     if order_row:
            #         entry_price = order_row.get('entry_price')
            #         executed_quantity = order_row.get('executed_quantity')
            #         side = order_row.get('side')
                    
            #         if all(x is not None for x in [entry_price, executed_quantity, side, exit_price]):
            #             if side == 'BUY':
            #                 pnl = (exit_price - entry_price) * executed_quantity
            #             elif side == 'SELL':
            #                 pnl = (entry_price - exit_price) * executed_quantity
            #             logger.info(f"OrderManager: Calculated PnL for order {parent_order_id}: {pnl}")
            #         else:
            #             logger.warning(f"OrderManager: Cannot calculate PnL for order {parent_order_id} - missing data")
                
            #     # Update the main order with exit details
            #     await self.update_order_exit_details_in_db(
            #         order_id=parent_order_id,
            #         exit_price=exit_price,
            #         exit_time=exit_time,
            #         pnl=pnl,
            #         status="CLOSED"
            #     )
                
            #     logger.info(f"OrderManager: Updated main order {parent_order_id} status to CLOSED with exit_price={exit_price}, exit_time={exit_time}, pnl={pnl}")
                
            # except Exception as e:
                # logger.error(f"OrderManager: Error updating main order exit details for order {parent_order_id}: {e}")
            
            await session.commit()



    async def insert_broker_execution(
        self,
        parent_order_id: int,
        broker_id: int,
        side: str,
        execution_price: float = 0.0,
        executed_quantity: int = 0,
        execution_time: datetime = None,
        symbol: str = None,
        product_type: str = None,
        order_type: str = None,
        notes: str = None,
        status: str = "FILLED",
        broker_order_id: str = None,
        action: str = None,
        order_messages: str = None,
        raw_execution_data: dict = None
    ):
        """
        Public method to insert an ENTRY or EXIT row in broker_executions.
        This can be called from outside OrderManager (e.g., from OrderMonitor).
        """
        from algosat.core.dbschema import broker_executions
        from algosat.core.db import AsyncSessionLocal
        import datetime

        execution_time = execution_time or datetime.datetime.utcnow()

        # Ensure all required fields for broker_executions table are present
        broker_exec_data = {
            "parent_order_id": parent_order_id,
            "broker_id": broker_id,
            "broker_order_id": broker_order_id,
            "side": side,
            "status": status,
            "executed_quantity": executed_quantity,
            "execution_price": execution_price,
            "product_type": product_type,
            "order_type": order_type,
            "order_messages": order_messages,
            "raw_execution_data": raw_execution_data,
            "symbol": symbol,
            "execution_time": execution_time,
            "notes": notes,
            "action": action,
        }
        # Fill missing fields with defaults if necessary
        if broker_exec_data["side"] is None:
            broker_exec_data["side"] = "NA"
        if broker_exec_data["status"] is None:
            broker_exec_data["status"] = "UNKNOWN"
        if broker_exec_data["executed_quantity"] is None:
            broker_exec_data["executed_quantity"] = 0
        if broker_exec_data["execution_price"] is None:
            broker_exec_data["execution_price"] = 0.0
        if broker_exec_data["execution_time"] is None:
            broker_exec_data["execution_time"] = datetime.datetime.utcnow()
        # Add any other required fields with defaults as needed
        async with AsyncSessionLocal() as session:
            await session.execute(broker_executions.insert().values(**broker_exec_data))
            await session.commit()

    async def update_broker_execution_price(self, broker_exec_id, execution_price):
        """
        Update only the execution_price for a broker_execution row.
        """
        try:
            from algosat.core.db import AsyncSessionLocal, update_rows_in_table
            from algosat.core.dbschema import broker_executions
            async with AsyncSessionLocal() as session:
                await update_rows_in_table(
                    target_table=broker_executions,
                    condition=broker_executions.c.id == broker_exec_id,
                    new_values={"execution_price": execution_price}
                )
                await session.commit()
        except Exception as e:
            logger.error(f"OrderMonitor: Error updating execution_price for broker_execution id={broker_exec_id}: {e}")
