# core/order_manager.py
"""
OrderManager: Responsible for managing the lifecycle of orders across all brokers that are trade enabled and live/authenticated.
"""
from core.db import get_trade_enabled_brokers
from brokers.factory import get_broker
from common.logger import get_logger
from core.dbschema import trade_logs
from core.db import AsyncSessionLocal
from sqlalchemy import insert
from core.broker_manager import BrokerManager
from core.order_request import OrderRequest
from models.strategy_config import StrategyConfig
import json

logger = get_logger("OrderManager")

class OrderManager:
    def __init__(self, broker_manager: BrokerManager):
        self.broker_manager: BrokerManager = broker_manager

    @staticmethod
    def extract_strategy_config_id(config):
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

    async def place_order(self, config, order_payload, strategy_name=None):
        """
        Place order in all brokers that are trade enabled and live/authenticated.
        Delegates all broker-specific logic to BrokerManager.
        Returns a dict of broker_name -> order result.
        """
        # If order_payload is an OrderRequest, pass as is; else, raise error
        if not isinstance(order_payload, OrderRequest):
            raise ValueError("order_payload must be an OrderRequest instance")
        results = await self.broker_manager.place_order(order_payload, strategy_name=strategy_name)
        # Update DB for each order placed
        for broker_name, resp in results.items():
            if isinstance(resp, list):
                for r in resp:
                    await self.update_order_in_db(config, order_payload, broker_name, r)
            else:
                await self.update_order_in_db(config, order_payload, broker_name, resp)
        return results

    @staticmethod
    async def split_and_place_order(broker, total_qty, max_nse_qty, trigger_price_diff, **order_params):
        """
        Split the order into chunks if the quantity exceeds max_nse_qty.
        :param broker: Broker instance
        :param total_qty: Total quantity to be ordered.
        :param max_nse_qty: Maximum quantity allowed per order.
        :param trigger_price_diff: Trigger price diff
        :param order_params: Parameters for the order.
        :return: List of responses for each placed order.
        """
        responses = []
        original_price = order_params.get("limitPrice", 0)
        max_price_increase = 2.00
        price_increment = 0.20
        current_price = original_price
        order_type = order_params.get("type", 4)
        while total_qty > 0:
            qty = min(total_qty, max_nse_qty)
            order_params["qty"] = qty
            if order_type != 2:
                order_params["limitPrice"] = current_price
                order_params["stopPrice"] = current_price - trigger_price_diff
            if (current_price - original_price) < max_price_increase:
                current_price = min(original_price + max_price_increase, current_price + price_increment)
            logger.debug(f"Placing split order {order_params}")
            response = await broker.place_order(order_params)
            responses.append(response)
            total_qty -= qty
        return responses

    async def update_order_in_db(self, config, order_payload, broker_name, result):
        """
        Update order details to orders table in DB using db.py abstraction.
        Called from place_order, so status is set to 'AWAITING_ENTRY'.
        Ensures all values are native Python types (no numpy types, enums, etc.).
        """
        from core.db import insert_order, AsyncSessionLocal, get_broker_by_name
        import numpy as np
        def to_native(val):
            if isinstance(val, np.generic):
                return val.item()
            if hasattr(val, 'value'):
                return val.value
            if hasattr(val, 'name'):
                return val.name
            return val
        async with AsyncSessionLocal() as sess:
            broker_row = await get_broker_by_name(sess, broker_name)
            broker_id = broker_row["id"] if broker_row else None
            strategy_config_id = self.extract_strategy_config_id(config)
            if not strategy_config_id:
                logger.error(f"[OrderManager] Could not extract strategy_config_id from config: {repr(config)}. Skipping DB insert.")
                strategy_config_id = 3
            if isinstance(order_payload, OrderRequest):
                order_payload_dict = order_payload.to_dict()
            else:
                order_payload_dict = order_payload
            # Convert all values to native types
            order_data = {
                "strategy_config_id": to_native(strategy_config_id),
                "broker_id": to_native(broker_id),
                "symbol": to_native(order_payload_dict.get("symbol")),
                "candle_range": to_native(order_payload_dict.get("candle_range")),
                "entry_price": to_native(order_payload_dict.get("price")),
                "stop_loss": to_native(order_payload_dict.get("extra", {}).get("stopLoss")),
                "target_price": to_native(order_payload_dict.get("extra", {}).get("takeProfit")),
                "signal_time": to_native(order_payload_dict.get("signal_time")),
                "entry_time": to_native(order_payload_dict.get("entry_time")),
                "exit_time": to_native(order_payload_dict.get("exit_time")),
                "exit_price": to_native(order_payload_dict.get("exit_price")),
                "status": "AWAITING_ENTRY",
                "reason": to_native(order_payload_dict.get("reason")),
                "atr": to_native(order_payload_dict.get("atr")),
                "supertrend_signal": to_native(order_payload_dict.get("supertrend_signal")),
                "lot_qty": to_native(order_payload_dict.get("quantity")),
                "side": to_native(order_payload_dict.get("side")),
                "order_ids": json.dumps(order_payload_dict.get("order_ids", [])),
                "order_messages": json.dumps(order_payload_dict.get("order_messages", {})),
            }
            await insert_order(sess, order_data)

    async def get_broker_symbol(self, broker_name, symbol, instrument_type=None):
        """
        Returns the correct symbol/token for the given broker using BrokerManager.get_symbol_info.
        """
        return await self.broker_manager.get_symbol_info(broker_name, symbol, instrument_type)

def get_order_manager(broker_manager):
    return OrderManager(broker_manager)
