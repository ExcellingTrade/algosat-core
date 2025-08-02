import asyncio
from typing import Dict, List, Any, Optional
from collections import defaultdict
from algosat.common.logger import get_logger
from algosat.core.order_manager import OrderManager

logger = get_logger("OrderCache")

class OrderCache:
    def __init__(self, order_manager: OrderManager, refresh_interval: float = 60.0):
        self.order_manager = order_manager
        self.refresh_interval = refresh_interval
        self._cache: Dict[str, List[dict]] = {}  # broker_name -> list of order dicts
        self._locks: Dict[str, asyncio.Lock] = {}  # broker_name -> lock
        self._update_events: Dict[str, asyncio.Event] = {}  # broker_name -> event
        self._tasks: Dict[str, asyncio.Task] = {}  # broker_name -> background task
        self._running = False

    async def start(self):
        self._running = True
        broker_orders = await self.order_manager.get_all_broker_order_details()
        # broker_orders = defaultdict(list)
        # for order in broker_orders_list:
        #     broker_orders[order["broker_name"]].append(order)
        # Always initialize for all enabled brokers, even if no orders yet
        for broker_name in broker_orders.keys():
            if broker_name not in self._locks:
                self._locks[broker_name] = asyncio.Lock()
            if broker_name not in self._update_events:
                self._update_events[broker_name] = asyncio.Event()
            if broker_name not in self._tasks:
                self._tasks[broker_name] = asyncio.create_task(self._refresh_broker_orders(broker_name))

    async def stop(self):
        self._running = False
        for task in self._tasks.values():
            task.cancel()
        self._tasks.clear()

    async def _refresh_broker_orders(self, broker_name: str):
        while self._running:
            lock = self._locks[broker_name]
            event = self._update_events[broker_name]
            async with lock:
                try:
                    broker_orders= await self.order_manager.get_all_broker_order_details()
                    # broker_orders = defaultdict(list)
                    # for order in broker_orders_list:
                        # broker_orders[order["broker_name"]].append(order)
                    orders = broker_orders.get(broker_name, [])
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
            logger.error(f"OrderCache not started or broker {broker_name} not enabled.")
            raise RuntimeError(f"OrderCache not started or broker {broker_name} not enabled.")
        try:
            # Wait if update in progress
            while lock.locked():
                await event.wait()
            return self._cache.get(broker_name, [])
        except Exception as e:
            logger.error(f"OrderCache.get_orders failed for {broker_name}: {e}")
            return []

    async def get_order_by_id(self, broker_name: str, order_id: Any) -> Optional[dict]:
        try:
            orders = await self.get_orders(broker_name)
            # For Fyers BO orders, try with '-BO-1' suffix if not found
            for order in orders:
                broker_order_id = order.get("order_id") or order.get("id")
                if broker_order_id is not None and str(broker_order_id) == str(order_id):
                    return order
            return None
        except RuntimeError as re:
            logger.error(f"OrderCache.get_order_by_id RuntimeError for {broker_name}, order_id {order_id}: {re}")
            return None
        except Exception as e:
            logger.error(f"OrderCache.get_order_by_id failed for {broker_name}, order_id {order_id}: {e}")
            return None

    async def get_order_status_by_id(self, broker_name: str, order_id: Any) -> Optional[str]:
        """
        Get normalized order status by order ID from cache.
        Returns a string representation of the order status with proper normalization
        for different broker formats.
        """
        try:
            # Import here to avoid circular dependencies
            from algosat.brokers.base import OrderStatus
            
            # Fyers status mapping using OrderStatus enum
            FYERS_STATUS_MAP = {
                1: OrderStatus.CANCELLED,      # 1 = Cancelled
                2: OrderStatus.FILLED,        # 2 = Traded / Filled
                3: OrderStatus.PENDING,       # 3 = For future use (treat as Pending)
                4: OrderStatus.PENDING,       # 4 = Transit (treat as Pending)
                5: OrderStatus.REJECTED,      # 5 = Rejected
                6: OrderStatus.PENDING,       # 6 = Pending
                # Add more mappings as per Fyers API
            }
            
            cache_order = await self.get_order_by_id(broker_name, order_id)
            if not cache_order:
                logger.debug(f"Order not found in cache for {broker_name}, order_id {order_id}")
                return None
                
            broker_status = cache_order.get('status')
            if not broker_status:
                logger.debug(f"No status found for order {order_id} in {broker_name}")
                return None
                
            # Handle Fyers integer status codes
            if broker_status and isinstance(broker_status, int) and broker_name.lower() == "fyers":
                broker_status = FYERS_STATUS_MAP.get(broker_status, broker_status)
                
            # Normalize broker_status from OrderStatus.VALUE format
            if broker_status and isinstance(broker_status, str) and broker_status.startswith("OrderStatus."):
                broker_status = broker_status.split(".")[-1]
            # Handle OrderStatus enum objects
            elif broker_status and hasattr(broker_status, 'value') and hasattr(broker_status, 'name'):
                broker_status = broker_status.value if hasattr(broker_status, 'value') else str(broker_status)
                
            return str(broker_status) if broker_status else None
            
        except RuntimeError as re:
            logger.error(f"OrderCache.get_order_status_by_id RuntimeError for {broker_name}, order_id {order_id}: {re}")
            return None
        except Exception as e:
            logger.error(f"OrderCache.get_order_status_by_id failed for {broker_name}, order_id {order_id}: {e}")
            return None
