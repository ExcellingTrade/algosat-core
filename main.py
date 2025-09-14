# algosat/main.py

import asyncio
import sys
from algosat.core.strategy_manager import order_queue
from algosat.core.db import init_db, engine
from algosat.core.db import seed_default_strategies_and_configs
from algosat.core.dbschema import strategies, strategy_configs, broker_credentials
from algosat.core.strategy_manager import run_poll_loop
from algosat.common.broker_utils import get_broker_credentials, upsert_broker_credentials, get_nse_holiday_list
from algosat.common.logger import get_logger
from algosat.common.default_broker_configs import DEFAULT_BROKER_CONFIGS # Import the default configs
from algosat.common.default_strategy_configs import DEFAULT_STRATEGY_CONFIGS
from algosat.core.time_utils import get_ist_datetime
from sqlalchemy import select
from datetime import datetime, timedelta, time
from algosat.core.data_manager import DataManager
from algosat.core.broker_manager import BrokerManager
from algosat.core.order_manager import OrderManager
import warnings
warnings.filterwarnings("ignore", category=UserWarning, message="pkg_resources is deprecated")

logger = get_logger(__name__)

broker_manager = BrokerManager()

data_manager = DataManager(broker_manager=broker_manager)

if __name__ == "__main__" and __package__ is None:
    print("\n[ERROR] Do not run this file directly. Use: python -m algosat.main from the project root.\n", file=sys.stderr)
    sys.exit(1)

def is_trading_day(check_date=None):
    """
    Check if the given date (or today if None) is a trading day.
    Returns True if it's a weekday and not a NSE holiday.
    """
    if check_date is None:
        check_date = get_ist_datetime()
    
    # Check weekend (Saturday = 5, Sunday = 6)
    if check_date.weekday() >= 5:
        return False
    
    # Check NSE holidays
    try:
        nse_holidays = get_nse_holiday_list()
        if nse_holidays is None:
            logger.warning("🟡 NSE holiday list unavailable, using basic weekend check")
            return True  # If we can't get holidays, assume it's trading day (weekday)
        
        today_str = check_date.strftime("%d-%b-%Y")
        return today_str not in nse_holidays
    except Exception as e:
        logger.error(f"Error checking NSE holidays: {e}")
        return True  # If error, assume trading day

def get_next_trading_day(start_date=None):
    """
    Get the next trading day (9:12 AM IST) starting from the given date.
    """
    if start_date is None:
        start_date = get_ist_datetime()
    
    # Start checking from tomorrow if current date is not a trading day
    check_date = start_date + timedelta(days=1)
    
    # Find next trading day
    while not is_trading_day(check_date):
        check_date += timedelta(days=1)
        # Safety check - don't go beyond 30 days
        if (check_date - start_date).days > 30:
            logger.error("Could not find trading day within 30 days")
            break
    
    # Set time to 9:12 AM
    next_trading_start = check_date.replace(hour=9, minute=12, second=0, microsecond=0)
    return next_trading_start

async def wait_for_trading_day():
    """
    Check if today is a trading day. If not, wait until the next trading day at 9:12 AM IST.
    """
    now = get_ist_datetime()
    
    if is_trading_day(now):
        logger.info("🟢 Today is a trading day. Proceeding with AlgoSat operations.")
        return
    
    # Today is not a trading day
    day_type = "weekend" if now.weekday() >= 5 else "holiday"
    logger.info(f"🏖️  Today ({now.strftime('%Y-%m-%d %A')}) is a {day_type}. Markets are closed.")
    
    # Get next trading day
    next_trading = get_next_trading_day(now)
    wait_seconds = (next_trading - now).total_seconds()
    
    if wait_seconds > 0:
        wait_time_str = str(timedelta(seconds=int(wait_seconds)))
        logger.info(f"⏰ Next trading day: {next_trading.strftime('%Y-%m-%d %A at %H:%M:%S IST')}")
        logger.info(f"⏳ Waiting for {wait_time_str} until markets reopen...")
        
        # Wait with periodic status updates (every hour)
        update_interval = 3600  # 1 hour
        elapsed = 0
        
        while elapsed < wait_seconds:
            sleep_time = min(update_interval, wait_seconds - elapsed)
            await asyncio.sleep(sleep_time)
            elapsed += sleep_time
            
            if elapsed < wait_seconds:
                remaining = wait_seconds - elapsed
                remaining_str = str(timedelta(seconds=int(remaining)))
                logger.info(f"⏳ Still waiting... {remaining_str} remaining until markets reopen")
        
        logger.info("🟢 Market wait period completed. Starting AlgoSat operations...")
    else:
        logger.info("🟢 Next trading day is already here. Starting AlgoSat operations...")

async def main():
    try:
        # 0) Check if today is a trading day - if not, wait for next trading day
        await wait_for_trading_day()
        
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