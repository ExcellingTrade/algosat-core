# test_position_monitor.py
import asyncio
from algosat.core.data_manager import DataManager
from algosat.core.broker_manager import BrokerManager
from algosat.core.order_manager import OrderManager
from algosat.core.position_monitor import PositionMonitor

async def main():
    broker_manager = BrokerManager()
    await broker_manager.setup()
    data_manager = DataManager(broker_manager=broker_manager)
    order_manager = OrderManager(broker_manager)
    position_monitor = PositionMonitor(data_manager, order_manager, poll_interval=20)

    print("Starting PositionMonitor...")
    await position_monitor.start()

if __name__ == "__main__":
    asyncio.run(main())
