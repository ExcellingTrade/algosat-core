# core/order_manager.py
"""
OrderManager: Responsible for managing the lifecycle of orders across all brokers that are trade enabled and live/authenticated.
"""
from typing import Optional, Dict, Any, List # Added typing imports
from algosat.core.db import get_trade_enabled_brokers, AsyncSessionLocal, insert_order, get_broker_by_name
from algosat.brokers.factory import get_broker
from algosat.common.logger import get_logger
from algosat.core.dbschema import trade_logs
from algosat.core.broker_manager import BrokerManager
from algosat.core.order_request import OrderRequest, OrderStatus, Side, OrderType
from algosat.core.dbschema import orders as orders_table
from algosat.models.strategy_config import StrategyConfig
from algosat.models.order_aggregate import OrderAggregate, BrokerOrder
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
    1: OrderStatus.AWAITING_ENTRY,  # Example: 1 = pending
    2: OrderStatus.OPEN,           # Example: 2 = open
    3: OrderStatus.PARTIALLY_FILLED,
    4: OrderStatus.FILLED,
    5: OrderStatus.CANCELLED,
    6: OrderStatus.REJECTED,
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
        return {"order_id": order_id}

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
                    'trigger_price': (current_price - trigger_price_diff) if order_payload.side == Side.BUY else (current_price + trigger_price_diff)
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
        Insert a row into broker_executions for a broker's response to an order.
        Always stores all broker order ids as a list in broker_order_ids (even if only one), and one entry per broker per logical order.
        """
        from algosat.core.dbschema import broker_executions
        broker_id = response.get("broker_id")
        if broker_id is None:
            broker_id = await self._get_broker_id(broker_name)
        # Always store broker_order_ids as a list
        broker_order_ids = []
        # Accept both OrderResponse and dict
        order_ids = response.get("order_ids")
        if isinstance(order_ids, list):
            broker_order_ids = order_ids
        elif order_ids:
            broker_order_ids = [order_ids]
        # Always store status as string value
        status_val = response.get("status", "FAILED")
        if hasattr(status_val, 'value'):
            status_val = status_val.value
        # Ensure order_messages is a list or dict
        order_messages = response.get("order_messages")
        if order_messages is not None and not isinstance(order_messages, (list, dict)):
            order_messages = [order_messages]
        broker_exec_data = dict(
            parent_order_id=parent_order_id,
            broker_id=broker_id,
            broker_name=broker_name,  # Deprecated: broker_name, keep for migration only
            broker_order_ids=broker_order_ids,
            order_messages=order_messages,
            status=status_val,
            raw_response=response,
        )
        await session.execute(broker_executions.insert().values(**broker_exec_data))

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

    async def get_all_broker_order_details(self) -> list:
        """
        Fetch and normalize order details from all trade-enabled brokers via BrokerManager.
        Returns a list of dicts with common fields: broker_name, broker_id, order_id, status, symbol, raw.
        """
        broker_orders_raw = await self.broker_manager.get_all_broker_order_details()
        normalized_orders = []
        # You may want to cache broker_id lookups for efficiency
        broker_name_to_id = {}
        async def get_broker_id_cached(broker_name):
            if broker_name in broker_name_to_id:
                return broker_name_to_id[broker_name]
            broker_id = await self._get_broker_id(broker_name)
            broker_name_to_id[broker_name] = broker_id
            return broker_id
        for broker_name, orders in broker_orders_raw.items():
            broker_id = await get_broker_id_cached(broker_name)
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
        return normalized_orders

_order_manager_instance = None

def get_order_manager(broker_manager: BrokerManager) -> OrderManager:
    global _order_manager_instance
    # Ensure BrokerManager is passed for the first instantiation
    # or if the existing instance was created with a different broker_manager (though this simple version doesn't check that)
    if _order_manager_instance is None or _order_manager_instance.broker_manager != broker_manager:
        _order_manager_instance = OrderManager(broker_manager)
    return _order_manager_instance
