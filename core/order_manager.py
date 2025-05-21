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

logger = get_logger("OrderManager")

class OrderManager:
    def __init__(self, broker_manager):
        self.broker_manager = broker_manager

    async def place_order(self, config, order_payload):
        """
        Place order in all brokers that are trade enabled and live/authenticated.
        Returns a dict of broker_name -> order result.
        """
        brokers = await self.broker_manager.get_active_trade_brokers()
        results = {}
        for broker_name, broker in brokers.items():
            if not broker:
                logger.warning(f"Broker {broker_name} not found or not live in broker_manager.")
                results[broker_name] = {"status": False, "message": "Broker not found or not live"}
                continue
            try:
                result = await broker.place_order(order_payload)
                results[broker_name] = result
                await self.update_order_in_db(config, order_payload, broker_name, result)
            except Exception as e:
                logger.error(f"Order placement failed for {broker_name}: {e}")
                results[broker_name] = {"status": False, "message": str(e)}
        return results

    async def update_order_in_db(self, config, order_payload, broker_name, result):
        """
        Update order details to trade_logs table in DB.
        """
        async with AsyncSessionLocal() as sess:
            stmt = insert(trade_logs).values(
                config_id=config.get("id") if isinstance(config, dict) else getattr(config, "id", None),
                order_type=order_payload.get("order_type"),
                qty=order_payload.get("qty"),
                price=order_payload.get("price"),
                status=result.get("status"),
                raw_response=result,
            )
            await sess.execute(stmt)
            await sess.commit()

def get_order_manager(broker_manager):
    return OrderManager(broker_manager)
