import asyncio
from typing import Dict, List, Any, Optional
from algosat.core.broker_manager import BrokerManager
from algosat.common.logger import get_logger

logger = get_logger("OrderCache")

class OrderCache:
    def __init__(self, broker_manager: BrokerManager, refresh_interval: float = 60.0):
        self.broker_manager = broker_manager
        self.refresh_interval = refresh_interval
        self._cache: Dict[str, List[dict]] = {}  # broker_name -> list of order dicts
        self._locks: Dict[str, asyncio.Lock] = {}  # broker_name -> lock
        self._update_events: Dict[str, asyncio.Event] = {}  # broker_name -> event
        self._tasks: Dict[str, asyncio.Task] = {}  # broker_name -> background task
        self._running = False

    async def start(self):
        self._running = True
        enabled_brokers = await self.broker_manager.get_all_trade_enabled_brokers()
        for broker_name, broker in enabled_brokers.items():
            if broker_name not in self._locks:
                self._locks[broker_name] = asyncio.Lock()
            if broker_name not in self._update_events:
                self._update_events[broker_name] = asyncio.Event()
            if broker_name not in self._tasks:
                self._tasks[broker_name] = asyncio.create_task(self._refresh_broker_orders(broker_name, broker))

    async def stop(self):
        self._running = False
        for task in self._tasks.values():
            task.cancel()
        self._tasks.clear()

    async def _refresh_broker_orders(self, broker_name: str, broker):
        while self._running:
            lock = self._locks[broker_name]
            event = self._update_events[broker_name]
            async with lock:
                try:
                    orders = broker.get_order_details()
                    # Recursively await if orders is a coroutine
                    while asyncio.iscoroutine(orders):
                        orders = await orders
                    self._cache[broker_name] = orders
                    logger.debug(f"OrderCache updated for {broker_name} with {len(orders)} orders.")
                except Exception as e:
                    logger.error(f"OrderCache failed to update for {broker_name}: {e}")
                finally:
                    event.set()  # Signal update complete
                    event.clear()
            await asyncio.sleep(self.refresh_interval)

    async def get_orders(self, broker_name: str) -> List[dict]:
        lock = self._locks.get(broker_name)
        event = self._update_events.get(broker_name)
        if lock is None or event is None:
            raise RuntimeError(f"OrderCache not started or broker {broker_name} not enabled.")
        # Wait if update in progress
        while lock.locked():
            await event.wait()
        return self._cache.get(broker_name, [])

    async def get_order_by_id(self, broker_name: str, order_id: Any) -> Optional[dict]:
        orders = await self.get_orders(broker_name)
        for order in orders:
            if str(order.get("id")) == str(order_id) or str(order.get("order_id")) == str(order_id):
                return order
        return None
