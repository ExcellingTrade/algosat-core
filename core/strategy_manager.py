# algosat/core/strategy_manager.py

import asyncio
import datetime
from typing import Dict
from sqlalchemy.exc import ProgrammingError
from core.db import get_enabled_default_strategy_configs, AsyncSessionLocal
from config import settings
from common.logger import get_logger
from core.strategy_runner import run_strategy_config
from core.data_manager import DataManager
from core.order_manager import OrderManager
from core.order_monitor import OrderMonitor
from core.time_utils import get_ist_datetime
from models.strategy_config import StrategyConfig

logger = get_logger("strategy_manager")

# Track running strategy runner tasks by config ID
running_tasks: Dict[int, asyncio.Task] = {}
order_monitors: Dict[str, asyncio.Task] = {}
order_queue = asyncio.Queue()

async def order_monitor_loop(order_queue, data_manager, order_manager):
    while True:
        order_info = await order_queue.get()
        if order_info is None:
            logger.info("Order monitor received shutdown sentinel, exiting loop")
            break
        order_id = order_info["order_id"]
        if order_id not in order_monitors:
            monitor = OrderMonitor(
                order_id=order_id,
                config=order_info["config"],
                data_manager=data_manager,
                order_manager=order_manager,
                interval_minutes=order_info["interval_minutes"]
            )
            order_monitors[order_id] = asyncio.create_task(monitor.start())
    logger.info("Order monitor loop has exited")

async def run_poll_loop(data_manager: DataManager, order_manager: OrderManager):
    """
    Poll the strategy_configs table forever.
    For each enabled config, launch a runner (OptionBuy only for now).
    Now supports time-based start/stop for intraday/delivery trade types.
    """
    asyncio.create_task(order_monitor_loop(order_queue, data_manager, order_manager))
    try:
        async with AsyncSessionLocal() as session:
            while True:
                try:
                    configs = await get_enabled_default_strategy_configs(session)
                    now = get_ist_datetime().time()  # Use IST time for all time logic
                    if configs:
                        # Only print found configs the first time
                        if not running_tasks:
                            logger.debug(f"🟢 Found configs: {[row.id for row in configs]}")
                        current_ids = {row.id for row in configs}
                        

                        # Cancel tasks for configs no longer present as default
                        for cfg_id in list(running_tasks):
                            if cfg_id not in current_ids:
                                logger.info(f"🟡 Cancelling runner for config {cfg_id}")
                                running_tasks[cfg_id].cancel()
                                running_tasks.pop(cfg_id, None)

                        # Launch/stop tasks for configs based on time and trade_type
                        for row in configs:
                            cfg_id = row.id
                            trade_type = getattr(row, "trade_type", "intraday")
                            square_off_time = getattr(row, "square_off_time", "19:15")
                            start_time = getattr(row, "start_time", "09:15")
                            sq_time = datetime.datetime.strptime(square_off_time, "%H:%M").time()
                            st_time = datetime.datetime.strptime(start_time, "%H:%M").time()
                            st_time = st_time.replace(hour=4, minute=0)  # Adjust start time to 4 AM
                            def is_time_between(start, end, now):
                                if start < end:
                                    return start <= now < end
                                else:
                                    return start <= now or now < end
                            if trade_type == "intraday":
                                if is_time_between(st_time, sq_time, now):
                                    if cfg_id not in running_tasks:
                                        logger.debug(f"Starting runner task for config {cfg_id} (intraday window)")
                                        # Convert row to StrategyConfig
                                        if hasattr(row, '_mapping'):
                                            config_dict = dict(row._mapping)
                                        elif isinstance(row, dict):
                                            config_dict = row
                                        else:
                                            config_dict = dict(row)
                                        config = StrategyConfig(**config_dict)
                                        task = asyncio.create_task(run_strategy_config(config, data_manager, order_manager, order_queue))
                                        running_tasks[cfg_id] = task
                                else:
                                    if cfg_id in running_tasks:
                                        logger.info(f"Stopping intraday runner for config {cfg_id} (outside window)")
                                        running_tasks[cfg_id].cancel()
                                        running_tasks.pop(cfg_id, None)
                            else:  # delivery
                                # Optionally, stop at night (e.g., 00:00-06:00), else run 24/7
                                # To always run, comment out the next 4 lines
                                if is_time_between(datetime.time(0,0), datetime.time(6,0), now):
                                    if cfg_id in running_tasks:
                                        logger.info(f"Stopping delivery runner for config {cfg_id} (maintenance window)")
                                        running_tasks[cfg_id].cancel()
                                        running_tasks.pop(cfg_id, None)
                                else:
                                    if cfg_id not in running_tasks:
                                        logger.debug(f"Starting runner task for config {cfg_id} (delivery)")
                                        if hasattr(row, '_mapping'):
                                            config_dict = dict(row._mapping)
                                        elif isinstance(row, dict):
                                            config_dict = row
                                        else:
                                            config_dict = dict(row)
                                        config = StrategyConfig(**config_dict)
                                        task = asyncio.create_task(run_strategy_config(config, data_manager, order_manager, order_queue))
                                        running_tasks[cfg_id] = task
                    else:
                        logger.info("🟡 No configs found")
                except ProgrammingError as pe:
                    logger.warning(f"🟡 DB schema not ready: {pe}")
                except Exception as e:
                    logger.error(f"🔴 Unexpected DB error: {e}")
                logger.debug(f"⏳ Sleeping for {settings.poll_interval} seconds...")
                await asyncio.sleep(settings.poll_interval)
    except asyncio.CancelledError:
        logger.warning("🟡 Polling loop cancelled. Shutting down cleanly.")
        for task in running_tasks.values():
            task.cancel()
        running_tasks.clear()
        for task in order_monitors.values():
            task.cancel()
        order_monitors.clear()
        return