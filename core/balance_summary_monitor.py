import asyncio
from datetime import datetime, timezone
from algosat.core.db import AsyncSessionLocal, upsert_broker_balance_summary, get_all_brokers
from algosat.core.broker_manager import BrokerManager
from algosat.brokers.models import BalanceSummary
from algosat.common.logger import get_logger

logger = get_logger("BalanceSummaryMonitor")

class BalanceSummaryMonitor:
    def __init__(self, broker_manager: BrokerManager, interval: int = 60):
        self.broker_manager = broker_manager
        self.interval = interval  # seconds
        self._running = False
        self._task = None

    async def fetch_and_store_balances(self):
        async with AsyncSessionLocal() as session:
            brokers = await get_all_brokers(session)
            for broker in brokers:
                broker_id = broker["id"]
                broker_name = broker["broker_name"]
                try:
                    broker_obj = self.broker_manager.brokers.get(broker_name)
                    if broker_obj and hasattr(broker_obj, "get_balance_summary"):
                        summary = await broker_obj.get_balance_summary()
                        # Convert BalanceSummary model to dict for storage
                        summary_dict = summary.model_dump() if hasattr(summary, 'model_dump') else summary.to_dict()
                        await upsert_broker_balance_summary(session, broker_id, summary_dict)
                        logger.debug(f"Updated balance summary for {broker_name}")
                except Exception as e:
                    logger.error(f"Failed to fetch/store balance for {broker_name}: {e}")

    async def start(self):
        self._running = True
        while self._running:
            await self.fetch_and_store_balances()
            await asyncio.sleep(self.interval)

    def stop(self):
        self._running = False

# Usage example (to be started in your app's startup):
# broker_manager = BrokerManager()
# balance_summary_monitor = BalanceSummaryMonitor(broker_manager)
# asyncio.create_task(balance_summary_monitor.start())
