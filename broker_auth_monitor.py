import asyncio
import sys
import logging
from datetime import datetime, time as dt_time, timedelta
from zoneinfo import ZoneInfo
from algosat.core.broker_manager import BrokerManager
from algosat.core.db import async_session
from algosat.core.dbschema import broker_credentials
from sqlalchemy import update, select

logger = logging.getLogger("broker_auth_monitor")
logging.basicConfig(level=logging.INFO)

# --- CONFIGURABLE INTERVALS ---
PROFILE_CHECK_INTERVAL_MIN = 5   # minutes
BALANCE_CHECK_INTERVAL_MIN = 10  # minutes

IST = ZoneInfo("Asia/Kolkata")

async def update_broker_db(broker_name, **fields):
    async with async_session() as session:
        stmt = (
            update(broker_credentials)
            .where(broker_credentials.c.broker_name == broker_name)
            .values(**fields)
        )
        await session.execute(stmt)
        await session.commit()
        logger.debug(f"DB updated for {broker_name}: {fields}")

async def get_broker_token_generated_on(broker_name):
    async with async_session() as session:
        stmt = select(broker_credentials.c.credentials).where(broker_credentials.c.broker_name == broker_name)
        result = await session.execute(stmt)
        row = result.scalar()
        if row and isinstance(row, dict):
            return row.get("generated_on")
        return None

async def daily_6am_auth_check(broker_name, broker):
    while True:
        now_ist = datetime.now(IST)
        six_am_today = now_ist.replace(hour=6, minute=0, second=0, microsecond=0)
        if now_ist < six_am_today:
            # Sleep until 6am IST
            sleep_seconds = (six_am_today - now_ist).total_seconds()
            logger.info(f"[{broker_name}] Sleeping until 6am IST for daily auth check: {sleep_seconds:.0f}s")
            await asyncio.sleep(sleep_seconds)
        else:
            # Check token generation time
            generated_on = await get_broker_token_generated_on(broker_name)
            if generated_on:
                try:
                    token_time = datetime.fromisoformat(generated_on).astimezone(IST)
                except Exception:
                    token_time = None
            else:
                token_time = None
            if not token_time or token_time < six_am_today:
                logger.info(f"[{broker_name}] Token is old or missing, triggering re-auth at {now_ist}")
                await update_broker_db(
                    broker_name,
                    status="AUTHENTICATING",
                    last_auth_check=now_ist,
                    updated_at=now_ist
                )
                try:
                    await broker.authenticate()
                    await update_broker_db(
                        broker_name,
                        status="CONNECTED",
                        last_auth_check=now_ist,
                        updated_at=now_ist
                    )
                    logger.info(f"[{broker_name}] Re-authenticated successfully at {now_ist}")
                except Exception as e:
                    await update_broker_db(
                        broker_name,
                        status="ERROR",
                        last_auth_check=now_ist,
                        updated_at=now_ist,
                        notes=str(e)
                    )
                    logger.error(f"[{broker_name}] Re-authentication failed: {e}")
            else:
                logger.info(f"[{broker_name}] Token is valid for today (after 6am IST), skipping re-auth.")
            # Sleep until next 6am IST
            next_6am = six_am_today + timedelta(days=1)
            sleep_seconds = (next_6am - now_ist).total_seconds()
            await asyncio.sleep(sleep_seconds)

async def periodic_balance_check(broker_name, broker):
    while True:
        now_ist = datetime.now(IST)
        try:
            # Only check if broker is connected
            async with async_session() as session:
                stmt = select(broker_credentials.c.status).where(broker_credentials.c.broker_name == broker_name)
                result = await session.execute(stmt)
                status = result.scalar()
            if status == "CONNECTED":
                balance = await broker.get_balance()
                await update_broker_db(
                    broker_name,
                    available_balance=balance.get("available_balance"),
                    updated_at=now_ist
                )
                logger.info(f"[{broker_name}] Balance updated: {balance.get('available_balance')}")
        except Exception as e:
            logger.error(f"[{broker_name}] Balance check failed: {e}")
        await asyncio.sleep(BALANCE_CHECK_INTERVAL_MIN * 60)

async def periodic_profile_check(broker_name, broker):
    while True:
        now_ist = datetime.now(IST)
        try:
            await broker.get_profile()
            await update_broker_db(
                broker_name,
                status="CONNECTED",
                last_check=now_ist,
                updated_at=now_ist
            )
            logger.debug(f"[{broker_name}] Profile check successful.")
        except Exception as e:
            await update_broker_db(
                broker_name,
                status="DISCONNECTED",
                last_check=now_ist,
                updated_at=now_ist,
                notes=str(e)
            )
            logger.warning(f"[{broker_name}] Profile check failed, marked DISCONNECTED: {e}")
        await asyncio.sleep(PROFILE_CHECK_INTERVAL_MIN * 60)

async def monitor_broker(broker_name, broker):
    # Run all tasks in parallel for each broker
    await asyncio.gather(
        daily_6am_auth_check(broker_name, broker),
        periodic_balance_check(broker_name, broker),
        periodic_profile_check(broker_name, broker)
    )

async def main():
    broker_manager = BrokerManager()
    await broker_manager.setup()
    tasks = []
    for broker_name, broker in broker_manager.brokers.items():
        if getattr(broker, 'is_enabled', True):
            tasks.append(asyncio.create_task(monitor_broker(broker_name, broker)))
    logger.info(f"Started broker auth monitor for {len(tasks)} brokers.")
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.warning("Broker auth monitor interrupted. Exiting.")
        sys.exit(0)

# --- RECOMMENDATIONS ---
# - Use a process manager (e.g., PM2, systemd) to keep this worker always running.
# - Consider using a persistent scheduler (e.g., APScheduler) for more complex scheduling needs.
# - All time handling is done in IST for compliance with trading hours.
# - Logging is robust and should be monitored for errors and state changes.
# - All broker tasks run in parallel for scalability.
