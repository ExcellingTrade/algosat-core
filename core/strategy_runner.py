from sqlalchemy import select
from core.dbschema import strategies as strategies_table
from core.db import AsyncSessionLocal, get_strategy_name_by_id
import asyncio
from common.logger import get_logger
# from core.data_provider import get_data_provider
from core.execution_manager import get_execution_manager
from strategies.option_buy import OptionBuyStrategy
# from strategies.option_sell import OptionSellStrategy
# from strategies.swing_highlow import SwingHighLowStrategy
from core.data_provider.provider import DataProvider

logger = get_logger("strategy_runner")

# Map strategy names (as stored in config.strategy_name) to classes
STRATEGY_MAP = {
    "OptionBuy": OptionBuyStrategy,
    # "'OptionSell'": OptionSellStrategy,
    # "swing_highlow": SwingHighLowStrategy,
}

async def run_strategy_config(config_row, data_provider: DataProvider, execution_manager):
    """
    Given a strategy config row, identify and run the correct strategy.
    """
    # Determine the strategy key (name) from config_row or via lookup
    strategy_name = getattr(config_row, "strategy_name", None)
    if not strategy_name:
        # Fallback: fetch from strategies table using strategy_id
        async with AsyncSessionLocal() as session:
            strategy_name = await get_strategy_name_by_id(session, config_row.strategy_id)
    StrategyClass = STRATEGY_MAP.get(strategy_name)
    if not StrategyClass:
        logger.debug(f"No strategy class found for '{strategy_name}'")
        return

    # Instantiate strategy with injected DataProvider and ExecutionManager
    try:
        logger.debug(f"Instantiating strategy class {StrategyClass} with config_row type: {type(config_row)}")
        logger.debug(f"config_row: {repr(config_row)}")
        strategy = StrategyClass(config_row, data_provider, execution_manager)
    except Exception as e:
        logger.error(f"Exception during strategy instantiation: {e}", exc_info=True)
        return
    logger.info(f"Starting strategy '{strategy_name}' for config {getattr(config_row, 'symbol', None)}")

    # One-time setup with infinite exponential backoff retry if setup fails
    backoff = 5  # initial seconds
    max_backoff = 600  # max 10 minutes
    while True:
        try:
            await strategy.setup()
        except Exception as e:
            logger.error(f"Error during setup of '{strategy_name}': {e}", exc_info=True)
            # Always retry on any setup error
            logger.info(f"Retrying setup for '{strategy_name}' after {backoff} seconds (exception)...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)
            continue
        # Check for OptionBuyStrategy._setup_failed or similar flag
        if getattr(strategy, '_setup_failed', False):
            logger.warning(f"Setup failed for '{strategy_name}' (e.g., could not identify strikes). Retrying after {backoff} seconds...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)
            continue
        break  # setup succeeded

    # # Main loop: run_tick every poll_interval seconds
    # poll_interval = getattr(strategy, "poll_interval", getattr(config_row, "trade", {{}}).get("poll_interval", 60))
    # while True:
    #     try:
    #         await strategy.run_tick()
    #     except Exception as e:
    #         logger.error(f"Error in run_tick for '{strategy_name}': {e}", exc_info=True)
    #     await asyncio.sleep(poll_interval)
