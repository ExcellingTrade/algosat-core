from datetime import timedelta
import asyncio
from sqlalchemy import select
from algosat.core.dbschema import strategies as strategies_table
from algosat.core.db import AsyncSessionLocal, get_strategy_name_by_id
from algosat.common.logger import get_logger
from algosat.core.execution_manager import get_execution_manager
from algosat.strategies.option_buy import OptionBuyStrategy
# from strategies.option_sell import OptionSellStrategy
# from strategies.swing_highlow import SwingHighLowStrategy
from algosat.core.data_manager import DataManager
from algosat.core.time_utils import get_ist_datetime, localize_to_ist
from algosat.core.order_manager import OrderManager
from algosat.core.order_monitor import OrderMonitor
from algosat.models.strategy_config import StrategyConfig


logger = get_logger("strategy_runner")

# Map strategy names (as stored in config.strategy_name) to classes
STRATEGY_MAP = {
    "OptionBuy": OptionBuyStrategy,
    # "'OptionSell'": OptionSellStrategy,
    # "swing_highlow": SwingHighLowStrategy,
}

async def run_strategy_config(config_row, data_manager: DataManager, order_manager: OrderManager, order_queue):
    """
    Given a strategy config row, identify and run the correct strategy.
    """
    # Convert config_row to StrategyConfig dataclass
    if not isinstance(config_row, StrategyConfig):
        # Accepts dict, SQLAlchemy row, or namedtuple
        if hasattr(config_row, '_mapping'):
            config_dict = dict(config_row._mapping)
        elif isinstance(config_row, dict):
            config_dict = config_row
        else:
            config_dict = dict(config_row)
        config = StrategyConfig(**config_dict)
    else:
        config = config_row

    strategy_name = getattr(config, "strategy_name", None)
    if not strategy_name:
        # Fallback: fetch from strategies table using strategy_id
        async with AsyncSessionLocal() as session:
            strategy_name = await get_strategy_name_by_id(session, config.strategy_id)
    StrategyClass = STRATEGY_MAP.get(strategy_name)
    if not StrategyClass:
        logger.debug(f"No strategy class found for '{strategy_name}'")
        return

    # --- Ensure broker is initialized and resolve symbol/token upfront ---
    symbol = config.symbol
    instrument_type = config.instrument
    await data_manager.ensure_broker()  # Ensure broker is initialized
    broker_name = data_manager.get_current_broker_name()
    resolved_symbol = symbol
    if broker_name and symbol:
        # Use DataManager's get_broker_symbol to resolve
        symbol_info = await data_manager.get_broker_symbol(symbol, instrument_type)
        resolved_symbol = symbol_info.get('instrument_token', symbol_info.get('symbol', symbol))

    # Pass StrategyConfig to strategy
    try:
        logger.debug(f"Instantiating strategy class {StrategyClass} with config type: {type(config)}")
        config_for_strategy = config.copy().dict()
        # Get symbol_info from broker
        symbol_info = None
        if broker_name and symbol:
            symbol_info = await data_manager.get_broker_symbol(symbol, instrument_type)
        config_for_strategy['symbol_info'] = symbol_info
        # Optionally, for backward compatibility, set 'symbol' to symbol_info['symbol'] if present
        if symbol_info and 'symbol' in symbol_info:
            config_for_strategy['symbol'] = symbol_info['symbol']
        strategy = StrategyClass(StrategyConfig(**config_for_strategy), data_manager, order_manager)
    except Exception as e:
        logger.error(f"Exception during strategy instantiation: {e}", exc_info=True)
        return
    logger.info(f"Starting strategy '{strategy_name}' for config {config.symbol}")

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

    # Main loop: run_tick every interval_minutes candle
    # Use self.trade if available, else fallback to config_row
    interval_minutes = getattr(strategy, "trade", None)
    if interval_minutes:
        interval_minutes = interval_minutes.get("interval_minutes", 5)
    else:
        interval_minutes = getattr(config_row, "trade", {}) and getattr(config_row, "trade", {}).get("interval_minutes", 5)

    # Only show progress bar for the first strategy instance (e.g., first symbol)
    # For others, just log the wait time
    async def wait_for_next_candle(interval_minutes):
        try:
            current_time = get_ist_datetime()
            next_candle_start = (
                current_time + timedelta(minutes=interval_minutes - current_time.minute % interval_minutes)
            ).replace(second=0, microsecond=0)
            wait_time = max(1, math.ceil((localize_to_ist(next_candle_start) - current_time).total_seconds()))
            logger.info(f"Waiting {wait_time} seconds for the next candle ({getattr(strategy, 'symbol', 'Unknown')}).")
            await asyncio.sleep(wait_time)
        except Exception as e:
            logger.error(f"Error in wait_for_next_candle: {e}", exc_info=True)

    while True:
        try:
            order_info = await strategy.process_cycle()
            # If an order was placed, put it in the order_queue for the manager to monitor
            if order_info and isinstance(order_info, dict) and "order_id" in order_info:
                await order_queue.put({
                    "order_id": order_info["order_id"],
                    "config": config_row,
                    "interval_minutes": interval_minutes
                })
        except Exception as e:
            logger.error(f"Error in run_tick for '{strategy_name}': {e}", exc_info=True)
        try:
            await wait_for_next_candle(interval_minutes)
        except Exception as e:
            logger.error(f"Error in wait_for_next_candle for '{strategy_name}': {e}", exc_info=True)
