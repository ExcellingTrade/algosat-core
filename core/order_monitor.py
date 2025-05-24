import asyncio
from datetime import datetime
from common.logger import get_logger

logger = get_logger("OrderMonitor")

class OrderMonitor:
    def __init__(self, order_id, config, data_manager, order_manager, interval_minutes):
        self.order_id = order_id
        self.config = config
        self.data_manager = data_manager
        self.order_manager = order_manager
        self.interval_minutes = interval_minutes
        self._running = True
        self._last_status = None

    async def fast_monitor(self):
        while self._running:
            try:
                # 1. Check order status
                status = await self.order_manager.get_order_status(self.order_id)
                if status != self._last_status:
                    # 2. If status changed, update DB
                    await self.order_manager.update_order_status_in_db(self.order_id, status)
                    self._last_status = status
                # 3. If open, fetch price, check stoploss/target, cancel if needed
                if status == "OPEN":
                    price = await self.data_manager.get_ltp(self.config, self.order_id)
                    stoploss = self.config.get("stop_loss")
                    target = self.config.get("target_price")
                    if price is not None:
                        if stoploss is not None and price <= stoploss:
                            logger.info(f"Order {self.order_id}: Price {price} hit stoploss {stoploss}, cancelling order.")
                            await self.order_manager.cancel_order(self.order_id)
                        elif target is not None and price >= target:
                            logger.info(f"Order {self.order_id}: Price {price} hit target {target}, cancelling order.")
                            await self.order_manager.cancel_order(self.order_id)
            except Exception as e:
                logger.error(f"OrderMonitor fast_monitor error: {e}")
            await asyncio.sleep(60)

    async def slow_monitor(self):
        while self._running:
            try:
                # 1. Fetch history
                history = await self.data_manager.get_history(self.config, self.order_id)
                # 2. Evaluate exit conditions (custom logic can be added here)
                # 3. Cancel order if needed (example: custom exit condition)
                # ...
            except Exception as e:
                logger.error(f"OrderMonitor slow_monitor error: {e}")
            await asyncio.sleep(self.interval_minutes * 60)

    async def start(self):
        await asyncio.gather(self.fast_monitor(), self.slow_monitor())

    def stop(self):
        self._running = False
