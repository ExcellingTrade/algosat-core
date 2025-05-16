# algosat/core/strategy_manager.py

import asyncio
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from core.db import get_session
from config import settings
from common.logger import get_logger

logger = get_logger("strategy_manager")

async def run_poll_loop():
    """
    Poll the strategy_configs table forever.
    If any enabled config exists, log its IDs.
    Otherwise, just say 'no configs' (and never crash).
    """
    async for session in get_session():
        while True:
            try:
                # Note the corrected table name: strategy_configs
                result = await session.execute(
                    text("SELECT id FROM strategy_config WHERE enabled = true")
                )
                rows = result.fetchall()
                if rows:
                    ids = [row[0] for row in rows]
                    logger.info(f"Found configs: {ids}")
                else:
                    logger.info("No configs found")
            except ProgrammingError as pe:
                # Either the table or column doesn't exist yet
                logger.warning(f"DB schema not ready: {pe}")
            except Exception as e:
                # Any other DB error
                logger.error(f"Unexpected DB error: {e}")
            # Sleep for the specified interval before polling again
            logger.debug(f"Sleeping for {settings.poll_interval} seconds...")
            await asyncio.sleep(settings.poll_interval)