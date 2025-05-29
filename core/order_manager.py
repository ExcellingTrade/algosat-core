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

logger = get_logger("OrderManager")

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
        OrderManager is not responsible for broker selection or looping; BrokerManager handles all broker logic.

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

        # Delegate to BrokerManager for actual broker routing and placement
        try:
            broker_manager = self.broker_manager
            broker_responses = await broker_manager.place_order(order_payload, strategy_name=strategy_name)
        except Exception as e:
            logger.error(f"BrokerManager.place_order failed: {e}", exc_info=True)
            broker_responses = {"error": str(e)}

        # After broker responses, insert order(s) into DB with broker info
        # (This replaces the pre-broker DB insert logic)
        inserted_order_ids = []
        broker_to_local_id = {}
        for broker_name, response in broker_responses.items():
            # Only insert if broker attempted execution
            if response and isinstance(response, dict):
                # Always pass OrderRequest and models, never dicts, to DB insert
                order_id = await self._insert_and_get_order_id(
                    config=config,
                    order_payload=order_payload,
                    broker_name=broker_name,
                    result=response,
                    parent_order_id=None
                )
                if order_id:
                    inserted_order_ids.append(order_id)
                    broker_to_local_id[broker_name] = order_id
        # Set parent_order_id: use the first inserted id as parent for all
        if inserted_order_ids:
            parent_id = inserted_order_ids[0]
            # Update all orders (including the first) to have parent_order_id = parent_id
            for oid in inserted_order_ids:
                await self._set_parent_order_id(oid, parent_id)
        return {
            "overall_status": "success" if any(r.get("status") in ("success", True) for r in broker_responses.values()) else "error",
            "message": f"Order placement attempted via BrokerManager.",
            "broker_responses": broker_responses,
            "local_order_ids": inserted_order_ids,
            "parent_order_id": inserted_order_ids[0] if inserted_order_ids else None
        }

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

        async with AsyncSessionLocal() as sess:
            broker_id = None
            if broker_name:
                broker_row = await get_broker_by_name(sess, broker_name)
                broker_id = broker_row["id"] if broker_row else None
            else:
                brokers = await get_trade_enabled_brokers(sess)
                if brokers:
                    broker_id = brokers[0]["id"]
            strategy_config_id = config.id if isinstance(config, StrategyConfig) else self.extract_strategy_config_id(config)
            if not strategy_config_id:
                logger.error(f"[OrderManager] Could not extract strategy_config_id from config: {repr(config)}. Order will not be inserted.")
                return None

            # --- Build order_data from OrderRequest and broker result ---
            order_data = {
                "strategy_config_id": to_native(strategy_config_id),
                "broker_id": to_native(broker_id),
                "parent_order_id": parent_order_id,
                "symbol": order_payload.symbol,
                "qty": order_payload.quantity,
                "lot_qty": order_payload.quantity,
                "side": order_payload.side.value if isinstance(order_payload.side, Side) else str(order_payload.side),
                "order_ids": json.dumps([]),
                "order_messages": json.dumps({}),
            }
            # Core fields from OrderRequest
            if order_payload.price is not None:
                order_data["entry_price"] = to_native(order_payload.price)
            if order_payload.trigger_price is not None:
                order_data["trigger_price"] = to_native(order_payload.trigger_price)
            # Extra fields from OrderRequest.extra
            extra_data = order_payload.extra if order_payload.extra else {}
            for k in [
                "candle_range", "entry_price", "stop_loss", "target_price", "profit", "signal_time", "entry_time", "exit_time", "exit_price", "status", "reason", "atr", "supertrend_signal", "lot_qty"]:
                v = extra_data.get(k)
                if v is not None:
                    order_data[k] = to_native(v)
            # --- Broker result: order_ids and order_messages ---
            order_ids = []
            order_messages = {}
            raw_response = None
            if result:
                # Accept both canonical OrderResponse and dict
                ids = result.get("order_ids")
                if ids:
                    order_ids = [str(i) for i in ids]
                msgs = result.get("order_messages")
                if msgs:
                    order_messages = {str(k): str(v) for k, v in msgs.items()}
                # If there are failed/success for each orderid, ensure all are present
                # If only error, put under 'error' key
                if not order_ids and not order_messages and result.get("status") == "FAILED":
                    msg = result.get("message") or result.get("raw_response") or "Broker returned error"
                    order_messages = {"error": str(msg)}
                # If partial, ensure all orderids have a message
                if order_ids and order_messages:
                    for oid in order_ids:
                        if oid not in order_messages:
                            order_messages[oid] = "Order placed"
                # --- Store full broker API payload(s) ---
                if "raw_response" in result:
                    raw_response = result["raw_response"]
                else:
                    raw_response = result
            order_data["order_ids"] = json.dumps(order_ids)
            order_data["order_messages"] = json.dumps(order_messages)
            order_data["raw_response"] = raw_response
            # Status
            if result and result.get("status"):
                order_data["status"] = str(result.get("status"))
            else:
                order_data["status"] = to_native(extra_data.get("status", "AWAITING_ENTRY"))
            # Final check for side, ensuring it's a string like "BUY" or "SELL" (DB expects string, not Side enum)
            if isinstance(order_data.get("side"), Side):
                order_data["side"] = order_data["side"].value
            elif isinstance(order_data.get("side"), str):
                # Accept only 'BUY' or 'SELL', else fallback to error
                side_str = order_data["side"].upper()
                if side_str in ("BUY", "SELL"):
                    order_data["side"] = side_str
                else:
                    logger.error(f"Invalid side value for DB insert: {order_data['side']}")
                    order_data["side"] = "BUY"  # fallback or raise error
            else:
                logger.error(f"Side value is not a string or Side enum: {order_data['side']}")
                order_data["side"] = "BUY"  # fallback or raise error
            # Remove unconsumed columns for DB insert
            if "order_type" in order_data:
                del order_data["order_type"]
            inserted = await insert_order(sess, order_data)
            return inserted["id"] if inserted else None

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
                new_values={"status": status}
            )
            logger.debug(f"Order {order_id} status updated to {status} in DB.")

_order_manager_instance = None

def get_order_manager(broker_manager: BrokerManager) -> OrderManager:
    global _order_manager_instance
    # Ensure BrokerManager is passed for the first instantiation
    # or if the existing instance was created with a different broker_manager (though this simple version doesn't check that)
    if _order_manager_instance is None or _order_manager_instance.broker_manager != broker_manager:
        _order_manager_instance = OrderManager(broker_manager)
    return _order_manager_instance
