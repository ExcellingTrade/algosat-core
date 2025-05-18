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
    strategy = StrategyClass(config_row, data_provider, execution_manager)
    logger.info(f"Starting strategy '{strategy_name}' for config {config_row.symbol}")

    # One-time setup
    try:
        await strategy.setup()
    except Exception as e:
        logger.error(f"Error during setup of '{strategy_name}': {e}", exc_info=True)
        return

    # # Main loop: run_tick every poll_interval seconds
    # poll_interval = getattr(strategy, "poll_interval", getattr(config_row, "trade", {{}}).get("poll_interval", 60))
    # while True:
    #     try:
    #         await strategy.run_tick()
    #     except Exception as e:
    #         logger.error(f"Error in run_tick for '{strategy_name}': {e}", exc_info=True)
    #     await asyncio.sleep(poll_interval)
