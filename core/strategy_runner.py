import asyncio
from strategies.option_buy import OptionBuyStrategy
from core.data_provider.provider import DataProvider
from common.logger import get_logger

logger = get_logger("strategy_runner")

# Placeholder for ExecutionManager (to be implemented)
class ExecutionManager:
    async def execute(self, config, order):
        logger.info(f"[MOCK] Executing order: {order} for config: {config.id}")
        return {"status": "mock_executed", "order": order}

async def run_strategy_config(config_row):
    """
    Given a strategy config row, instantiate and run the OptionBuy strategy.
    """
    # Only OptionBuy for now
    config = config_row
    data_provider = DataProvider()
    execution_manager = ExecutionManager()
    strategy = OptionBuyStrategy(config, data_provider, execution_manager)
    logger.info(f"Starting OptionBuy strategy for config {config.id} ({config.symbol})")
    await strategy.setup()
    # Main loop: run_tick every poll_interval (from config or default)
    poll_interval = getattr(strategy, "poll_interval", 60)
    while True:
        try:
            await strategy.run_tick()
        except Exception as e:
            logger.error(f"Error in run_tick: {e}")
        await asyncio.sleep(poll_interval)
