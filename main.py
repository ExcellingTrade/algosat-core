# algosat/main.py

import asyncio
import sys
from core.strategy_manager import order_queue
from core.db import init_db, engine
from core.db import seed_default_strategies_and_configs
from core.dbschema import strategies, strategy_configs, broker_credentials
from core.strategy_manager import run_poll_loop
from common.broker_utils import get_broker_credentials, upsert_broker_credentials
from common.logger import get_logger
from common.default_broker_configs import DEFAULT_BROKER_CONFIGS # Import the default configs
from common.default_strategy_configs import DEFAULT_STRATEGY_CONFIGS
from sqlalchemy import select
from datetime import datetime
from core.data_manager import DataManager
from core.broker_manager import BrokerManager
from core.order_manager import get_order_manager

logger = get_logger(__name__)

broker_manager = BrokerManager()

data_manager = DataManager(broker_manager=broker_manager)

if __name__ == "__main__":
    import asyncio

    async def main():
        # 1) Ensure database schema exists
        logger.info("🔄 Initializing database schema…")
        await init_db()

        # 2) Seed default strategies and configs
        logger.debug("🔄 Seeding default strategies and configs...")
        await seed_default_strategies_and_configs()

        # 3) Initialize broker configurations, prompt for missing credentials, and authenticate all enabled brokers
        await broker_manager.setup()

        # Print broker profiles and positions before starting the strategy engine
        for broker_name, broker in broker_manager.brokers.items():
            try:
                profile = await broker.get_profile()
                logger.debug(f"Broker {broker_name} profile: {profile}")
            except Exception as e:
                logger.debug(f"Error fetching profile for broker {broker_name}: {e}")
            try:
                positions = await broker.get_positions()
                logger.debug(f"Broker {broker_name} positions: {positions}")
            except Exception as e:
                logger.debug(f"Error fetching positions for broker {broker_name}: {e}")

        # 6) Initialize DataManager and OrderManager, then start the strategy polling loop
        order_manager = get_order_manager(broker_manager)
        logger.info("🚦 All brokers authenticated. Starting strategy engine...")
        await run_poll_loop(data_manager, order_manager)
        # 7) Close the database connection
        await engine.dispose()
        logger.info("🟢 Database connection closed.")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.warning("🔴 Program interrupted by user. Shutting down gracefully...")
        # signal strategy consumers to stop
        asyncio.run(order_queue.put(None))
        # close DB connection
        asyncio.run(engine.dispose())
        sys.exit(0)