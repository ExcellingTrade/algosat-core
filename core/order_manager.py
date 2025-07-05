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
            max_nse_qty = config.trade.get('max_nse_qty') or config.trade.get('max_nse_qtty')
        if max_nse_qty and order_payload.quantity > max_nse_qty:
            return await self.split_and_place_order(config, order_payload, max_nse_qty, strategy_name)
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
            broker_manager = self.broker_manager
            broker_responses = await broker_manager.place_order(order_payload, strategy_name=strategy_name)
            # 3. Insert broker_executions rows
            for broker_name, response in broker_responses.items():
                await self._insert_broker_execution(session, order_id, broker_name, response)
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
    ) -> Dict[str, Any]:
        """
        Split the order into chunks if the quantity exceeds max_nse_qty and place each chunk as a separate order.
        Each broker gets a single broker_executions entry with all order_ids from the splits.
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
        # Aggregate order_ids and messages per broker
        broker_order_ids_map = {}  # broker_name -> list of order_ids
        broker_order_messages_map = {}  # broker_name -> list of messages
        broker_status_map = {}  # broker_name -> last status
        broker_raw_responses = {}  # broker_name -> list of raw responses
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
                slice_update = {
                    'quantity': qty,
                    'price': current_price,
                    'trigger_price': (current_price - trigger_price_diff) if order_payload.side == Side.BUY else (current_price + trigger_price_diff),
                    'side': "ENTRY"
                }
                slice_payload = order_payload.copy(update=slice_update)
                broker_manager = self.broker_manager
                broker_responses = await broker_manager.place_order(slice_payload, strategy_name=strategy_name)
                for broker_name, response in broker_responses.items():
                    # Assume response['order_id'] is a single string (not a list)
                    order_id = response.get('order_id') or (response.get('order_ids')[0] if isinstance(response.get('order_ids'), list) else response.get('order_ids'))
                    if order_id:
                        broker_order_ids_map.setdefault(broker_name, []).append(order_id)
                    # Aggregate messages
                    order_message = response.get('order_messages')
                    if order_message:
                        broker_order_messages_map.setdefault(broker_name, []).append(order_message)
                    # Track last status and raw response for this broker
                    broker_status_map[broker_name] = response.get('status')
                    broker_raw_responses.setdefault(broker_name, []).append(response)
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
            # After all slices, insert a single broker_executions row per broker
            for broker_name in broker_order_ids_map:
                # Consolidate raw_responses as a dict: order_id -> response
                raw_responses_dict = {}
                for idx, order_id in enumerate(broker_order_ids_map[broker_name]):
                    # Try to match order_id to response in order (fallback to idx)
                    responses_for_broker = broker_raw_responses.get(broker_name, [])
                    if idx < len(responses_for_broker):
                        raw_responses_dict[order_id] = responses_for_broker[idx]
                    else:
                        raw_responses_dict[order_id] = None
                await self._insert_broker_execution(
                    session,
                    parent_order_id,
                    broker_name,
                    {
                        'order_ids': broker_order_ids_map[broker_name],
                        'order_messages': broker_order_messages_map.get(broker_name, []),
                        'status': broker_status_map.get(broker_name, 'FAILED'),
                        'raw_response': raw_responses_dict,
                    }
                )
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
                "qty": order_payload.quantity,
            }
            inserted = await insert_order(sess, order_data)
            return inserted["id"] if inserted else None

    async def _insert_broker_execution(self, session, parent_order_id, broker_name, response):
        """
        DEPRECATED: Legacy method for backward compatibility.
        Use insert_granular_execution() for new execution tracking.
        """
        # Keep existing logic for now during migration
        from algosat.core.dbschema import broker_executions
        broker_id = response.get("broker_id")
        if broker_id is None:
            broker_id = await self._get_broker_id(broker_name)
        
        # Legacy storage - store in deprecated fields
        broker_order_ids = []
        order_ids = response.get("order_ids")
        if isinstance(order_ids, list):
            broker_order_ids = order_ids
        elif order_ids:
            broker_order_ids = [order_ids]
        
        status_val = response.get("status", "FAILED")
        if hasattr(status_val, 'value'):
            status_val = status_val.value
        
        order_messages = response.get("order_messages")
        if order_messages is not None and not isinstance(order_messages, (list, dict)):
            order_messages = [order_messages]
        
        # For backward compatibility, create a single execution record in new format
        # This is a migration helper - new code should use insert_granular_execution
        if broker_order_ids:
            first_order_id = broker_order_ids[0]
            # Extract product_type and order_type from response if present
            product_type = response.get("product_type")
            order_type = response.get("order_type")
            broker_exec_data = dict(
                parent_order_id=parent_order_id,
                broker_id=broker_id,
                broker_order_id=first_order_id,
                side=ExecutionSide.ENTRY.value,  # Default to ENTRY for legacy orders
                execution_price=0.0,  # Will be updated when actual execution is tracked
                executed_quantity=0,   # Will be updated when actual execution is tracked
                status=status_val,
                order_messages=order_messages,
                raw_execution_data=response,
                # Legacy fields
                broker_name=broker_name,
                broker_order_ids=broker_order_ids,
                raw_response=response,
                # New fields
                product_type=product_type,
                order_type=order_type,
            )
            await session.execute(broker_executions.insert().values(**broker_exec_data))

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
            return broker_row["id"] if broker_row else None

    async def get_broker_symbol(self, broker_name, symbol, instrument_type=None):
        """
        Returns the correct symbol/token for the given broker using BrokerManager.get_symbol_info.
        """
        return await self.broker_manager.get_symbol_info(broker_name, symbol, instrument_type)

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
        async with AsyncSessionLocal() as session:
            await update_rows_in_table(
                target_table=orders,
                condition=orders.c.id == order_id,
                new_values={"pnl": pnl}
            )
            logger.debug(f"Order {order_id} PnL updated to {pnl} in DB.")

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
            # Fyers: orders is a dict with 'orderBook' key
            if broker_name.lower() == "fyers" and isinstance(orders, dict) and "orderBook" in orders:
                for o in orders["orderBook"]:
                    status = FYERS_STATUS_MAP.get(o.get("status"), str(o.get("status")))
                    normalized_orders.append({
                        "broker_name": broker_name,
                        "broker_id": broker_id,
                        "order_id": o.get("id"),
                        "status": status,
                        "symbol": o.get("symbol"),
                        "raw": o
                    })
            # Zerodha: orders is a list of dicts
            elif broker_name.lower() == "zerodha" and isinstance(orders, list):
                for o in orders:
                    status = ZERODHA_STATUS_MAP.get(o.get("status"), o.get("status"))
                    normalized_orders.append({
                        "broker_name": broker_name,
                        "broker_id": broker_id,
                        "order_id": o.get("order_id"),
                        "status": status,
                        "symbol": o.get("tradingsymbol"),
                        "raw": o
                    })
            # Add more brokers as needed
            else:
                # Fallback: treat as list of dicts
                if isinstance(orders, list):
                    for o in orders:
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

    async def process_broker_order_update(
        self,
        parent_order_id: int,
        broker_name: str,
        broker_order_data: dict
    ):
        """
        Process broker order status updates and create granular execution records.
        This method should be called when polling broker order status or receiving webhooks.
        
        Args:
            parent_order_id: ID from orders table
            broker_name: Name of the broker
            broker_order_data: Broker's order/execution data
            
        Expected broker_order_data format:
        {
            "order_id": "123456",
            "status": "FILLED" | "PARTIAL" | "CANCELLED",
            "executed_qty": 100,
            "executed_price": 245.50,
            "execution_time": "2025-06-28T10:30:00Z",
            "execution_id": "E123456",
            "order_type": "MARKET",
            "symbol": "NSE:NIFTY50-25JUN25-23400-CE",
            "is_exit": false,  # true for SL/TP/manual exit orders
            "notes": "BO SL leg filled"
        }
        """
        try:
            broker_id = await self._get_broker_id(broker_name)
            if not broker_id:
                logger.error(f"Unknown broker: {broker_name}")
                return
            
            order_id = broker_order_data.get("order_id")
            status = broker_order_data.get("status", "").upper()
            executed_qty = broker_order_data.get("executed_qty", 0)
            executed_price = broker_order_data.get("executed_price", 0.0)
            
            # Skip if no execution happened
            if status not in ["FILLED", "PARTIAL"] or executed_qty <= 0:
                logger.debug(f"No execution to record for order {order_id}, status: {status}")
                return
            
            # Determine if this is ENTRY or EXIT
            is_exit = broker_order_data.get("is_exit", False)
            side = ExecutionSide.EXIT if is_exit else ExecutionSide.ENTRY
            
            # Check if we already recorded this execution (avoid duplicates)
            existing_executions = await self.get_granular_executions(parent_order_id)
            execution_id = broker_order_data.get("execution_id")
            
            # Simple duplicate check based on execution_id or order_id + qty + price
            for existing in existing_executions:
                if execution_id and existing.get("execution_id") == execution_id:
                    logger.debug(f"Execution {execution_id} already recorded, skipping")
                    return
                if (existing.get("broker_order_id") == order_id and 
                    existing.get("executed_quantity") == executed_qty and
                    abs(float(existing.get("execution_price", 0)) - executed_price) < 0.01):
                    logger.debug(f"Duplicate execution detected for order {order_id}, skipping")
                    return
            
            # Record the execution
            await self.insert_granular_execution(
                parent_order_id=parent_order_id,
                broker_id=broker_id,
                broker_order_id=order_id,
                side=side,
                execution_price=executed_price,
                executed_quantity=executed_qty,
                symbol=broker_order_data.get("symbol"),
                execution_time=broker_order_data.get("execution_time"),
                execution_id=execution_id,
                is_partial_fill=(status == "PARTIAL"),
                order_type=broker_order_data.get("order_type"),
                notes=broker_order_data.get("notes"),
                raw_execution_data=broker_order_data
            )
            
            # Update aggregated prices in orders table
            await self.update_order_aggregated_prices(parent_order_id)
            
            # Update order status based on executions
            await self.update_order_status(parent_order_id)
            
            logger.info(f"Processed {side.value} execution for order {parent_order_id}: {executed_qty}@{executed_price}")
            
        except Exception as e:
            logger.error(f"Error processing broker order update: {e}", exc_info=True)

    async def determine_order_status(self, order_id: int) -> str:
        """
        Determine the order status based on broker executions.
        
        Returns:
        - AWAITING_ENTRY: Order placed but not yet executed (all broker orders in trigger pending state)
        - OPEN: At least one broker order has been executed
        - CANCELLED: Order has been cancelled
        - CLOSED: Order is closed (exit executed)
        - FAILED: All broker orders failed
        """
        executions = await self.get_granular_executions(order_id)
        
        if not executions:
            return "AWAITING_ENTRY"
        
        # Check for any executions with EXIT side - if found, order is closed
        exit_executions = [e for e in executions if e.get('side') == 'EXIT']
        if exit_executions:
            return "CLOSED"
        
        # Check status of executions
        statuses = [e.get('status', '').upper() for e in executions]
        
        # If any execution is filled or partial, order is open
        if any(status in ['FILLED', 'PARTIAL', 'PARTIALLY_FILLED'] for status in statuses):
            return "OPEN"
        
        # If all executions are cancelled, order is cancelled
        if all(status == 'CANCELLED' for status in statuses):
            return "CANCELLED"
        
        # If all executions are failed/rejected, order is failed
        if all(status in ['FAILED', 'REJECTED'] for status in statuses):
            return "FAILED"
        
        # Default to awaiting entry for pending/trigger pending states
        return "AWAITING_ENTRY"
    
    async def update_order_status(self, order_id: int) -> None:
        """Update the order status in the database based on current executions."""
        new_status = await self.determine_order_status(order_id)
        
        async with AsyncSessionLocal() as session:
            await session.execute(
                text("UPDATE orders SET status = :status, updated_at = NOW() WHERE id = :order_id"),
                {"status": new_status, "order_id": order_id}
            )
            await session.commit()
            logger.info(f"Updated order {order_id} status to {new_status}")

    async def update_broker_exec_status_in_db(self, broker_order_id, status):
        """
        Update the status of a broker execution in the broker_executions table by broker_order_id.
        """
        from algosat.core.db import update_broker_exec_status_in_db as db_update_broker_exec_status_in_db
        await db_update_broker_exec_status_in_db(broker_order_id, status)

    async def exit_order(self, parent_order_id: int, exit_reason: str = None, ltp: float = None):
        """
        Standardized exit: For a logical order, fetch all broker_executions. For each FILLED/PARTIALLY_FILLED row,
        call BrokerManager.exit_order with minimal identifiers. All broker-specific logic is handled in broker wrappers.
        Optionally pass exit_reason for logging or broker-specific use.
        After exit, insert a new broker_executions row with side=EXIT, exit price as LTP (passed in), and update exit_time.
        ltp: If provided, use as exit price. If not, will be 0.0 in broker_executions row.
        """
        from algosat.core.db import AsyncSessionLocal, get_broker_executions_by_order_id, get_order_by_id
        from algosat.core.dbschema import broker_executions
        import datetime
        async with AsyncSessionLocal() as session:
            broker_execs = await get_broker_executions_by_order_id(session, parent_order_id)
            # Fetch the symbol from the orders table (logical order)
            order_row = await get_order_by_id(session, parent_order_id)
            logical_symbol = order_row.get('strike_symbol') or order_row.get('symbol') if order_row else None
            if not broker_execs:
                logger.warning(f"OrderManager: No broker executions found for parent_order_id={parent_order_id} in exit_order.")
                return
            for be in broker_execs:
                status = (be.get('status') or '').upper()
                if status not in ('FILLED', 'PARTIALLY_FILLED', 'PARTIAL'):
                    logger.info(f"OrderManager: Skipping broker_execution id={be.get('id')} with status={status}")
                    # continue
                broker_id = be.get('broker_id')
                broker_order_id = be.get('broker_order_id')
                # Use symbol from logical order if not present in broker_execution
                symbol = be.get('symbol') or logical_symbol
                product_type = be.get('product_type')
                if broker_id is None or broker_order_id is None:
                    logger.error(f"OrderManager: Missing broker_id or broker_order_id in broker_execution for parent_order_id={parent_order_id}")
                    continue
                try:
                    logger.info(f"OrderManager: Initiating exit for broker_execution id={be.get('id')} (broker_id={broker_id}, broker_order_id={broker_order_id}, symbol={symbol}, product_type={product_type}, exit_reason={exit_reason})")
                    await self.broker_manager.exit_order(
                        broker_id,
                        broker_order_id,
                        symbol=symbol,
                        product_type=product_type,
                        exit_reason=exit_reason
                    )
                    logger.info(f"OrderManager: Exit order sent to broker_id={broker_id} for broker_order_id={broker_order_id}")

                    # --- Insert broker_executions row for EXIT ---
                    exit_time = datetime.datetime.now(datetime.timezone.utc)
                    broker_exec_data = dict(
                        parent_order_id=parent_order_id,
                        broker_id=broker_id,
                        broker_order_id=broker_order_id,
                        side='EXIT',
                        execution_price=ltp or 0.0,
                        executed_quantity=be.get('executed_quantity', 0),
                        status='FILLED',
                        order_messages=f"Exit order placed. Reason: {exit_reason}",
                        raw_execution_data=None,
                        symbol=symbol,
                        execution_time=exit_time,
                        product_type=product_type,
                        order_type='MARKET',
                        notes=f"Auto exit via OrderManager. Reason: {exit_reason}"
                    )
                    await session.execute(broker_executions.insert().values(**broker_exec_data))
                    await session.commit()
                except Exception as e:
                    logger.error(f"OrderManager: Error exiting order for broker_id={broker_id}, broker_order_id={broker_order_id}: {e}")

