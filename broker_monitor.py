import asyncio
import sys
from datetime import datetime, timedelta, time as dt_time
from algosat.core.broker_manager import BrokerManager
from algosat.core.db import (
    AsyncSessionLocal, get_broker_by_name, 
    get_all_brokers, upsert_broker_balance_summary
)
from algosat.core.time_utils import get_ist_now
from algosat.common.logger import get_logger, cleanup_logs_and_cache, clean_broker_monitor_logs
from algosat.common.broker_utils import update_broker_status

logger = get_logger("broker_monitor")

PROFILE_CHECK_INTERVAL_MIN = 5  # minutes

def seconds_until_next_6_01am_ist():
    now = get_ist_now()
    next_6_01am = now.replace(hour=6, minute=1, second=0, microsecond=0)
    if now >= next_6_01am:
        next_6_01am += timedelta(days=1)
    return (next_6_01am - now).total_seconds()

def seconds_until_next_market_open(now_ist):
    """Return seconds until next market open (9:15 IST)."""
    market_open = now_ist.replace(hour=9, minute=15, second=0, microsecond=0)
    if now_ist.time() < dt_time(9, 15):
        return (market_open - now_ist).total_seconds()
    # If after market close, next open is tomorrow
    market_open += timedelta(days=1)
    return (market_open - now_ist).total_seconds()

def is_market_hours(now_ist):
    """Return True if now_ist is within market hours (IST 9:15 to 15:30)."""
    market_open = dt_time(9, 15)
    market_close = dt_time(15, 30)
    return market_open <= now_ist.time() <= market_close

async def serial_health_check(broker_name, broker):
    now_ist = get_ist_now()
    logger.info(f"[{broker_name}] Starting serial health check at {now_ist}.")
    try:
        logger.info(f"[{broker_name}] Running get_profile...")
        await broker.get_profile()
        await update_broker_status(broker_name, "CONNECTED", notes="", last_check=now_ist)
        logger.info(f"[{broker_name}] get_profile successful. Status set to CONNECTED.")
    except Exception as e:
        await update_broker_status(broker_name, "DISCONNECTED", notes=str(e), last_check=now_ist)
        logger.error(f"[{broker_name}] get_profile failed: {e}. Status set to DISCONNECTED.")
        return False
    # try:
    #     logger.info(f"[{broker_name}] Running get_balance...")
    #     balance = await broker.get_balance()
    #     async with AsyncSessionLocal() as session:
    #         await update_broker(session, broker_name, {
    #             "available_balance": balance.get("available_balance"),
    #             "updated_at": now_ist
    #         })
    #     logger.info(f"[{broker_name}] get_balance successful. Balance updated: {balance.get('available_balance')}")
    # except Exception as e:
    #     logger.error(f"[{broker_name}] get_balance failed: {e}")
    try:
        if hasattr(broker, "get_balance_summary"):
            logger.info(f"[{broker_name}] Running get_balance_summary...")
            async with AsyncSessionLocal() as session:
                brokers = await get_all_brokers(session)
                broker_data = next((b for b in brokers if b["broker_name"] == broker_name), None)
            if broker_data:
                broker_id = broker_data["id"]
                summary = await broker.get_balance_summary()
                summary_dict = summary.model_dump() if hasattr(summary, 'model_dump') else summary.to_dict()
                logger.info(f"[{broker_name}] Balance summary fetched: {summary_dict}")
                async with AsyncSessionLocal() as session:
                    await upsert_broker_balance_summary(session, broker_id, summary_dict)
                logger.info(f"[{broker_name}] get_balance_summary successful. Balance summary updated.")
    except Exception as e:
        logger.error(f"[{broker_name}] get_balance_summary failed: {e}")
    logger.info(f"[{broker_name}] Serial health check complete.")
    return True

async def monitor_broker(broker_name, broker_manager):
    logger.info(f"[{broker_name}] Starting broker monitor loop...")
    while True:
        try:
            async with AsyncSessionLocal() as session:
                broker_row = await get_broker_by_name(session, broker_name)
                status = broker_row["status"] if broker_row else None
            broker = broker_manager.brokers.get(broker_name)
            logger.debug(f"[{broker_name}] Broker status from DB: {status}")
            now_ist = get_ist_now()
            if status == "CONNECTED" and broker is not None:
                if is_market_hours(now_ist):
                    logger.info(f"[{broker_name}] Status CONNECTED and within market hours. Running serial_health_check.")
                    await serial_health_check(broker_name, broker)
                    logger.debug(f"[{broker_name}] Sleeping for {PROFILE_CHECK_INTERVAL_MIN} minutes before next check.")
                    await asyncio.sleep(PROFILE_CHECK_INTERVAL_MIN * 60)
                else:
                    logger.info(f"[{broker_name}] Status CONNECTED but outside market hours. Sleeping for {PROFILE_CHECK_INTERVAL_MIN} minutes.")
                    await asyncio.sleep(PROFILE_CHECK_INTERVAL_MIN * 60)
            elif status == "FAILED":
                logger.info(f"[{broker_name}] Status FAILED. Attempting re-authentication...")
                await broker_manager.reauthenticate_broker(broker_name)
                logger.debug(f"[{broker_name}] Sleeping for {PROFILE_CHECK_INTERVAL_MIN} minutes before next check.")
                await asyncio.sleep(PROFILE_CHECK_INTERVAL_MIN * 60)
            else:
                logger.debug(f"[{broker_name}] Status is '{status}'. No health check or re-auth needed right now.")
                logger.debug(f"[{broker_name}] Sleeping for {PROFILE_CHECK_INTERVAL_MIN} minutes before next check.")
                await asyncio.sleep(PROFILE_CHECK_INTERVAL_MIN * 60)
        except Exception as e:
            logger.error(f"[{broker_name}] Exception in monitor_broker loop: {e}", exc_info=True)
            await asyncio.sleep(PROFILE_CHECK_INTERVAL_MIN * 60)

def seconds_until_next_scheduled_time(now_ist):
    """Calculate seconds until the next scheduled re-authentication time."""
    scheduled_times = [
        dt_time(0, 5),   # 12:05 AM IST
        dt_time(6, 10),  # 6:10 AM IST
        dt_time(8, 5)    # 8:00 AM IST
    ]
    now_time = now_ist.time()
    today = now_ist.date()
    next_times = []
    for t in scheduled_times:
        dt_scheduled = datetime.combine(today, t)
        dt_scheduled = dt_scheduled.replace(tzinfo=now_ist.tzinfo)
        if dt_scheduled <= now_ist:
            dt_scheduled += timedelta(days=1)
        next_times.append(dt_scheduled)
    next_run = min(next_times)
    return (next_run - now_ist).total_seconds()

async def daily_reauth_scheduler(broker_manager):
    """Separate task to handle daily re-authentication at multiple times."""
    while True:
        try:
            now_ist = get_ist_now()
            seconds_to_next = seconds_until_next_scheduled_time(now_ist)
            hours = seconds_to_next / 3600
            minutes = seconds_to_next / 60
            logger.info(f"Daily scheduler: Time until next scheduled re-auth: {hours:.2f} hours ({minutes:.1f} minutes)")
            # Sleep until next scheduled time
            await asyncio.sleep(seconds_to_next)
            # At scheduled time, re-run setup with force_auth and clean logs
            logger.info("Running scheduled re-authentication via setup() and log cleanup.")
            await broker_manager.setup(force_auth=True)
            cleanup_logs_and_cache()
            clean_broker_monitor_logs()
        except Exception as e:
            logger.error(f"Exception in daily_reauth_scheduler: {e}", exc_info=True)
            await asyncio.sleep(60)  # Wait 1 minute before retrying

async def main():
    logger.info("Starting minimal serial broker monitor...")
    try:
        cleanup_logs_and_cache()
        clean_broker_monitor_logs()
        broker_manager = BrokerManager()
        await broker_manager.setup()
        logger.info(f"Brokers to monitor: {list(broker_manager.brokers.keys())}")
        tasks = []
        # Create monitoring tasks for each broker
        for broker_name in broker_manager.brokers.keys():
            logger.info(f"[{broker_name}] Creating monitor task.")
            tasks.append(asyncio.create_task(monitor_broker(broker_name, broker_manager)))
        # Create daily re-authentication scheduler task
        logger.info("Creating daily re-authentication scheduler task.")
        tasks.append(asyncio.create_task(daily_reauth_scheduler(broker_manager)))
        logger.info(f"Started broker monitor for {len(broker_manager.brokers)} brokers plus scheduler.")
        await asyncio.gather(*tasks, return_exceptions=True)
    except Exception as e:
        logger.error(f"Exception in main broker monitor: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.warning("Broker monitor interrupted. Exiting gracefully.")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Broker monitor crashed: {e}")
        sys.exit(1)
