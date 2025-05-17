# algosat/core/strategy_manager.py

import asyncio
from sqlalchemy.exc import ProgrammingError
from core.db import get_session
from config import settings
from common.logger import get_logger
from sqlalchemy import select
from core.dbschema import strategy_configs
from core.strategy_runner import run_strategy_config

logger = get_logger("strategy_manager")

async def run_poll_loop():
    """
    Poll the strategy_configs table forever.
    For each enabled config, launch a runner (OptionBuy only for now).
    """
    async for session in get_session():
        while True:
            try:
                stmt = select(strategy_configs).where(strategy_configs.c.enabled == True)
                result = await session.execute(stmt)
                configs = result.fetchall()
                if configs:
                    logger.info(f"Found configs: {[row.id for row in configs]}")
                    # For now, only run OptionBuy strategies
                    for row in configs:
                        # Fetch strategy key from joined strategies table if needed
                        # For now, assume OptionBuy only
                        # TODO: Add deduplication/avoid duplicate runners
                        await run_strategy_config(row)
                else:
                    logger.info("No configs found")
            except ProgrammingError as pe:
                logger.warning(f"DB schema not ready: {pe}")
            except Exception as e:
                logger.error(f"Unexpected DB error: {e}")
            logger.debug(f"Sleeping for {settings.poll_interval} seconds...")
            await asyncio.sleep(settings.poll_interval)