import asyncio
from datetime import datetime
from algosat.common.logger import get_logger

logger = get_logger("OrderMonitor")

class OrderMonitor:
    def __init__(self, order_id, data_manager, order_manager):
        self.order_id = order_id
        self.data_manager = data_manager
        self.order_manager = order_manager
        self._running = True
        self._last_status = None
        # Order details (populated by fetch_order_details)
        self.strike = None
        self.broker_id = None
        self.broker_name = None
        self.strategy_config_id = None
        self.interval_minutes = None
        self.stop_loss = None
        self.target_price = None
        self.trade = None

    async def fetch_order_details(self):
        """
        Fetch full order row (with broker info) for this order_id.
        """
        from algosat.core.db import AsyncSessionLocal, get_order_by_id, get_strategy_config_by_id, get_broker_by_name
        async with AsyncSessionLocal() as session:
            order = await get_order_by_id(session, self.order_id)
            if order:
                self.strike = order.get("symbol")
                self.broker_id = order.get("broker_id")
                self.strategy_config_id = order.get("strategy_config_id")
                self.stop_loss = order.get("stop_loss")
                self.target_price = order.get("target_price")
                # Optionally fetch broker_name
                if self.broker_id:
                    # You may want a helper to get broker_name by id
                    from algosat.core.dbschema import broker_credentials
                    result = await session.execute(broker_credentials.select().where(broker_credentials.c.id == self.broker_id))
                    row = result.first()
                    if row:
                        self.broker_name = row["broker_name"]
                # Fetch config/trade info for interval_minutes
                if self.strategy_config_id:
                    config = await get_strategy_config_by_id(session, self.strategy_config_id)
                    self.trade = config.get("trade") if config else None
                    if self.trade and isinstance(self.trade, dict):
                        self.interval_minutes = self.trade.get("interval_minutes", 5)
                    else:
                        self.interval_minutes = 5

    async def fast_monitor(self):
        while self._running:
            try:
                status = await self.order_manager.get_order_status(self.order_id)
                if status != self._last_status:
                    await self.order_manager.update_order_status_in_db(self.order_id, status)
                    self._last_status = status
                if status == "OPEN":
                    price = await self.data_manager.get_ltp(self.strike, self.order_id)
                    if price is not None:
                        if self.stop_loss is not None and price <= self.stop_loss:
                            logger.info(f"Order {self.order_id}: Price {price} hit stoploss {self.stop_loss}, cancelling order.")
                            await self.order_manager.cancel_order(self.order_id)
                        elif self.target_price is not None and price >= self.target_price:
                            logger.info(f"Order {self.order_id}: Price {price} hit target {self.target_price}, cancelling order.")
                            await self.order_manager.cancel_order(self.order_id)
            except Exception as e:
                logger.error(f"OrderMonitor fast_monitor error: {e}")
            await asyncio.sleep(60)

    async def slow_monitor(self):
        while self._running:
            try:
                from algosat.common.strategy_utils import fetch_strikes_history
                if not self.strike:
                    logger.error(f"OrderMonitor slow_monitor: strike is None for order_id={self.order_id}")
                    await asyncio.sleep(self.interval_minutes * 60)
                    continue
                interval_minutes = self.interval_minutes or 5
                from datetime import time, timedelta
                from algosat.core.time_utils import get_ist_datetime, localize_to_ist, calculate_end_date
                from algosat.common.broker_utils import get_trade_day
                from algosat.common.strategy_utils import calculate_backdate_days
                current_date = get_ist_datetime()
                back_days = calculate_backdate_days(interval_minutes)
                trade_day = get_trade_day(current_date - timedelta(days=back_days))
                start_date = datetime.combine(trade_day, time(9, 15))
                current_end_date = datetime.combine(localize_to_ist(current_date), get_ist_datetime().time())
                end_date = calculate_end_date(current_end_date, interval_minutes)
                end_date = end_date.replace(hour=9, minute=40, second=0, microsecond=0)
                history_data = await fetch_strikes_history(
                    self.data_manager,
                    [self.strike],
                    from_date=start_date,
                    to_date=end_date,
                    interval_minutes=interval_minutes,
                    ins_type="",
                    cache=False
                )
                logger.debug(f"OrderMonitor slow_monitor: Fetched history data for {self.strike} from {start_date} to {end_date} len={len(history_data.get(self.strike, []))}")
                # if not history_data or self.strike not in history_data:
                # Here you can add custom logic to evaluate the fetched history data
                # 2. Evaluate exit conditions (custom logic can be added here)
                # 3. Cancel order if needed (example: custom exit condition)
                # ...
            except Exception as e:
                logger.error(f"OrderMonitor slow_monitor error: {e}")
            await asyncio.sleep(self.interval_minutes * 60)

    async def start(self):
        # Fetch all order details before monitoring
        await self.fetch_order_details()
        logger.debug(f"Monitoring order_id={self.order_id} for strike={self.strike}, broker={self.broker_name}, interval_minutes={self.interval_minutes}")
        await asyncio.gather(self.fast_monitor(), self.slow_monitor())

    def stop(self):
        self._running = False
