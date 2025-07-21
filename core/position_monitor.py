# position_monitor.py
import asyncio
from datetime import datetime, timedelta
from algosat.core.db import AsyncSessionLocal, get_all_open_orders
from algosat.core.data_manager import DataManager
from algosat.core.order_manager import OrderManager
from algosat.common.logger import get_logger

logger = get_logger("PositionMonitor")

class PositionMonitor:
    def __init__(self, data_manager: DataManager, order_manager: OrderManager, poll_interval: int = 20):
        self.data_manager = data_manager
        self.order_manager = order_manager
        self.poll_interval = poll_interval  # seconds
        self._running = False

    async def start(self):
        self._running = True
        while self._running:
            await self.check_positions()
            await asyncio.sleep(self.poll_interval)

    async def stop(self):
        self._running = False

    async def check_positions(self):
        # Check all open orders (filter only on status)
        async with AsyncSessionLocal() as session:
            open_orders = await get_all_open_orders(session)
            if not open_orders:
                logger.info("No open orders. Skipping position check.")
                return
            logger.info(f"Checking positions for {len(open_orders)} open orders.")
            # Fetch positions from all brokers
            positions_by_broker = await self.order_manager.broker_manager.get_all_broker_positions()
            for order in open_orders:
                order_id = order.get('id')
                symbol = order.get('strike_symbol') or order.get('symbol')
                broker_id = order.get('broker_id')
                # Compare with broker positions
                for broker_name, positions in positions_by_broker.items():
                    match = self._find_position_match(order, positions)
                    if match:
                        logger.info(f"Order {order_id} matched position in broker {broker_name}: {match}")
                        # Optionally update order status/PnL here
                    else:
                        logger.warning(f"Order {order_id} not found in broker {broker_name} positions.")

    def _find_position_match(self, order, positions):
        # Compare order with broker positions (tradingsymbol, quantity, product, entry_price)
        for pos in positions.get('net', []):
            if (
                pos.get('tradingsymbol') == order.get('strike_symbol') and
                (pos.get('buy_quantity') == order.get('qty') or pos.get('overnight_quantity') == order.get('qty')) and
                pos.get('product') == order.get('product_type') and
                pos.get('buy_price') == order.get('entry_price')
            ):
                return pos
        return None
