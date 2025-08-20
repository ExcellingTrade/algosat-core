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
from algosat.utils.telegram_notify import telegram_bot, send_telegram_async

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
        # Initialize data_manager lazily for broker name lookups
        self._data_manager = None

    async def _get_data_manager(self):
        """Get or create DataManager instance for internal operations."""
        if self._data_manager is None:
            from algosat.core.data_manager import DataManager
            self._data_manager = DataManager(broker_manager=self.broker_manager)
            await self._data_manager.ensure_broker()
        return self._data_manager

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
        parent_order_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Places an order by building a canonical OrderRequest and delegating to BrokerManager for broker routing.
        Inserts one row in orders (logical trade), and one row per broker in broker_executions.
        Returns the logical order id (orders.id) as canonical reference.

        Args:
            config: The strategy configuration (StrategyConfig instance).
            order_payload: The OrderRequest object detailing the order.
            strategy_name: Optional name of the strategy placing the order.
            parent_order_id: Optional parent order ID to establish parent-child relationship (e.g., hedge order for main order).

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
        # 2. Place order(s) with brokers
        check_margin = config.trade.get('check_margin', False)
        if max_nse_qty and order_payload.quantity > max_nse_qty:
            return await self.split_and_place_order(config, order_payload, max_nse_qty, strategy_name, check_margin=check_margin)
        # 1. Insert logical order row (orders)
        async with AsyncSessionLocal() as session:
            order_id = await self._insert_and_get_order_id(
                config=config,
                order_payload=order_payload,
                broker_name=None,
                result=None,
                parent_order_id=parent_order_id
            )
            if not order_id:
                logger.error("Failed to insert logical order row.")
                return None
            
            
            broker_responses = await self.broker_manager.place_order(order_payload, strategy_name=strategy_name, check_margin=check_margin)
            # 3. Insert broker_executions rows
            for broker_name, response in broker_responses.items():
                raw_action = getattr(order_payload, 'side', None) or response.get('side', None) or 'BUY'
                action = self.normalize_action_field(raw_action)
                # logger.debug(f"OrderManager: Action normalization in place_order - raw_action='{raw_action}' -> action='{action}'")
                try:
                    await self._insert_broker_execution(session, order_id, broker_name, response, side=ExecutionSide.ENTRY.value, action=action)
                except Exception as insert_error:
                    logger.error(f"OrderManager: Failed to insert broker_execution for {broker_name} in place_order: {insert_error}")
                    # Continue with other brokers even if one fails
            await session.commit()
        # Telegram notification for order placed
        try:
            msg_lines = [
                f"🟢 <b>Order Placed</b>",
                f"<b>Order ID:</b> <code>{order_id}</code>",
                f"<b>Symbol:</b> <code>{order_payload.symbol}</code>",
                f"<b>Qty:</b> <code>{order_payload.quantity}</code>",
                f"<b>Side:</b> <code>{getattr(order_payload, 'side', 'N/A')}</code>",
            ]
            for broker_name, resp in broker_responses.items():
                status = resp.get('status', 'N/A')
                broker_order_id = resp.get('order_id', resp.get('broker_order_id', 'N/A'))
                traded_price = resp.get('traded_price', resp.get('average_price', 'N/A'))
                msg_lines.append(f"<b>{broker_name}:</b> <code>{status}</code> | <b>ID:</b> <code>{broker_order_id}</code> | <b>Price:</b> <code>{traded_price}</code>")
            send_telegram_async("\n".join(msg_lines))
        except Exception as e:
            logger.error(f"Failed to send Telegram order notification: {e}")
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
                # Only calculate trigger_price for non-MARKET orders and when current_price > 0
                if current_price > 0 and order_payload.order_type != OrderType.MARKET:
                    trigger_price = (current_price - trigger_price_diff) if order_payload.side == Side.BUY else (current_price + trigger_price_diff)
                else:
                    trigger_price = None  # MARKET orders or zero-price orders should not have trigger_price
                slice_payload = self.create_slice_payload(order_payload, qty, current_price, trigger_price, order_payload.side)
                broker_responses = await self.broker_manager.place_order(slice_payload, strategy_name=strategy_name, check_margin=check_margin)
                for broker_name, response in broker_responses.items():
                    # Insert a broker_executions row for this split order
                    raw_action = getattr(order_payload, 'side', None) or response.get('side', None) or 'BUY'
                    action = self.normalize_action_field(raw_action)
                    try:
                        await self._insert_broker_execution(
                            session,
                            parent_order_id,
                            broker_name,
                            response,
                            side=ExecutionSide.ENTRY.value,
                            action=action
                        )
                    except Exception as insert_error:
                        logger.error(f"OrderManager: Failed to insert broker_execution for {broker_name} in split order: {insert_error}")
                        # Continue with other brokers even if one fails
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

    async def has_child_orders(self, parent_order_id: int) -> bool:
        """
        Check if an order has any child orders without fetching them.
        
        Args:
            parent_order_id: ID of the parent order
            
        Returns:
            True if the order has child orders, False otherwise
        """
        from algosat.core.db import AsyncSessionLocal
        from algosat.core.dbschema import orders
        from sqlalchemy import select, func
        
        async with AsyncSessionLocal() as session:
            stmt = select(func.count(orders.c.id)).where(orders.c.parent_order_id == parent_order_id)
            result = await session.execute(stmt)
            count = result.scalar()
            has_children = count > 0
            logger.debug(f"OrderManager: Order {parent_order_id} has child orders: {has_children}")
            return has_children

    async def get_child_orders(self, parent_order_id: int) -> List[dict]:
        """
        Get all child orders for a given parent order ID.
        
        Args:
            parent_order_id: ID of the parent order
            
        Returns:
            List of child order records
        """
        from algosat.core.db import AsyncSessionLocal
        from algosat.core.dbschema import orders
        from sqlalchemy import select
        
        async with AsyncSessionLocal() as session:
            stmt = select(orders).where(orders.c.parent_order_id == parent_order_id)
            result = await session.execute(stmt)
            child_orders = [dict(row._mapping) for row in result.fetchall()]
            logger.debug(f"OrderManager: Found {len(child_orders)} child orders for parent_order_id={parent_order_id}")
            return child_orders

    async def exit_child_orders(self, parent_order_id: int, exit_reason: str = None, check_live_status: bool = False):
        """
        Exit all child orders for a given parent order.
        This is called when a main order exits to also exit its hedge orders.
        NOTE: This method assumes has_child_orders() has already been checked.
        
        Args:
            parent_order_id: ID of the parent order whose children should be exited
            exit_reason: Reason for exiting the child orders
            check_live_status: Whether to check live broker status before exit
        """
        try:
            child_orders = await self.get_child_orders(parent_order_id)
            logger.info(f"OrderManager: Found {len(child_orders)} child orders to exit for parent_order_id={parent_order_id}")
            
            for child_order in child_orders:
                child_order_id = child_order['id']
                child_symbol = child_order.get('strike_symbol') or child_order.get('symbol', 'Unknown')
                child_status = child_order.get('status', 'Unknown')
                
                # Skip child orders that are already closed/exited
                if child_status in ('FILLED', 'CANCELLED', 'REJECTED', 'FAILED'):
                    logger.info(f"OrderManager: Skipping child order {child_order_id} (symbol={child_symbol}) - already closed with status={child_status}")
                    continue
                
                try:
                    logger.info(f"OrderManager: Exiting child order {child_order_id} (symbol={child_symbol}, status={child_status}) due to parent order {parent_order_id} exit")
                    
                    # Recursively call exit_order for the child - this will handle any grandchildren too
                    await self.exit_order(
                        parent_order_id=child_order_id,
                        exit_reason=exit_reason or f"Parent order {parent_order_id} exited",
                        check_live_status=check_live_status
                    )
                    
                    # Update child order status to EXIT_CLOSED since it's being closed due to parent order exit
                    try:
                        from algosat.common.constants import TRADE_STATUS_EXIT_CLOSED
                        await self.update_order_status_in_db(child_order_id, TRADE_STATUS_EXIT_CLOSED)
                        logger.info(f"OrderManager: Updated child order {child_order_id} status to EXIT_CLOSED due to parent order {parent_order_id} exit")
                    except Exception as status_e:
                        logger.error(f"OrderManager: Failed to update child order {child_order_id} status to EXIT_CLOSED: {status_e}")
                    
                    logger.info(f"OrderManager: Successfully initiated exit for child order {child_order_id}")
                    
                except Exception as e:
                    logger.error(f"OrderManager: Failed to exit child order {child_order_id}: {e}", exc_info=True)
                    # Continue with other child orders even if one fails
                    continue
                    
        except Exception as e:
            logger.error(f"OrderManager: Error in exit_child_orders for parent_order_id={parent_order_id}: {e}", exc_info=True)

    async def set_parent_order_id(self, child_order_id: int, parent_order_id: int):
        """
        Update the parent_order_id of an order row after insert.
        Useful for establishing parent-child relationships between orders (e.g., hedge and main orders).
        
        Args:
            child_order_id: ID of the child order (e.g., hedge order)
            parent_order_id: ID of the parent order (e.g., main order)
        """
        from algosat.core.db import AsyncSessionLocal, update_rows_in_table
        from algosat.core.dbschema import orders
        async with AsyncSessionLocal() as session:
            await update_rows_in_table(
                target_table=orders,
                condition=orders.c.id == child_order_id,
                new_values={"parent_order_id": parent_order_id}
            )
            await session.commit()
            logger.info(f"OrderManager: Set parent_order_id relationship: child {child_order_id} -> parent {parent_order_id}")

    async def _set_parent_order_id(self, order_id, parent_order_id):
        """
        Update the parent_order_id of an order row after insert.
        DEPRECATED: Use set_parent_order_id instead.
        """
        await self.set_parent_order_id(order_id, parent_order_id)

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
                "parent_order_id": parent_order_id,  # NEW: Set parent-child relationship (e.g., hedge order for main order)
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
                "orig_target": order_payload.extra.get("orig_target"),
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

    def build_broker_exec_data(self, *, parent_order_id, broker_id, broker_order_id, side, status, executed_quantity=0, execution_price=0.0, product_type=None, order_type=None, order_messages=None, action=None, raw_execution_data=None, symbol=None, execution_time=None, notes=None, exit_broker_order_id=None, quantity=None):
        """
        Utility to build the broker execution data dict for DB insert.
        """
        # Additional safety check for boolean status values
        if isinstance(status, bool):
            status = "FAILED" if status is False else "PENDING"
            logger.warning(f"OrderManager: build_broker_exec_data converted boolean status to string: {status}")
        
        # Ensure executed_quantity is never None for database NOT NULL constraint
        if executed_quantity is None:
            executed_quantity = 0
            logger.warning(f"OrderManager: build_broker_exec_data converted None executed_quantity to 0")
        
        return dict(
            parent_order_id=parent_order_id,
            broker_id=broker_id,
            broker_order_id=broker_order_id,
            exit_broker_order_id=exit_broker_order_id,
            side=side,
            action=action or side,
            status=OrderManager.to_enum_value(status),
            executed_quantity=executed_quantity,
            execution_price=execution_price,
            quantity=quantity,
            product_type=product_type,
            order_type=order_type,
            order_messages=order_messages,
            raw_execution_data=raw_execution_data,
            symbol=symbol,
            execution_time=execution_time,
            notes=notes
        )

    @staticmethod
    def normalize_action_field(action_value):
        """
        Normalize action field to remove enum prefixes and ensure consistent string format.
        Handles: Side.BUY -> BUY, SIDE.BUY -> BUY, 'BUY' -> BUY
        """
        if action_value is None:
            return 'BUY'  # Default fallback
            
        # Handle both enum values (Side.BUY) and string values ('BUY')
        if hasattr(action_value, 'value'):
            normalized = str(action_value.value).upper()
        else:
            normalized = str(action_value).upper()
        
        # Remove any 'SIDE.' prefix if present (normalize SIDE.BUY to BUY)
        if normalized.startswith('SIDE.'):
            normalized = normalized[5:]
            
        return normalized

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
            
            # Enhanced status conversion for broker responses
            if isinstance(status_val, bool):
                # Boolean status from broker response
                if status_val is False:
                    status_val = "FAILED"  # Failed orders
                    logger.warning(f"OrderManager: Converted boolean False to FAILED for broker_name={broker_name}")
                else:  # status_val is True
                    # For successful orders, check if we have an order_id to determine proper status
                    if order_id:
                        status_val = "PENDING"  # Order placed successfully, awaiting execution
                        logger.info(f"OrderManager: Converted boolean True to PENDING for broker_name={broker_name} with order_id={order_id}")
                    else:
                        status_val = "FAILED"  # True but no order_id means something went wrong
                        logger.warning(f"OrderManager: Converted boolean True to FAILED (no order_id) for broker_name={broker_name}")
            elif isinstance(status_val, str):
                # String status - validate and normalize
                status_upper = status_val.upper()
                if status_upper in ["COMPLETE", "COMPLETED", "FILLED", "TRADED"]:
                    status_val = "FILLED"
                elif status_upper in ["PARTIAL", "PARTIALLY_FILLED"]:
                    status_val = "PARTIALLY_FILLED"
                elif status_upper in ["REJECT", "REJECTED"]:
                    status_val = "REJECTED"
                elif status_upper in ["CANCEL", "CANCELLED"]:
                    status_val = "CANCELLED"
                elif status_upper == "PENDING":
                    status_val = "PENDING"
                else:
                    # Keep original string value for other statuses
                    status_val = status_upper
                logger.debug(f"OrderManager: Normalized string status '{response.get('status')}' -> '{status_val}' for broker_name={broker_name}")
            else:
                # Non-boolean, non-string status (unexpected)
                status_val = "FAILED"
                logger.warning(f"OrderManager: Unexpected status type {type(status_val)} with value {status_val}, defaulting to FAILED for broker_name={broker_name}")
            
            # VALIDATION: Skip insertion if broker_order_id is None (required field)
            if order_id is None:
                logger.warning(f"OrderManager: Skipping broker_execution insert for {broker_name} - broker_order_id is None. Response: {response}")
                return
            
            product_type = response.get("product_type")
            order_type = response.get("order_type")
            exec_price = response.get("execPrice", 0.0)
            exec_quantity = response.get("execQuantity", 0)
            raw_action_val = action or response.get("side", "BUY")
            action_val = self.normalize_action_field(raw_action_val)
            symbol = response.get("symbol")  # isymbol from broker response
            
            logger.debug(f"OrderManager: Action normalization in _insert_broker_execution - raw_action='{raw_action_val}' -> action='{action_val}'")
            
            # Log symbol extraction for debugging
            if symbol:
                logger.info(f"OrderManager: Extracted symbol '{symbol}' from {broker_name} response for parent_order_id={parent_order_id}")
            else:
                logger.warning(f"OrderManager: No symbol found in {broker_name} response for parent_order_id={parent_order_id}. Response keys: {list(response.keys())}")
            
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
                raw_execution_data=self._serialize_datetime_for_json(response),
                symbol=symbol  # Include symbol in broker execution data
            )
            await session.execute(broker_executions.insert().values(**broker_exec_data))
            logger.info(f"OrderManager: Successfully inserted broker_execution for {broker_name}, parent_order_id={parent_order_id}, order_id={order_id}")
        except Exception as e:
            logger.error(f"_insert_broker_execution failed for broker_name={broker_name}, parent_order_id={parent_order_id}: {e}", exc_info=True)
            # Continue processing other brokers even if one fails - don't re-raise

    async def _insert_exit_broker_execution(self, session, *, parent_order_id, broker_id, broker_order_id, side, status, executed_quantity, execution_price=0.0, product_type, order_type, order_messages, symbol, execution_time=None, notes, action=None, exit_reason=None, exit_broker_order_id=None, quantity=None):
        """
        Helper to build and insert a broker_executions row for EXIT/cancel actions.
        Checks for existing EXIT entries before inserting to prevent duplicates.
        """
        from algosat.core.dbschema import broker_executions
        from algosat.core.db import get_broker_executions_for_order
        
        # Check if EXIT broker_execution already exists for this parent_order_id, broker_id, broker_order_id
        existing_execs = await get_broker_executions_for_order(
            session,
            parent_order_id,
            side='EXIT'
        )
        found = None
        for ex in existing_execs:
            if ex.get('broker_id') == broker_id and ex.get('broker_order_id') == broker_order_id:
                found = ex
                break
        
        if found:
            # Update only execution_price if EXIT entry already exists
            await self.update_broker_execution_price(found.get('id'), execution_price)
            logger.info(f"OrderManager: Updated execution_price for existing EXIT broker_execution id={found.get('id')}")
        else:
            # Insert new EXIT broker_execution
            broker_exec_data = self.build_broker_exec_data(
                parent_order_id=parent_order_id,
                broker_id=broker_id,
                broker_order_id=broker_order_id,
                side=side,
                status=status,
                executed_quantity=executed_quantity,
                execution_price=execution_price,
                quantity=quantity,
                product_type=product_type,
                order_type=order_type,
                order_messages=order_messages,
                action=action,
                raw_execution_data=None,
                symbol=symbol,
                execution_time=execution_time,
                notes=notes,
                exit_broker_order_id=exit_broker_order_id
            )
            await session.execute(broker_executions.insert().values(**broker_exec_data))
            logger.info(f"OrderManager: Inserted new EXIT broker_execution for parent_order_id={parent_order_id}, broker_id={broker_id}, broker_order_id={broker_order_id}, exit_broker_order_id={exit_broker_order_id}")


    async def exit_all_orders(self, exit_reason: str = None, strategy_id: int = None, check_live_status: bool = False, broker_ids_filter: List[int] = None, broker_names_filter: List[str] = None):
        """
        Exit all open orders by querying the orders table for orders with open statuses
        and calling exit_order for each of them.
        
        Args:
            exit_reason: Optional reason for exiting all orders
            strategy_id: Optional strategy ID to filter orders by. If provided, only orders 
                        belonging to this strategy will be exited.
            check_live_status: If True, check live broker status before exit decisions
            broker_ids_filter: Optional list of broker IDs to filter by. If provided, only 
                             broker executions from these brokers will be exited.
            broker_names_filter: Optional list of broker names to filter by. If provided, only 
                               broker executions from these brokers will be exited.
        """
        from algosat.core.db import AsyncSessionLocal, get_orders_by_strategy_id
        from algosat.core.dbschema import orders
        from sqlalchemy import select
        
        # Convert broker names to broker IDs if needed using cached approach
        final_broker_ids_filter = None
        if broker_ids_filter or broker_names_filter:
            final_broker_ids_filter = list(broker_ids_filter) if broker_ids_filter else []
            
            if broker_names_filter:
                # Use cached broker name to ID mapping (similar to get_all_broker_order_details)
                broker_name_to_id = {}
                
                async def get_broker_id_cached(broker_name):
                    if broker_name in broker_name_to_id:
                        return broker_name_to_id[broker_name]
                    broker_id = await self._get_broker_id(broker_name)
                    broker_name_to_id[broker_name] = broker_id
                    return broker_id
                
                # Convert broker names to IDs using cached lookup
                for broker_name in broker_names_filter:
                    broker_id = await get_broker_id_cached(broker_name)
                    if broker_id:
                        final_broker_ids_filter.append(broker_id)
                        logger.info(f"OrderManager: Mapped broker_name '{broker_name}' to broker_id {broker_id}")
                    else:
                        logger.warning(f"OrderManager: Broker name '{broker_name}' not found in credentials table")
            
            # Create filter description for logging
            filter_description = f" (filtered to broker_ids: {final_broker_ids_filter})" if final_broker_ids_filter else ""
            logger.info(f"OrderManager: Exit orders with broker filter{filter_description}")
        
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
                    broker_filter_desc = f" with broker filter {final_broker_ids_filter}" if final_broker_ids_filter else ""
                    logger.info(f"OrderManager: Exiting order {order_id} (symbol={symbol}, status={order_status}){broker_filter_desc} with check_live_status={check_live_status}")
                    await self.exit_order(
                        parent_order_id=order_id,
                        exit_reason=exit_reason or "Exit all orders requested",
                        check_live_status=check_live_status,
                        broker_ids_filter=final_broker_ids_filter
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
            "raw_execution_data": self._serialize_datetime_for_json(raw_execution_data) if raw_execution_data else None
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

    def _serialize_datetime_for_json(self, data):
        """
        Recursively convert datetime objects and enums to JSON-serializable values.
        """
        if isinstance(data, dict):
            return {key: self._serialize_datetime_for_json(value) for key, value in data.items()}
        elif isinstance(data, list):
            return [self._serialize_datetime_for_json(item) for item in data]
        elif isinstance(data, datetime):
            return data.isoformat()
        elif isinstance(data, Enum):
            return data.value
        elif hasattr(data, '__dict__'):
            # Handle objects with datetime attributes
            result = {}
            for key, value in data.__dict__.items():
                result[key] = self._serialize_datetime_for_json(value)
            return result
        else:
            return data

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
        # Mock data for testing (only on Aug 9, 2025) with comprehensive broker order data from logs
        from datetime import datetime, date
        if date.today() == date(2025, 8, 10):
            logger.info("Using comprehensive mock broker order data for testing (Aug 9, 2025) - all broker orders from logs")
            mock_broker_orders = {
                'zerodha': [
                    {'broker_name': 'zerodha', 'broker_id': 3, 'order_id': '250808600208680', 'status': 'FILLED', 'symbol': 'NIFTY2581424500PE', 'quantity': 75, 'executed_quantity': 75, 'exec_price': 139.45, 'product_type': 'MIS', 'order_type': 'LIMIT', 'exchange_timestamp': '2025-08-08 14:20:07'},
                    {'broker_name': 'zerodha', 'broker_id': 3, 'order_id': '250808600351563', 'status': 'FILLED', 'symbol': 'NIFTY2581424900CE', 'quantity': 75, 'executed_quantity': 75, 'exec_price': 18.4, 'product_type': 'NRML', 'order_type': 'MARKET', 'exchange_timestamp': '2025-08-08 14:20:07'},
                    {'broker_name': 'zerodha', 'broker_id': 3, 'order_id': '250808600356326', 'status': 'FILLED', 'symbol': 'NIFTY2581424400PE', 'quantity': 75, 'executed_quantity': 75, 'exec_price': 111.75, 'product_type': 'NRML', 'order_type': 'MARKET', 'exchange_timestamp': '2025-08-08 14:20:07'},
                    {'broker_name': 'zerodha', 'broker_id': 3, 'order_id': '250808600356343', 'status': 'FILLED', 'symbol': 'NIFTY2581424450PE', 'quantity': 75, 'executed_quantity': 75, 'exec_price': 134.2, 'product_type': 'NRML', 'order_type': 'MARKET', 'exchange_timestamp': '2025-08-08 14:20:07'},
                    {'broker_name': 'zerodha', 'broker_id': 3, 'order_id': '250808600358768', 'status': 'FILLED', 'symbol': 'NIFTY2581424400PE', 'quantity': 75, 'executed_quantity': 75, 'exec_price': 111.65, 'product_type': 'NRML', 'order_type': 'MARKET', 'exchange_timestamp': '2025-08-08 14:20:07'},
                    {'broker_name': 'zerodha', 'broker_id': 3, 'order_id': '250808600353018', 'status': 'FILLED', 'symbol': 'NIFTY2581424900CE', 'quantity': 75, 'executed_quantity': 75, 'exec_price': 18.1, 'product_type': 'NRML', 'order_type': 'LIMIT', 'exchange_timestamp': '2025-08-08 14:20:07'},
                    {'broker_name': 'zerodha', 'broker_id': 3, 'order_id': '250808600579485', 'status': 'FILLED', 'symbol': 'NIFTY2581424450PE', 'quantity': 75, 'executed_quantity': 75, 'exec_price': 103.45, 'product_type': 'NRML', 'order_type': 'MARKET', 'exchange_timestamp': '2025-08-08 14:20:07'},
                    {'broker_name': 'zerodha', 'broker_id': 3, 'order_id': '250808600582884', 'status': 'FILLED', 'symbol': 'NIFTY2581424550CE', 'quantity': 75, 'executed_quantity': 75, 'exec_price': 115.9, 'product_type': 'NRML', 'order_type': 'MARKET', 'exchange_timestamp': '2025-08-08 14:20:07'},
                    {'broker_name': 'zerodha', 'broker_id': 3, 'order_id': '250808600582899', 'status': 'FILLED', 'symbol': 'NIFTY2581424500CE', 'quantity': 75, 'executed_quantity': 75, 'exec_price': 140.6, 'product_type': 'NRML', 'order_type': 'MARKET', 'exchange_timestamp': '2025-08-08 14:20:07'},
                    {'broker_name': 'zerodha', 'broker_id': 3, 'order_id': '250808600583778', 'status': 'FILLED', 'symbol': 'NIFTY2581424500PE', 'quantity': 75, 'executed_quantity': 75, 'exec_price': 121.3, 'product_type': 'MIS', 'order_type': 'MARKET', 'exchange_timestamp': '2025-08-08 14:20:07'},
                    {'broker_name': 'zerodha', 'broker_id': 3, 'order_id': '250808600592290', 'status': 'FILLED', 'symbol': 'NIFTY2581424500CE', 'quantity': 75, 'executed_quantity': 75, 'exec_price': 127.05, 'product_type': 'NRML', 'order_type': 'MARKET', 'exchange_timestamp': '2025-08-08 14:20:07'},
                    {'broker_name': 'zerodha', 'broker_id': 3, 'order_id': '250808600592430', 'status': 'FILLED', 'symbol': 'NIFTY2581424550CE', 'quantity': 75, 'executed_quantity': 75, 'exec_price': 103.55, 'product_type': 'NRML', 'order_type': 'MARKET', 'exchange_timestamp': '2025-08-08 14:20:07'},
                    {'broker_name': 'zerodha', 'broker_id': 3, 'order_id': '250808600594402', 'status': 'FILLED', 'symbol': 'NIFTY2581424500CE', 'quantity': 75, 'executed_quantity': 75, 'exec_price': 125.55, 'product_type': 'NRML', 'order_type': 'MARKET', 'exchange_timestamp': '2025-08-08 14:20:07'},
                    {'broker_name': 'zerodha', 'broker_id': 3, 'order_id': '250808600602823', 'status': 'FILLED', 'symbol': 'NIFTY2581424500CE', 'quantity': 75, 'executed_quantity': 75, 'exec_price': 120.25, 'product_type': 'NRML', 'order_type': 'MARKET', 'exchange_timestamp': '2025-08-08 14:20:07'},
                    {'broker_name': 'zerodha', 'broker_id': 3, 'order_id': '250808600742217', 'status': 'FILLED', 'symbol': 'NIFTY2581424400PE', 'quantity': 75, 'executed_quantity': 75, 'exec_price': 110.4, 'product_type': 'NRML', 'order_type': 'MARKET', 'exchange_timestamp': '2025-08-08 14:20:07'},
                    {'broker_name': 'zerodha', 'broker_id': 3, 'order_id': '250808600742226', 'status': 'FILLED', 'symbol': 'NIFTY2581424350PE', 'quantity': 75, 'executed_quantity': 75, 'exec_price': 90.4, 'product_type': 'NRML', 'order_type': 'MARKET', 'exchange_timestamp': '2025-08-08 14:20:07'},
                    {'broker_name': 'zerodha', 'broker_id': 3, 'order_id': '250808600790593', 'status': 'FILLED', 'symbol': 'NIFTY2581424400PE', 'quantity': 75, 'executed_quantity': 75, 'exec_price': 107.2, 'product_type': 'NRML', 'order_type': 'MARKET', 'exchange_timestamp': '2025-08-08 14:20:07'},
                    {'broker_name': 'zerodha', 'broker_id': 3, 'order_id': '250808600790790', 'status': 'FILLED', 'symbol': 'NIFTY2581424350PE', 'quantity': 75, 'executed_quantity': 75, 'exec_price': 87.35, 'product_type': 'NRML', 'order_type': 'MARKET', 'exchange_timestamp': '2025-08-08 14:20:07'},
                    {'broker_name': 'zerodha', 'broker_id': 3, 'order_id': '250808600836393', 'status': 'FILLED', 'symbol': 'NIFTY2581424300PE', 'quantity': 75, 'executed_quantity': 75, 'exec_price': 85.6, 'product_type': 'NRML', 'order_type': 'MARKET', 'exchange_timestamp': '2025-08-08 14:20:07'},
                    {'broker_name': 'zerodha', 'broker_id': 3, 'order_id': '250808600850173', 'status': 'FILLED', 'symbol': 'NIFTY2581424300PE', 'quantity': 75, 'executed_quantity': 75, 'exec_price': 96.9, 'product_type': 'NRML', 'order_type': 'MARKET', 'exchange_timestamp': '2025-08-08 14:20:07'}
                ],
                'fyers': [
                    {'broker_name': 'fyers', 'broker_id': 1, 'order_id': '25080800069210-BO-1', 'status': 'FILLED', 'symbol': 'NSE:NIFTY2581424500PE', 'qty': 75, 'executed_quantity': 75, 'exec_price': 139.5, 'product_type': 'BO', 'order_type': 'Limit', 'orderDateTime': '08-Aug-2025 14:20:07'},
                    {'broker_name': 'fyers', 'broker_id': 1, 'order_id': '25080800103792', 'status': 'FILLED', 'symbol': 'NSE:NIFTY2581424900CE', 'qty': 75, 'executed_quantity': 75, 'exec_price': 20.85, 'product_type': 'INTRADAY', 'order_type': 'Market', 'orderDateTime': '08-Aug-2025 14:20:07'},
                    {'broker_name': 'fyers', 'broker_id': 1, 'order_id': '25080800131213', 'status': 'FILLED', 'symbol': 'NSE:NIFTY2581424400PE', 'qty': 75, 'executed_quantity': 75, 'exec_price': 111.95, 'product_type': 'MARGIN', 'order_type': 'Market', 'orderDateTime': '08-Aug-2025 14:20:07'},
                    {'broker_name': 'fyers', 'broker_id': 1, 'order_id': '25080800131221', 'status': 'FILLED', 'symbol': 'NSE:NIFTY2581424450PE', 'qty': 75, 'executed_quantity': 75, 'exec_price': 133.85, 'product_type': 'MARGIN', 'order_type': 'Market', 'orderDateTime': '08-Aug-2025 14:20:07'},
                    {'broker_name': 'fyers', 'broker_id': 1, 'order_id': '25080800131232', 'status': 'FILLED', 'symbol': 'NSE:NIFTY2581424150PE', 'qty': 75, 'executed_quantity': 75, 'exec_price': 41.15, 'product_type': 'INTRADAY', 'order_type': 'Market', 'orderDateTime': '08-Aug-2025 14:20:07'},
                    {'broker_name': 'fyers', 'broker_id': 1, 'order_id': '25080800132094', 'status': 'FILLED', 'symbol': 'NSE:NIFTY2581424400PE', 'qty': 75, 'executed_quantity': 75, 'exec_price': 111.6, 'product_type': 'MARGIN', 'order_type': 'Market', 'orderDateTime': '08-Aug-2025 14:20:07'},
                    {'broker_name': 'fyers', 'broker_id': 1, 'order_id': '25080800133576', 'status': 'FILLED', 'symbol': 'NSE:NIFTY2581424150PE', 'qty': 75, 'executed_quantity': 75, 'exec_price': 42.05, 'product_type': 'INTRADAY', 'order_type': 'Market', 'orderDateTime': '08-Aug-2025 14:20:07'},
                    {'broker_name': 'fyers', 'broker_id': 1, 'order_id': '25080800133881', 'status': 'FILLED', 'symbol': 'NSE:NIFTY2581424900CE', 'qty': 75, 'executed_quantity': 75, 'exec_price': 17.6, 'product_type': 'INTRADAY', 'order_type': 'Market', 'orderDateTime': '08-Aug-2025 14:20:07'},
                    {'broker_name': 'fyers', 'broker_id': 1, 'order_id': '25080800145627', 'status': 'FILLED', 'symbol': 'NSE:NIFTY2581424200PE', 'qty': 75, 'executed_quantity': 75, 'exec_price': 49.55, 'product_type': 'INTRADAY', 'order_type': 'Market', 'orderDateTime': '08-Aug-2025 14:20:07'},
                    {'broker_name': 'fyers', 'broker_id': 1, 'order_id': '25080800145636', 'status': 'FILLED', 'symbol': 'NSE:NIFTY2581424200PE', 'qty': 75, 'executed_quantity': 75, 'exec_price': 49.2, 'product_type': 'INTRADAY', 'order_type': 'Market', 'orderDateTime': '08-Aug-2025 14:20:07'},
                    {'broker_name': 'fyers', 'broker_id': 1, 'order_id': '25080800221447', 'status': 'FILLED', 'symbol': 'NSE:NIFTY2581424750CE', 'qty': 75, 'executed_quantity': 75, 'exec_price': 44.55, 'product_type': 'INTRADAY', 'order_type': 'Market', 'orderDateTime': '08-Aug-2025 14:20:07'},
                    {'broker_name': 'fyers', 'broker_id': 1, 'order_id': '25080800221457', 'status': 'FILLED', 'symbol': 'NSE:NIFTY2581424450PE', 'qty': 75, 'executed_quantity': 75, 'exec_price': 103.35, 'product_type': 'MARGIN', 'order_type': 'Market', 'orderDateTime': '08-Aug-2025 14:20:07'},
                    {'broker_name': 'fyers', 'broker_id': 1, 'order_id': '25080800076776-BO-3', 'status': 'CANCELLED', 'symbol': 'NSE:NIFTY2581424500PE', 'qty': 75, 'executed_quantity': 0, 'exec_price': 0, 'product_type': 'BO', 'order_type': 'Limit', 'orderDateTime': '08-Aug-2025 14:20:07'},
                    {'broker_name': 'fyers', 'broker_id': 1, 'order_id': '25080800076775-BO-2', 'status': 'FILLED', 'symbol': 'NSE:NIFTY2581424500PE', 'qty': 75, 'executed_quantity': 75, 'exec_price': 120.8, 'product_type': 'BO', 'order_type': 'Limit', 'orderDateTime': '08-Aug-2025 14:20:07'},
                    {'broker_name': 'fyers', 'broker_id': 1, 'order_id': '25080800223163', 'status': 'FILLED', 'symbol': 'NSE:NIFTY2581424500CE', 'qty': 75, 'executed_quantity': 75, 'exec_price': 140.4, 'product_type': 'MARGIN', 'order_type': 'Market', 'orderDateTime': '08-Aug-2025 14:20:07'},
                    {'broker_name': 'fyers', 'broker_id': 1, 'order_id': '25080800223154', 'status': 'FILLED', 'symbol': 'NSE:NIFTY2581424550CE', 'qty': 75, 'executed_quantity': 75, 'exec_price': 115.5, 'product_type': 'MARGIN', 'order_type': 'Market', 'orderDateTime': '08-Aug-2025 14:20:07'},
                    {'broker_name': 'fyers', 'broker_id': 1, 'order_id': '25080800227197', 'status': 'FILLED', 'symbol': 'NSE:NIFTY2581424500CE', 'qty': 75, 'executed_quantity': 75, 'exec_price': 126.75, 'product_type': 'MARGIN', 'order_type': 'Market', 'orderDateTime': '08-Aug-2025 14:20:07'},
                    {'broker_name': 'fyers', 'broker_id': 1, 'order_id': '25080800227202', 'status': 'FILLED', 'symbol': 'NSE:NIFTY2581424750CE', 'qty': 75, 'executed_quantity': 75, 'exec_price': 41.35, 'product_type': 'INTRADAY', 'order_type': 'Market', 'orderDateTime': '08-Aug-2025 14:20:07'},
                    {'broker_name': 'fyers', 'broker_id': 1, 'order_id': '25080800227203', 'status': 'FILLED', 'symbol': 'NSE:NIFTY2581424550CE', 'qty': 75, 'executed_quantity': 75, 'exec_price': 103.65, 'product_type': 'MARGIN', 'order_type': 'Market', 'orderDateTime': '08-Aug-2025 14:20:07'},
                    {'broker_name': 'fyers', 'broker_id': 1, 'order_id': '25080800228141', 'status': 'FILLED', 'symbol': 'NSE:NIFTY2581424500CE', 'qty': 75, 'executed_quantity': 75, 'exec_price': 125.8, 'product_type': 'MARGIN', 'order_type': 'Market', 'orderDateTime': '08-Aug-2025 14:20:07'},
                    {'broker_name': 'fyers', 'broker_id': 1, 'order_id': '25080800231750', 'status': 'FILLED', 'symbol': 'NSE:NIFTY2581424500CE', 'qty': 75, 'executed_quantity': 75, 'exec_price': 120.1, 'product_type': 'MARGIN', 'order_type': 'Market', 'orderDateTime': '08-Aug-2025 14:20:07'},
                    {'broker_name': 'fyers', 'broker_id': 1, 'order_id': '25080800286743', 'status': 'FILLED', 'symbol': 'NSE:NIFTY2581424400PE', 'qty': 75, 'executed_quantity': 75, 'exec_price': 110.35, 'product_type': 'MARGIN', 'order_type': 'Market', 'orderDateTime': '08-Aug-2025 14:20:07'},
                    {'broker_name': 'fyers', 'broker_id': 1, 'order_id': '25080800286755', 'status': 'FILLED', 'symbol': 'NSE:NIFTY2581424350PE', 'qty': 75, 'executed_quantity': 75, 'exec_price': 90.45, 'product_type': 'MARGIN', 'order_type': 'Market', 'orderDateTime': '08-Aug-2025 14:20:07'},
                    {'broker_name': 'fyers', 'broker_id': 1, 'order_id': '25080800303134', 'status': 'FILLED', 'symbol': 'NSE:NIFTY2581424400PE', 'qty': 75, 'executed_quantity': 75, 'exec_price': 107.05, 'product_type': 'MARGIN', 'order_type': 'Market', 'orderDateTime': '08-Aug-2025 14:20:07'},
                    {'broker_name': 'fyers', 'broker_id': 1, 'order_id': '25080800303190', 'status': 'FILLED', 'symbol': 'NSE:NIFTY2581424350PE', 'qty': 75, 'executed_quantity': 75, 'exec_price': 87.25, 'product_type': 'MARGIN', 'order_type': 'Market', 'orderDateTime': '08-Aug-2025 14:20:07'},
                    {'broker_name': 'fyers', 'broker_id': 1, 'order_id': '25080800316916', 'status': 'FILLED', 'symbol': 'NSE:NIFTY2581424300PE', 'qty': 75, 'executed_quantity': 75, 'exec_price': 86.2, 'product_type': 'MARGIN', 'order_type': 'Market', 'orderDateTime': '08-Aug-2025 14:20:07'},
                    {'broker_name': 'fyers', 'broker_id': 1, 'order_id': '25080800321544', 'status': 'FILLED', 'symbol': 'NSE:NIFTY2581424300PE', 'qty': 75, 'executed_quantity': 75, 'exec_price': 96.85, 'product_type': 'MARGIN', 'order_type': 'Market', 'orderDateTime': '08-Aug-2025 14:20:07'}
                ]
            }
            return mock_broker_orders
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
                    order_type = FYERS_ORDER_TYPE_MAP.get(o.get("order_type"), o.get("type"))
                    
                    # Extract execution time from Fyers orderDateTime field
                    execution_time = None
                    if o.get("orderDateTime"):
                        try:
                            from datetime import datetime
                            execution_time = datetime.strptime(o.get("orderDateTime"), "%d-%b-%Y %H:%M:%S")
                        except (ValueError, TypeError):
                            execution_time = None
                    
                    # Extract parent_id for BO orders from the order ID
                    normalized_orders.append({
                        "broker_name": broker_name,
                        "broker_id": broker_id,
                        "order_id": o.get("id"),  # Fyers uses 'id' field in raw data
                        "status": status,
                        "symbol": o.get("symbol"),
                        "qty": o.get("qty", 0),
                        "executed_quantity": o.get("filledQty", 0),  # Fyers uses 'filledQty' in raw data
                        "exec_price": o.get("tradedPrice", 0),  # Fyers uses 'tradedPrice' in raw data
                        "product_type": o.get("productType"),  # Fyers uses 'productType' in raw data
                        "order_type": order_type,
                        "execution_time": execution_time,
                        "side": "BUY" if o.get("side") ==1 else "SELL",
                        "parent_id": o.get("parentId"),  # Add parentId for BO order tracking
                        # "raw": o
                    })
                # Zerodha normalization
                elif broker_name.lower() == "zerodha":
                    status = ZERODHA_STATUS_MAP.get(o.get("status"), o.get("status"))
                    
                    # Extract execution time from Zerodha time fields (prefer exchange_timestamp)
                    execution_time = None
                    if o.get("exchange_timestamp"):
                        execution_time = o.get("exchange_timestamp")
                    elif o.get("order_timestamp"):
                        execution_time = o.get("order_timestamp")
                    elif o.get("exchange_update_timestamp"):
                        # Convert string timestamp to datetime if needed
                        try:
                            from datetime import datetime
                            if isinstance(o.get("exchange_update_timestamp"), str):
                                execution_time = datetime.strptime(o.get("exchange_update_timestamp"), "%Y-%m-%d %H:%M:%S")
                            else:
                                execution_time = o.get("exchange_update_timestamp")
                        except (ValueError, TypeError):
                            execution_time = None
                    
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
                        "execution_time": execution_time,
                        "side": "BUY" if o.get("transaction_type") == "BUY" else "SELL",
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

    async def update_broker_exec_status_in_db(self, broker_exec_id, status):
        """
        Update only the status of a broker execution in the broker_executions table by broker_exec_id.
        For comprehensive updates with multiple fields, use update_rows_in_table directly.
        """
        from algosat.core.db import AsyncSessionLocal, update_rows_in_table
        from algosat.core.dbschema import broker_executions
        
        update_fields = {"status": status.value if hasattr(status, 'value') else str(status)}
        
        logger.info(f"Updating broker execution {broker_exec_id} status to: {update_fields['status']}")
        
        async with AsyncSessionLocal() as session:
            await update_rows_in_table(
                target_table=broker_executions,
                condition=broker_executions.c.id == broker_exec_id,
                new_values=update_fields
            )
            logger.debug(f"Broker execution {broker_exec_id} status updated successfully")

    @staticmethod
    def _get_cache_lookup_order_id(broker_order_id, broker_name, product_type):
        """
        Helper to determine cache key for broker order id.
        For Fyers: Only BO orders without existing -BO- suffix need -BO-1 appended.
        """
        if not broker_order_id or not broker_name:
            return broker_order_id
            
        # Only apply to Fyers broker
        if broker_name.lower() != 'fyers':
            return broker_order_id
            
        # Only apply to BO product type
        if not product_type or product_type.lower() != 'bo':
            return broker_order_id
            
        # Don't append if order_id already has -BO- suffix
        if '-BO-' in str(broker_order_id):
            return broker_order_id
            
        # Append -BO-1 suffix for Fyers BO orders without existing suffix
        return f"{broker_order_id}-BO-1"

    @staticmethod
    def _is_cancel_response_successful(cancel_resp):
        """
        Helper to determine if a cancel response indicates success across different brokers.
        
        Zerodha format: {'status': True/False, 'message': '...'}
        Fyers format: {'code': <number>, 's': 'ok'/'error', 'message': '...'}
        
        Returns True only if the cancel operation was actually successful.
        """
        if not cancel_resp or not isinstance(cancel_resp, dict):
            return False
            
        # Zerodha: check 'status' field
        if 'status' in cancel_resp:
            return cancel_resp.get('status') is True
            
        # Fyers: check 's' field and 'code' field
        if 's' in cancel_resp:
            s_status = cancel_resp.get('s')
            code = cancel_resp.get('code', 0)
            # Fyers success: s='ok' indicates success, code can vary (200, 1103, etc.)
            return s_status == 'ok'
            
        # Fallback: if neither format is recognized, assume failure for safety
        logger.warning(f"OrderManager: Unrecognized cancel response format: {cancel_resp}")
        return False

    async def exit_order(self, parent_order_id: int, exit_reason: str = None, ltp: float = None, check_live_status: bool = False, broker_ids_filter: List[int] = None):
        """
        Standardized exit: For a logical order, fetch all broker_executions. For each FILLED row, call exit_order. For PARTIALLY_FILLED/PARTIAL, call exit_order then cancel_order. For AWAITING_ENTRY/PENDING, call cancel_order. For REJECTED/FAILED, do nothing.
        After exit/cancel, insert a new broker_executions row with side=EXIT, exit price as LTP (passed in), and update exit_time.
        
        Args:
            parent_order_id: The logical order ID to exit
            exit_reason: Reason for exiting the order
            ltp: If provided, use as exit price. If not provided, will fetch current LTP from the market
            check_live_status: If True, check live broker status via order_cache and update DB before proceeding
            broker_ids_filter: Optional list of broker IDs to filter by. If provided, only 
                             broker executions from these brokers will be processed.
        """

        from algosat.core.db import AsyncSessionLocal, get_broker_executions_for_order, get_order_by_id
        from algosat.common.constants import TRADE_STATUS_EXIT_MANUAL_PENDING
        async with AsyncSessionLocal() as session:
            broker_execs = await get_broker_executions_for_order(session, parent_order_id)
            order_row = await get_order_by_id(session, parent_order_id)
            logical_symbol = order_row.get('strike_symbol') # or order_row.get('symbol') if order_row else None
            order_side = order_row.get('side') if order_row else None
            

            
            if not broker_execs:
                logger.warning(f"OrderManager: No broker executions found for parent_order_id={parent_order_id} in exit_order.")
                return
                
            logger.info(f"OrderManager: Starting exit_order for parent_order_id={parent_order_id} with check_live_status={check_live_status}, exit_reason='{exit_reason}'")
            
            # CRITICAL: Get all broker orders ONCE if live status checking is requested
            # This ensures we have the most current status from brokers before making exit/cancel decisions
            # Particularly important for EXIT_ATOMIC_FAILED scenarios where DB status may be outdated
            all_broker_orders = {}
            if check_live_status:
                try:
                    logger.info(f"OrderManager: Fetching live broker orders for comprehensive status synchronization before exit decisions")
                    all_broker_orders = await self.get_all_broker_order_details()
                    logger.info(f"OrderManager: Retrieved live orders from {len(all_broker_orders)} brokers for status verification")
                    if logger.isEnabledFor(10):  # DEBUG level
                        logger.debug(f"OrderManager: Live broker orders data: {all_broker_orders}")
                except Exception as e:
                    logger.error(f"OrderManager: Error fetching live broker orders: {e}")
                    all_broker_orders = {}
            
            # COORDINATED EXITS: Exit child orders (hedge orders) when main order exits
            # This must be done BEFORE exiting the main order to ensure proper sequencing
            # Check for child orders first to avoid unnecessary DB operations
            try:
                logger.debug(f"OrderManager: Checking for child orders to exit for parent_order_id={parent_order_id}")
                if await self.has_child_orders(parent_order_id):
                    await self.exit_child_orders(
                        parent_order_id=parent_order_id,
                        exit_reason=exit_reason,
                        check_live_status=check_live_status
                    )
                else:
                    logger.debug(f"OrderManager: No child orders found for parent_order_id={parent_order_id}")
            except Exception as e:
                logger.error(f"OrderManager: Error checking/exiting child orders for parent_order_id={parent_order_id}: {e}", exc_info=True)
                # Continue with main order exit even if child order exits fail
            
            for be in broker_execs:
                status = (be.get('status') or '').upper()
                broker_id = be.get('broker_id')
                broker_order_id = be.get('broker_order_id')
                symbol = be.get('symbol') or logical_symbol
                product_type = be.get('product_type')
                broker_exec_id = be.get('id')
                
                # Apply broker filter if specified
                if broker_ids_filter is not None and broker_id not in broker_ids_filter:
                    logger.info(f"OrderManager: Skipping broker_exec_id={broker_exec_id} (broker_id={broker_id}) - not in filter {broker_ids_filter}")
                    continue
                
                self.validate_broker_fields(broker_id, symbol, context_msg=f"exit_order (parent_order_id={parent_order_id})")
                if broker_id is None or broker_order_id is None:
                    logger.error(f"OrderManager: Missing broker_id or broker_order_id in broker_execution for parent_order_id={parent_order_id}")
                    continue
                # Get broker name for live status checking
                broker_name = None
                if check_live_status:
                    try:
                        data_manager = await self._get_data_manager()
                        broker_name = await data_manager.get_broker_name_by_id(broker_id)
                        logger.debug(f"OrderManager: Retrieved broker_name={broker_name} for broker_id={broker_id}")
                    except Exception as e:
                        logger.error(f"OrderManager: Could not get broker_name for broker_id={broker_id}: {e}")
                        
                cache_lookup_order_id = self._get_cache_lookup_order_id(broker_order_id, broker_name, product_type)
                
                # Check live status if requested using existing normalized method
                live_broker_status = None
                if check_live_status and broker_name:
                    try:
                        logger.info(f"OrderManager: Checking live status for broker_exec_id={broker_exec_id}, broker_name={broker_name}, cache_lookup_order_id={cache_lookup_order_id}")
                        
                        # Use the pre-fetched broker orders data
                        broker_orders = all_broker_orders.get(broker_name, [])
                        
                        # Find matching order in broker response
                        matching_order = None
                        if broker_orders:
                            for order in broker_orders:
                                broker_order_id_from_response = order.get('order_id')
                                logger.debug(f"OrderManager: Order info from broker response: {order}")
                                # Direct order ID matching (Fyers maintains consistent BO-1 suffix throughout order lifecycle)
                                if broker_order_id_from_response == cache_lookup_order_id:
                                    matching_order = order
                                    break
                        
                        if matching_order:
                            logger.info(f"OrderManager: Found matching order in live broker data for broker_exec_id={broker_exec_id}")
                            live_broker_status = matching_order.get('status')
                            live_product_type = matching_order.get('product_type')
                            logger.info(f"OrderManager: Live status check - DB status: '{status}', Live status: '{live_broker_status}', Live product_type: '{live_product_type}' for broker_exec_id={broker_exec_id}")
                            
                            # Comprehensive update with all available live broker fields
                            update_fields = {}
                            update_needed = False
                            
                            # Status update - CRITICAL for proper exit/cancel decision making
                            if live_broker_status and live_broker_status.upper() != status:
                                old_status = status
                                update_fields['status'] = live_broker_status
                                status = live_broker_status.upper()  # Use live status for exit decisions
                                update_needed = True
                                logger.info(f"OrderManager: LIVE STATUS SYNC - broker_exec_id={broker_exec_id}: DB status '{old_status}' -> Live status '{live_broker_status}'. This will determine exit vs cancel action.")
                            else:
                                logger.debug(f"OrderManager: Live status '{live_broker_status}' matches DB status '{status}' for broker_exec_id={broker_exec_id}")
                            
                            # Product type update
                            if live_product_type and live_product_type != product_type:
                                update_fields['product_type'] = live_product_type
                                product_type = live_product_type  # Use live product_type for exit decisions
                                update_needed = True
                                logger.info(f"OrderManager: Product_type update needed for broker_exec_id={broker_exec_id}: '{product_type}' -> '{live_product_type}'")
                            
                            # Extract additional fields from live broker data (based on order_monitor comprehensive update logic)
                            # Execution details
                            live_executed_quantity = None
                            live_quantity = None
                            live_execution_price = None
                            live_order_type = None
                            live_symbol = None
                            
                            # Map broker-specific field names to standardized values
                            if broker_name.lower() == "fyers":
                                live_executed_quantity = matching_order.get("executed_quantity") or matching_order.get("filledQty")
                                live_quantity = matching_order.get("qty") or matching_order.get("quantity")
                                live_execution_price = matching_order.get("exec_price") or matching_order.get("tradedPrice")
                                live_order_type = matching_order.get("order_type")
                                live_symbol = matching_order.get("symbol")
                            elif broker_name.lower() == "zerodha":
                                live_executed_quantity = matching_order.get("executed_quantity") or matching_order.get("filled_quantity")
                                live_quantity = matching_order.get("quantity")
                                live_execution_price = matching_order.get("exec_price") or matching_order.get("average_price")
                                live_order_type = matching_order.get("order_type")
                                live_symbol = matching_order.get("symbol") or matching_order.get("tradingsymbol")
                            else:
                                # Generic mapping for other brokers
                                live_executed_quantity = matching_order.get("executed_quantity") or matching_order.get("filled_quantity") or matching_order.get("filledQty")
                                live_quantity = matching_order.get("quantity") or matching_order.get("qty")
                                live_execution_price = matching_order.get("exec_price") or matching_order.get("execution_price") or matching_order.get("average_price") or matching_order.get("tradedPrice")
                                live_order_type = matching_order.get("order_type")
                                live_symbol = matching_order.get("symbol") or matching_order.get("tradingsymbol")
                            
                            # Update executed_quantity if available and different
                            current_executed_qty = be.get('executed_quantity')
                            if live_executed_quantity is not None:
                                try:
                                    if current_executed_qty is None or float(live_executed_quantity) != float(current_executed_qty or 0):
                                        update_fields['executed_quantity'] = live_executed_quantity
                                        update_needed = True
                                        logger.info(f"OrderManager: Executed_quantity update for broker_exec_id={broker_exec_id}: {current_executed_qty} -> {live_executed_quantity}")
                                except Exception as e:
                                    logger.error(f"OrderManager: Error comparing executed_quantity for broker_exec_id={broker_exec_id}: {e}")
                            
                            # Update quantity if available and different
                            current_quantity = be.get('quantity')
                            if live_quantity is not None:
                                try:
                                    if current_quantity is None or float(live_quantity) != float(current_quantity or 0):
                                        update_fields['quantity'] = live_quantity
                                        update_needed = True
                                        logger.info(f"OrderManager: Quantity update for broker_exec_id={broker_exec_id}: {current_quantity} -> {live_quantity}")
                                except Exception as e:
                                    logger.error(f"OrderManager: Error comparing quantity for broker_exec_id={broker_exec_id}: {e}")
                            
                            # Update execution_price if available and different
                            current_exec_price = be.get('execution_price')
                            if live_execution_price is not None:
                                try:
                                    if current_exec_price is None or float(live_execution_price) != float(current_exec_price or 0):
                                        update_fields['execution_price'] = live_execution_price
                                        update_needed = True
                                        logger.info(f"OrderManager: Execution_price update for broker_exec_id={broker_exec_id}: {current_exec_price} -> {live_execution_price}")
                                except Exception as e:
                                    logger.error(f"OrderManager: Error comparing execution_price for broker_exec_id={broker_exec_id}: {e}")
                            
                            # Update order_type if available and different
                            current_order_type = be.get('order_type')
                            if live_order_type is not None and live_order_type != current_order_type:
                                update_fields['order_type'] = live_order_type
                                update_needed = True
                                logger.info(f"OrderManager: Order_type update for broker_exec_id={broker_exec_id}: {current_order_type} -> {live_order_type}")
                            
                            # Update symbol if available and different
                            current_symbol = be.get('symbol')
                            if live_symbol is not None and live_symbol != current_symbol:
                                update_fields['symbol'] = live_symbol
                                update_needed = True
                                logger.info(f"OrderManager: Symbol update for broker_exec_id={broker_exec_id}: {current_symbol} -> {live_symbol}")
                            
                            # Normalize action field if it contains enum values (SIDE.BUY -> BUY)
                            current_action = be.get('action')
                            if current_action:
                                normalized_action = self.normalize_action_field(current_action)
                                
                                # Update if normalization changed the value
                                if normalized_action != str(current_action):
                                    update_fields['action'] = normalized_action
                                    update_needed = True
                                    logger.info(f"OrderManager: Action normalization for broker_exec_id={broker_exec_id}: '{current_action}' -> '{normalized_action}'")
                            
                            # If this is a status transition to FILLED/PARTIAL, set execution_time (only once)
                            # TEMP: Skip execution_time updates during testing (Aug 9, 2025)
                            from datetime import date
                            if date.today() != date(2025, 8, 9):
                                current_execution_time = be.get('execution_time')
                                if (live_broker_status and live_broker_status.upper() in ("FILLED", "PARTIAL", "PARTIALLY_FILLED") and 
                                    status not in ("FILLED", "PARTIAL", "PARTIALLY_FILLED") and 
                                    current_execution_time is None):  # Only set if not already set
                                    from datetime import datetime, timezone
                                    
                                    # Extract execution time from broker data if available, otherwise use current time
                                    execution_time = None
                                    if matching_order and matching_order.get("execution_time"):
                                        execution_time = matching_order.get("execution_time")
                                        logger.info(f"OrderManager: Using broker-provided execution_time: {execution_time}")
                                    else:
                                        execution_time = datetime.now(timezone.utc)
                                        logger.info(f"OrderManager: Using system execution_time (broker time not available): {execution_time}")
                                    
                                    update_fields['execution_time'] = execution_time
                                    update_needed = True
                                    logger.info(f"OrderManager: Setting execution_time for first transition to {live_broker_status}")
                            else:
                                logger.info(f"OrderManager: Skipping execution_time update during testing (Aug 9, 2025)")
                            
                            # Store raw broker data for debugging and future analysis
                            if matching_order:
                                # Convert datetime objects to strings for JSON serialization
                                raw_data = self._serialize_datetime_for_json(matching_order)
                                update_fields['raw_execution_data'] = raw_data
                                update_needed = True
                            
                            if update_needed:
                                logger.info(f"OrderManager: Updating broker_exec_id={broker_exec_id} with comprehensive live data: {list(update_fields.keys())}")
                                
                                # Use update_rows_in_table directly for comprehensive updates
                                from algosat.core.db import AsyncSessionLocal, update_rows_in_table
                                from algosat.core.dbschema import broker_executions
                                
                                # Convert status enum to string if needed
                                if 'status' in update_fields and hasattr(update_fields['status'], 'value'):
                                    update_fields['status'] = update_fields['status'].value
                                elif 'status' in update_fields:
                                    update_fields['status'] = str(update_fields['status'])
                                
                                # Convert Fyers order_type integer to string if needed
                                if 'order_type' in update_fields and broker_name == 'fyers' and isinstance(update_fields['order_type'], int):
                                    update_fields['order_type'] = FYERS_ORDER_TYPE_MAP.get(update_fields['order_type'], str(update_fields['order_type']))
                                    logger.debug(f"OrderManager: Converted Fyers order_type to string for broker_exec_id={broker_exec_id}: {update_fields['order_type']}")
                                
                                async with AsyncSessionLocal() as comprehensive_session:
                                    await update_rows_in_table(
                                        target_table=broker_executions,
                                        condition=broker_executions.c.id == broker_exec_id,
                                        new_values=update_fields
                                    )
                                    logger.info(f"OrderManager: Successfully updated broker_exec_id={broker_exec_id} with {len(update_fields)} fields")
                                
                                # Update the be dictionary with the new values so subsequent operations use updated data
                                for field, value in update_fields.items():
                                    be[field] = value
                                    logger.debug(f"OrderManager: Updated be['{field}'] = {value} for broker_exec_id={broker_exec_id}")
                            else:
                                logger.debug(f"OrderManager: Live data matches DB data for broker_exec_id={broker_exec_id}")
                        else:
                            logger.warning(f"OrderManager: Could not find matching order in broker response for broker_exec_id={broker_exec_id}, using DB status '{status}'")
                    except Exception as e:
                        logger.error(f"OrderManager: Error checking live status for broker_exec_id={broker_exec_id}: {e}, using DB status '{status}'")
                elif check_live_status:
                    logger.warning(f"OrderManager: Live status check requested but broker_name missing for broker_exec_id={broker_exec_id}")
                
                logger.info(f"OrderManager: Processing broker_execution id={broker_exec_id} (broker_id={broker_id}, broker_order_id={broker_order_id}, symbol={symbol}, product_type={product_type}, final_status={status})")
                
                # DECISION LOGIC: Based on final status (potentially updated from live broker data)
                # - FILLED: Call exit_order to close position
                # - PARTIALLY_FILLED: Call exit_order for filled portion + cancel_order for remaining  
                # - PENDING/AWAITING_ENTRY: Call cancel_order to cancel unfilled order
                # - REJECTED/FAILED/CANCELLED: Skip (no action needed)
                
                # Action based on status
                if status in ('REJECTED', 'FAILED', 'CANCELLED'):
                    logger.info(f"OrderManager: Skipping broker_execution id={broker_exec_id} with status={status} (no action needed for exit).")
                    continue
                    
                try:
                    import datetime
                    orig_side_raw = be.get('action') or ''
                    orig_side = self.normalize_action_field(orig_side_raw)
                    
                    logger.debug(f"OrderManager: Action normalization - orig_side_raw='{orig_side_raw}' -> orig_side='{orig_side}'")
                    
                    # TEMP: Skip exit_time updates during testing (Aug 9, 2025)  
                    from datetime import date
                    exit_time = None
                    if date.today() != date(2025, 8, 9):
                        exit_time = datetime.datetime.now(datetime.timezone.utc)
                    else:
                        logger.info(f"OrderManager: Skipping exit_time update during testing (Aug 9, 2025)")
                        
                    if orig_side == 'BUY':
                            exit_action = 'SELL'
                    elif orig_side == 'SELL':
                        exit_action = 'BUY'
                    else:
                        exit_action = 'EXIT'  # Fallback for unknown entry action
                        
                    logger.debug(f"OrderManager: Exit action calculation - orig_side_raw={orig_side_raw}, orig_side={orig_side}, exit_action={exit_action}")
                        
                    if status == 'FILLED':
                        logger.info(f"OrderManager: DECISION → EXIT: Order is FILLED, calling broker exit_order for broker_execution id={broker_exec_id}")
                        logger.info(f"OrderManager: Calling broker_manager.exit_order(broker_id={broker_id}, broker_order_id={cache_lookup_order_id}, symbol={symbol}, product_type={product_type}, exit_reason='{exit_reason}', side={order_side})")
                        
                        # Initialize exit response and order_id variables
                        exit_resp = None
                        exit_broker_order_id = None
                        
                        # Try to execute broker exit call
                        try:
                            exit_resp = await self.broker_manager.exit_order(
                                broker_id,
                                cache_lookup_order_id,
                                symbol=symbol,
                                product_type=product_type,
                                exit_reason=exit_reason,
                                side=order_side
                            )
                            
                            logger.info(f"OrderManager: Exit order response for broker_id={broker_id}, broker_order_id={cache_lookup_order_id}: {exit_resp}")
                            
                            # Extract exit_broker_order_id from response if available (for Zerodha exits)
                            if exit_resp and isinstance(exit_resp, dict):
                                exit_broker_order_id = exit_resp.get('order_id')
                                if exit_broker_order_id:
                                    logger.info(f"OrderManager: Extracted exit_broker_order_id={exit_broker_order_id} from exit response")
                                    
                        except Exception as broker_exit_error:
                            logger.error(f"OrderManager: Broker exit call failed for broker_id={broker_id}, broker_order_id={cache_lookup_order_id}: {broker_exit_error}")
                            # Continue to create EXIT broker_execution entry even if broker exit fails
                        
                        # Always create EXIT broker_execution entry regardless of broker exit success/failure
                        await self._insert_exit_broker_execution(
                            session,
                            parent_order_id=parent_order_id,
                            broker_id=broker_id,
                            broker_order_id=cache_lookup_order_id,
                            side='EXIT',
                            status='PENDING',
                            action = exit_action,
                            executed_quantity=be.get('executed_quantity', 0),
                            quantity=be.get('quantity', be.get('executed_quantity', 0)),  # Use quantity from ENTRY, fallback to executed_quantity
                            # execution_price=ltp or 0.0,  # Will be updated from actual broker response
                            product_type=product_type,  # Use updated product_type from live data
                            order_type='MARKET',
                            order_messages=f"Exit order placed. Reason: {exit_reason}",
                            symbol=symbol,
                            # execution_time=exit_time,  # Will be updated from actual broker response
                            notes=f"Auto exit via OrderManager. Reason: {exit_reason}",
                            exit_broker_order_id=exit_broker_order_id
                        )
                        logger.info(f"OrderManager: Successfully inserted EXIT broker_execution for parent_order_id={parent_order_id}")
                        
                    elif status in ('PARTIALLY_FILLED', 'PARTIAL'):
                        logger.info(f"OrderManager: DECISION → EXIT + CANCEL: Order is PARTIALLY_FILLED, calling exit_order for filled portion and cancel_order for remaining - broker_execution id={broker_exec_id}")
                        logger.info(f"OrderManager: First calling broker_manager.exit_order for partial fill...")
                        
                        exit_resp = await self.broker_manager.exit_order(
                            broker_id,
                            cache_lookup_order_id,
                            symbol=symbol,
                            product_type=product_type,
                            exit_reason=exit_reason
                        )
                        logger.info(f"OrderManager: Exit order response for partial fill: {exit_resp}")
                        
                        # Extract exit_broker_order_id from response if available (for Zerodha exits)
                        exit_broker_order_id = None
                        if exit_resp and isinstance(exit_resp, dict):
                            exit_broker_order_id = exit_resp.get('order_id')
                            if exit_broker_order_id:
                                logger.info(f"OrderManager: Extracted exit_broker_order_id={exit_broker_order_id} from exit response for partial fill")
                        
                        logger.info(f"OrderManager: Now calling broker_manager.cancel_order for remaining quantity...")
                        cancel_resp = await self.broker_manager.cancel_order(
                            broker_id,
                            cache_lookup_order_id,
                            symbol=symbol,
                            product_type=product_type,
                            exit_reason=f"Exit requested for PARTIALLY_FILLED order"
                        )
                        logger.info(f"OrderManager: Cancel order response for partial fill: {cancel_resp}")
                        
                        # Log warning if cancel failed, but continue with EXIT insertion
                        if not self._is_cancel_response_successful(cancel_resp):
                            cancel_error = cancel_resp.get('message', 'Unknown error') if cancel_resp else 'No response received'
                            logger.warning(f"OrderManager: Cancel failed for PARTIALLY_FILLED order broker_exec_id={broker_exec_id}: {cancel_error}. Continuing with exit processing.")
                        
                        await self._insert_exit_broker_execution(
                            session,
                            parent_order_id=parent_order_id,
                            broker_id=broker_id,
                            broker_order_id=cache_lookup_order_id,
                            action = exit_action,
                            side='EXIT',
                            status='PENDING',
                            executed_quantity=be.get('executed_quantity', 0),
                            quantity=be.get('quantity', be.get('executed_quantity', 0)),  # Use quantity from ENTRY, fallback to executed_quantity
                            # execution_price=ltp or 0.0,  # Will be updated from actual broker response
                            product_type=product_type,  # Use updated product_type from live data
                            order_type='MARKET',
                            order_messages=f"Exit and cancel placed for PARTIALLY_FILLED. Reason: {exit_reason}",
                            symbol=symbol,
                            # execution_time=exit_time,  # Will be updated from actual broker response
                            notes=f"Auto exit+cancel via OrderManager. Reason: {exit_reason}",
                            exit_broker_order_id=exit_broker_order_id
                        )
                        logger.info(f"OrderManager: Successfully inserted EXIT broker_execution for PARTIALLY_FILLED order")
                        
                    elif status in ('AWAITING_ENTRY', 'PENDING', 'TRIGGER_PENDING'):
                        logger.info(f"OrderManager: DECISION → CANCEL: Order is {status}, calling cancel_order to cancel unfilled order - broker_execution id={broker_exec_id}")
                        logger.info(f"OrderManager: Calling broker_manager.cancel_order(broker_id={broker_id}, broker_order_id={cache_lookup_order_id}, symbol={symbol}, product_type={product_type})")
                        
                        cancel_resp = await self.broker_manager.cancel_order(
                            broker_id,
                            cache_lookup_order_id,
                            symbol=symbol,
                            product_type=product_type,
                            cancel_reason=f"Exit requested but status was {status}"
                        )
                        logger.info(f"OrderManager: Cancel order response for pending order: {cancel_resp}")
                        
                        # Only update status to CANCELLED if cancel operation succeeded
                        if self._is_cancel_response_successful(cancel_resp):
                            logger.info(f"OrderManager: Cancel successful, updating broker_exec_id={broker_exec_id} status to CANCELLED")
                            await self.update_broker_exec_status_in_db(
                                broker_exec_id=broker_exec_id,
                                status='CANCELLED'
                            )
                        else:
                            cancel_error = cancel_resp.get('message', 'Unknown error') if cancel_resp else 'No response received'
                            logger.warning(f"OrderManager: Cancel failed for broker_exec_id={broker_exec_id}: {cancel_error}. Status will remain {status}.")
                    else:
                        logger.warning(f"OrderManager: Unhandled status '{status}' for broker_execution id={broker_exec_id}. No action taken.")
                        continue
                        
                except Exception as e:
                    logger.error(f"OrderManager: Error exiting/cancelling order for broker_id={broker_id}, broker_order_id={cache_lookup_order_id}, broker_exec_id={broker_exec_id}: {e}")
            
            logger.info(f"OrderManager: Completed exit_order processing for parent_order_id={parent_order_id}. Processed {len(broker_execs)} broker executions.")
            # After all exits, if exit_reason is manual, update order status to EXIT_MANUAL_PENDING
            if exit_reason and exit_reason.lower() == 'manual':
                logger.info(f"OrderManager: Setting order {parent_order_id} status to EXIT_MANUAL_PENDING after manual exit.")
                await self.update_order_status_in_db(parent_order_id, TRADE_STATUS_EXIT_MANUAL_PENDING)
                # send_telegram_async(
                #     f"OrderManager: Order {parent_order_id} marked as EXIT_MANUAL_PENDING after manual exit request."
                # )
            await session.commit()
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
                
                # Update the main order with exit details
            
                
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
            "raw_execution_data": self._serialize_datetime_for_json(raw_execution_data) if raw_execution_data else None,
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
