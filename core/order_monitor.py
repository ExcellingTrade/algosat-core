from __future__ import annotations
from typing import Optional, Any
import asyncio
from datetime import datetime
from algosat.common.logger import get_logger
from algosat.models.order_aggregate import OrderAggregate

from algosat.core.data_manager import DataManager
from algosat.core.order_manager import OrderManager
from algosat.core.order_cache import OrderCache
from algosat.common.strategy_utils import wait_for_next_candle

logger = get_logger("OrderMonitor")

class OrderMonitor:
    def __init__(
        self,
        order_id: int,
        strategy: Any,
        data_manager: DataManager,
        order_manager: OrderManager,
        order_cache: OrderCache,  # new dependency
        fast_interval: float = 60.0,
        fast_interval_minutes: int = 1  # new: candle timeframe in minutes
    ):
        self.order_id: int = order_id
        self.strategy: Any = strategy
        self.data_manager: DataManager = data_manager
        self.order_manager: OrderManager = order_manager
        self.order_cache: OrderCache = order_cache
        self.fast_interval: float = fast_interval
        self.fast_interval_minutes: int = fast_interval_minutes
        self.monitor_interval: float = getattr(strategy, "monitor_interval", 1) * 60
        self.entry_interval: float = getattr(strategy, "entry_interval", 1) * 60
        self._running: bool = True

    async def _fast_monitor(self) -> None:
        from algosat.core.order_manager import OrderStatusEnum
        while self._running:
            # Load aggregated order data
            agg: OrderAggregate = await self.data_manager.get_order_aggregate(self.order_id)
            broker_statuses = []
            # Check for any broker_execs in failed state before checking order_ids
            failed_statuses = {OrderStatusEnum.REJECTED, OrderStatusEnum.FAILED}
            for bro in agg.broker_orders:
                if bro.status in failed_statuses:
                    logger.info(f"OrderMonitor: Updating order_id={self.order_id} to FAILED due to broker_exec status {bro.status} (broker_id={bro.broker_id})")
                    await self.order_manager.update_order_status_in_db(self.order_id, OrderStatusEnum.FAILED)
                    self.stop()
                    return
            for bro in agg.broker_orders:
                broker_name = await self.data_manager.get_broker_name_by_id(bro.broker_id)
                order_details = await self.order_cache.get_order_by_id(broker_name, bro.order_id)
                status = order_details.get("status") if order_details else None
                broker_statuses.append(status)
            # Aggregate status logic
            if broker_statuses and all(s == OrderStatusEnum.FILLED for s in broker_statuses):
                await self.order_manager.update_order_status_in_db(self.order_id, OrderStatusEnum.FILLED)
            elif any(s == OrderStatusEnum.PARTIALLY_FILLED for s in broker_statuses):
                await self.order_manager.update_order_status_in_db(self.order_id, OrderStatusEnum.PARTIALLY_FILLED)
            elif any(s == OrderStatusEnum.REJECTED for s in broker_statuses):
                await self.order_manager.update_order_status_in_db(self.order_id, OrderStatusEnum.REJECTED)
            elif any(s == OrderStatusEnum.CANCELLED for s in broker_statuses):
                await self.order_manager.update_order_status_in_db(self.order_id, OrderStatusEnum.CANCELLED)
            # Let strategy decide exit based on latest price
            ltp = await self.data_manager.get_ltp(agg.symbol, self.order_id)
            if ltp is not None:
                exit_req = await self.strategy.evaluate_price_exit(self.order_id, ltp)
                if exit_req:
                    await self.order_manager.place_order(exit_req, strategy_name=self.strategy.name)
                    self.stop()
                    return
            await wait_for_next_candle(self.fast_interval_minutes)

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
