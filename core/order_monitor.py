from __future__ import annotations
from typing import Optional, Any
import asyncio
from datetime import datetime
from algosat.common.logger import get_logger
from algosat.models.order_aggregate import OrderAggregate

from algosat.core.data_manager import DataManager
from algosat.core.order_manager import OrderManager
from algosat.core.order_cache import OrderCache
from algosat.core.order_request import OrderStatus
from algosat.common.strategy_utils import wait_for_next_candle, fetch_strikes_history

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
        # Use OrderStatus from order_request.py
        while self._running:
            try:
                agg: OrderAggregate = await self.data_manager.get_order_aggregate(self.order_id)
            except Exception as e:
                logger.error(f"OrderMonitor: Error in get_order_aggregate for order_id={self.order_id}: {e}")
                await asyncio.sleep(self.fast_interval)
                continue
            all_order_statuses = []  # Flattened list of all broker order statuses
            failed_statuses = {OrderStatus.REJECTED.value, OrderStatus.FAILED.value}
            for bro in agg.broker_orders:
                bro_status_str = bro.status.value if hasattr(bro.status, 'value') else str(bro.status).split('.')[-1]
                if bro_status_str in failed_statuses:
                    logger.info(f"OrderMonitor: Updating order_id={self.order_id} to FAILED due to broker_exec status {bro.status} (broker_id={bro.broker_id})")
                    await self.order_manager.update_order_status_in_db(self.order_id, OrderStatus.FAILED)
                    self.stop()
                    return
            for bro in agg.broker_orders:
                try:
                    broker_name = await self.data_manager.get_broker_name_by_id(bro.broker_id)
                    order_ids = bro.order_id if isinstance(bro.order_id, list) else [bro.order_id]
                    for oid in order_ids:
                        if not oid:
                            continue
                        order_details = await self.order_cache.get_order_by_id(broker_name, oid)
                        status = order_details.get("status") if order_details else None
                        if status is not None:
                            all_order_statuses.append(status)
                except Exception as e:
                    logger.error(f"OrderMonitor: Error fetching order details for broker_id={bro.broker_id}: {e}")
            def status_str(s):
                return s.value if hasattr(s, 'value') else str(s).split('.')[-1]
            # Set logical order to OPEN if any order is FILLED or PARTIALLY_FILLED
            if all_order_statuses and any(status_str(s) in [OrderStatus.FILLED.value, OrderStatus.PARTIALLY_FILLED.value] for s in all_order_statuses):
                await self.order_manager.update_order_status_in_db(self.order_id, OrderStatus.OPEN)
            # Set to FILLED only if all are FILLED
            if all_order_statuses and all(status_str(s) == OrderStatus.FILLED.value for s in all_order_statuses):
                await self.order_manager.update_order_status_in_db(self.order_id, OrderStatus.FILLED)
            # Set to PARTIALLY_FILLED if any are PARTIALLY_FILLED (but not all FILLED)
            elif any(status_str(s) == OrderStatus.PARTIALLY_FILLED.value for s in all_order_statuses):
                await self.order_manager.update_order_status_in_db(self.order_id, OrderStatus.PARTIALLY_FILLED)
            elif any(status_str(s) == OrderStatus.REJECTED.value for s in all_order_statuses):
                await self.order_manager.update_order_status_in_db(self.order_id, OrderStatus.REJECTED)
            elif any(status_str(s) == OrderStatus.CANCELLED.value for s in all_order_statuses):
                await self.order_manager.update_order_status_in_db(self.order_id, OrderStatus.CANCELLED)
            try:
                ltp = await self.data_manager.get_ltp(agg.symbol)
            except Exception as e:
                logger.error(f"OrderMonitor: Error in get_ltp for symbol={agg.symbol}, order_id={self.order_id}: {e}")
                ltp = None
            try:
                history = await self.data_manager.fetch_history(
                    agg.symbol,
                    interval_minutes=getattr(self.strategy, "entry_interval", 1),
                    lookback=getattr(self.strategy, "exit_lookback", 1) + 1
                )
            except Exception as e:
                logger.error(f"OrderMonitor: Error in fetch_history for symbol={agg.symbol}, order_id={self.order_id}: {e}")
                history = None
            self.strategy.update_trailing_stop_loss(self.order_id, ltp, history, self.order_manager)
            if ltp is not None:
                try:
                    exit_req = await self.strategy.evaluate_price_exit(self.order_id, ltp)
                except Exception as e:
                    logger.error(f"OrderMonitor: Error in evaluate_price_exit for order_id={self.order_id}: {e}")
                    exit_req = None
                if exit_req:
                    await self.order_manager.place_order(exit_req, strategy_name=self.strategy.name)
                    self.stop()
                    return
            await wait_for_next_candle(self.fast_interval_minutes)

    async def _slow_monitor(self) -> None:
        while self._running:
            try:
                agg: OrderAggregate = await self.data_manager.get_order_aggregate(self.order_id)
            except Exception as e:
                logger.error(f"OrderMonitor: Error in get_order_aggregate (slow) for order_id={self.order_id}: {e}")
                await asyncio.sleep(self.entry_interval)
                continue
            try:
                history = await self.data_manager.fetch_history(
                    agg.symbol,
                    interval_minutes=getattr(self.strategy, "entry_interval", 1),
                    lookback=getattr(self.strategy, "exit_lookback", 1) + 1
                )
            except Exception as e:
                logger.error(f"OrderMonitor: Error in fetch_history (slow) for symbol={agg.symbol}, order_id={self.order_id}: {e}")
                history = None
            try:
                ltp = await self.data_manager.get_ltp(agg.symbol)
            except Exception as e:
                logger.error(f"OrderMonitor: Error in get_ltp (slow) for symbol={agg.symbol}, order_id={self.order_id}: {e}")
                ltp = None
            self.strategy.update_trailing_stop_loss(self.order_id, ltp, history, self.order_manager)
            try:
                exit_req = await self.strategy.evaluate_candle_exit(self.order_id, history)
            except Exception as e:
                logger.error(f"OrderMonitor: Error in evaluate_candle_exit for order_id={self.order_id}: {e}")
                exit_req = None
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
