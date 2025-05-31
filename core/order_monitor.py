from __future__ import annotations
from typing import Optional, Any
import asyncio
from datetime import datetime
from algosat.common.logger import get_logger
from algosat.models.order_aggregate import OrderAggregate

from algosat.core.data_manager import DataManager
from algosat.core.order_manager import OrderManager
from algosat.core.order_cache import OrderCache

logger = get_logger("OrderMonitor")

class OrderMonitor:
    def __init__(
        self,
        order_id: int,
        strategy: Any,
        data_manager: DataManager,
        order_manager: OrderManager,
        order_cache: OrderCache,  # new dependency
        fast_interval: float = 60.0
    ):
        self.order_id: int = order_id
        self.strategy: Any = strategy
        self.data_manager: DataManager = data_manager
        self.order_manager: OrderManager = order_manager
        self.order_cache: OrderCache = order_cache
        self.fast_interval: float = fast_interval
        self.monitor_interval: float = getattr(strategy, "monitor_interval", 1) * 60
        self.entry_interval: float = getattr(strategy, "entry_interval", 1) * 60
        self._running: bool = True

    async def _fast_monitor(self) -> None:
        while self._running:
            # Load aggregated order data
            agg: OrderAggregate = await self.data_manager.get_order_aggregate(self.order_id)
            for bro in agg.broker_orders:
                # Use order_cache to get order details
                broker_name = self.data_manager.get_broker_name_by_id(bro.broker_id)  # You may need to implement this
                order_details = await self.order_cache.get_order_by_id(broker_name, bro.order_id)
                resp = order_details.get("status") if order_details else None
                await self.data_manager.update_order_status(self.order_id, bro.broker_id, resp)
            # Let strategy decide exit based on latest price
            ltp = await self.data_manager.get_ltp(agg.symbol, self.order_id)
            if ltp is not None:
                exit_req = await self.strategy.evaluate_price_exit(self.order_id, ltp)
                if exit_req:
                    await self.order_manager.place_order(exit_req, strategy_name=self.strategy.name)
                    self.stop()
                    return
            await asyncio.sleep(self.fast_interval)

    async def _slow_monitor(self) -> None:
        while self._running:
            agg: OrderAggregate = await self.data_manager.get_order_aggregate(self.order_id)
            history = await self.data_manager.fetch_history(
                agg.symbol,
                interval_minutes=getattr(self.strategy, "entry_interval", 1),
                lookback=getattr(self.strategy, "exit_lookback", 1) + 1
            )
            exit_req = await self.strategy.evaluate_candle_exit(self.order_id, history)
            if exit_req:
                await self.order_manager.place_order(exit_req, strategy_name=self.strategy.name)
                self.stop()
                return
            await asyncio.sleep(self.entry_interval)

    async def start(self) -> None:
        logger.debug(f"Starting monitor for order_id={self.order_id} on symbol={{await self.data_manager.get_symbol(self.order_id)}}")
        await asyncio.gather(self._fast_monitor(), self._slow_monitor())

    def stop(self) -> None:
        self._running = False
