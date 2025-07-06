# algosat/main.py

import asyncio
import sys
from algosat.core.strategy_manager import order_queue
from algosat.core.db import init_db, engine
from algosat.core.db import seed_default_strategies_and_configs
from algosat.core.dbschema import strategies, strategy_configs, broker_credentials
from algosat.core.strategy_manager import run_poll_loop
from algosat.common.broker_utils import get_broker_credentials, upsert_broker_credentials
from algosat.common.logger import get_logger
from algosat.common.default_broker_configs import DEFAULT_BROKER_CONFIGS # Import the default configs
from algosat.common.default_strategy_configs import DEFAULT_STRATEGY_CONFIGS
from sqlalchemy import select
from datetime import datetime
from algosat.core.data_manager import DataManager
from algosat.core.broker_manager import BrokerManager
from algosat.core.order_manager import OrderManager

logger = get_logger(__name__)

broker_manager = BrokerManager()

data_manager = DataManager(broker_manager=broker_manager)

if __name__ == "__main__" and __package__ is None:
    print("\n[ERROR] Do not run this file directly. Use: python -m algosat.main from the project root.\n", file=sys.stderr)
    sys.exit(1)

async def main():
    try:
        # 1) Ensure database schema exists
        logger.info("🔄 Initializing database schema…")
        await init_db()

        # 2) Seed default strategies and configs
        logger.debug("🔄 Seeding default strategies and configs...")
        await seed_default_strategies_and_configs()

        # 3) Initialize broker configurations, prompt for missing credentials, and authenticate all enabled brokers
        await broker_manager.setup()

        # # Print broker profiles and positions before starting the strategy engine
        # for broker_name, broker in broker_manager.brokers.items():
        #     try:
        #         profile = await broker.get_profile()
        #         logger.debug(f"Broker {broker_name} profile: {profile}")
        #     except Exception as e:
        #         logger.debug(f"Error fetching profile for broker {broker_name}: {e}")
        #     try:
        #         positions = await broker.get_positions()
        #         logger.debug(f"Broker {broker_name} positions: {positions}")
        #     except Exception as e:
        #         logger.debug(f"Error fetching positions for broker {broker_name}: {e}")

        # 6) Initialize DataManager and OrderManager, then start the strategy polling loop
        order_manager = OrderManager(broker_manager)
        # logger.info("🚦 All brokers authenticated. Starting strategy engine...")
        await run_poll_loop(data_manager, order_manager)
    except KeyboardInterrupt:
        logger.warning("🔴 Program interrupted by user. Shutting down gracefully...")
        await order_queue.put(None)
    finally:
        # Always dispose engine, log any error during disposal
        try:
            await engine.dispose()
            logger.info("🟢 Database connection closed.")
        except Exception as e:
            logger.error(f"Error disposing SQLAlchemy engine during shutdown: {e}", exc_info=True)

if __name__ == "__main__":
    asyncio.run(main())