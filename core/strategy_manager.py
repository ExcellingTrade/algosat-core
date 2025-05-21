# algosat/core/strategy_manager.py

import asyncio
from typing import Dict
from sqlalchemy.exc import ProgrammingError
from core.db import get_enabled_default_strategy_configs, AsyncSessionLocal
from config import settings
from common.logger import get_logger
from core.strategy_runner import run_strategy_config
from core.data_manager import DataManager
from core.order_manager import OrderManager

logger = get_logger("strategy_manager")

# Track running strategy runner tasks by config ID
running_tasks: Dict[int, asyncio.Task] = {}

async def run_poll_loop(data_manager: DataManager, order_manager: OrderManager):
    """
    Poll the strategy_configs table forever.
    For each enabled config, launch a runner (OptionBuy only for now).
    """
    try:
        async with AsyncSessionLocal() as session:
            while True:
                try:
                    configs = await get_enabled_default_strategy_configs(session)
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

                        # Launch tasks for new default configs
                        for row in configs:
                            cfg_id = row.id
                            if cfg_id not in running_tasks:
                                logger.debug(f"Starting runner task for config {cfg_id}")
                                task = asyncio.create_task(run_strategy_config(row, data_manager, order_manager))
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
        return