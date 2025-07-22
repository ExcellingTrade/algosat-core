# algosat/core/strategy_manager.py

import asyncio
import datetime
from typing import Dict
from sqlalchemy.exc import ProgrammingError
from algosat.core.db import get_active_strategy_symbols_with_configs, AsyncSessionLocal
from algosat.config import settings
from algosat.common.logger import get_logger
from algosat.core.strategy_runner import run_strategy_config
from algosat.core.data_manager import DataManager
from algosat.core.order_manager import OrderManager
from algosat.core.order_monitor import OrderMonitor
from algosat.core.time_utils import get_ist_datetime
from algosat.models.strategy_config import StrategyConfig
from algosat.core.order_cache import OrderCache
from algosat.strategies.option_buy import OptionBuyStrategy
from algosat.strategies.swing_highlow_buy import SwingHighLowBuyStrategy

logger = get_logger("strategy_manager")

# Map strategy names (as stored in config.strategy_name) to classes
STRATEGY_MAP = {
    "OptionBuy": OptionBuyStrategy,
    "SwingHighLowBuy": SwingHighLowBuyStrategy,
}

# Track running strategy runner tasks by config ID
running_tasks: Dict[int, asyncio.Task] = {}
order_monitors: Dict[str, asyncio.Task] = {}
order_queue = asyncio.Queue()

order_cache = None  # Will be initialized in run_poll_loop

async def initialize_strategy_instance(config: StrategyConfig, data_manager: DataManager, order_manager: OrderManager):
    """
    Initialize a strategy instance with proper setup including broker initialization and symbol resolution.
    This function moves the initialization logic from strategy_runner.py to strategy_manager.py
    to enable strategy instance sharing between multiple files.
    """
    strategy_name = getattr(config, "strategy_key", None)
    logger.debug(f"Config id: {getattr(config, 'id', None)}, strategy_name resolved: '{strategy_name}'")
    
    StrategyClass = STRATEGY_MAP.get(strategy_name)
    if not StrategyClass:
        logger.debug(f"No strategy class found for '{strategy_name}'")
        return None

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
        return None

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

    return strategy

async def order_monitor_loop(order_queue, data_manager, order_manager):
    global order_cache
    while True:
        order_info = await order_queue.get()
        if order_info is None:
            logger.info("Order monitor received shutdown sentinel, exiting loop")
            break
        order_id = order_info["order_id"]
        if order_id not in order_monitors:
            monitor = OrderMonitor(
                order_id=order_id,
                data_manager=data_manager,
                order_manager=order_manager,
                order_cache=order_cache
            )
            order_monitors[order_id] = asyncio.create_task(monitor.start())
    logger.info("Order monitor loop has exited")

async def run_poll_loop(data_manager: DataManager, order_manager: OrderManager):
    global order_cache
    # Initialize OrderCache with the order_manager
    if order_cache is None:
        order_cache = OrderCache(order_manager)
        await order_cache.start()
    # --- Start monitors for existing open orders on startup ---
    from algosat.core.db import get_all_open_orders
    async with AsyncSessionLocal() as session:
        open_orders = await get_all_open_orders(session)
        for order in open_orders:
            # You may need to fetch the strategy instance/config for this order
            # For now, pass None or fetch as needed
            order_info = {"order_id": order["id"]}
            await order_queue.put(order_info)
    # --- Existing: Start monitor loop for new orders ---
    asyncio.create_task(order_monitor_loop(order_queue, data_manager, order_manager))
    try:
        async with AsyncSessionLocal() as session:
            while True:
                try:
                    active_symbols = await get_active_strategy_symbols_with_configs(session)
                    now = get_ist_datetime().time()  # Use IST time for all time logic
                    if active_symbols:
                        # Only print found symbols the first time
                        if not running_tasks:
                            logger.info(f"🟢 Found active symbols: {[f"{row.symbol}-{row.strategy_name}" for row in active_symbols]}")
                        current_symbol_ids = {row.symbol_id for row in active_symbols}
                        

                        # Cancel tasks for symbols no longer active
                        for symbol_id in list(running_tasks):
                            if symbol_id not in current_symbol_ids:
                                logger.info(f"🟡 Cancelling runner for symbol {symbol_id}")
                                running_tasks[symbol_id].cancel()
                                running_tasks.pop(symbol_id, None)

                        # Launch/stop tasks for symbols based on time and product_type
                        for row in active_symbols:
                            symbol_id = row.symbol_id
                            product_type = row.product_type  # Now comes from strategy table
                            # Use default times if not specified in trade_config
                            trade_config = row.trade_config or {}
                            square_off_time = trade_config.get("square_off_time", "15:15")
                            start_time = trade_config.get("start_time", "09:15")
                            sq_time = datetime.datetime.strptime(square_off_time, "%H:%M").time()
                            st_time = datetime.datetime.strptime(start_time, "%H:%M").time()
                            st_time = st_time.replace(hour=4, minute=0)  # Adjust start time to 4 AM
                            sq_time = sq_time.replace(hour=21, minute=0)  # Adjust stop time to 4 AM
                            def is_time_between(start, end, now):
                                if start < end:
                                    return start <= now < end
                                else:
                                    return start <= now or now < end
                            if product_type == "INTRADAY":
                                if is_time_between(st_time, sq_time, now):
                                    if symbol_id not in running_tasks:
                                        logger.debug(f"Starting runner task for symbol {symbol_id} (intraday window)")
                                        # Create StrategyConfig from symbol data
                                        config_dict = {
                                            'id': row.config_id,
                                            'strategy_id': row.strategy_id,
                                            'name': row.config_name,
                                            'description': row.config_description,
                                            'exchange': row.exchange,
                                            'instrument': row.instrument,
                                            'trade': row.trade_config,
                                            'indicators': row.indicators_config,
                                            'symbol': row.symbol,
                                            'symbol_id': row.symbol_id,
                                            'strategy_key': row.strategy_key,
                                            'strategy_name': row.strategy_name,
                                            'order_type': row.order_type,
                                            'product_type': row.product_type
                                        }
                                        config = StrategyConfig(**config_dict)
                                        # Initialize strategy instance with setup
                                        strategy_instance = await initialize_strategy_instance(config, data_manager, order_manager)
                                        if strategy_instance:
                                            task = asyncio.create_task(run_strategy_config(strategy_instance, order_queue))
                                            running_tasks[symbol_id] = task
                                else:
                                    if symbol_id in running_tasks:
                                        logger.info(f"Stopping intraday runner for symbol {symbol_id} (outside window)")
                                        running_tasks[symbol_id].cancel()
                                        running_tasks.pop(symbol_id, None)
                            else:  # DELIVERY
                                # Optionally, stop at night (e.g., 00:00-06:00), else run 24/7
                                # To always run, comment out the next 4 lines
                                if is_time_between(datetime.time(0,0), datetime.time(6,0), now):
                                    if symbol_id in running_tasks:
                                        logger.info(f"Stopping delivery runner for symbol {symbol_id} (maintenance window)")
                                        running_tasks[symbol_id].cancel()
                                        running_tasks.pop(symbol_id, None)
                                else:
                                    if symbol_id not in running_tasks:
                                        logger.debug(f"Starting runner task for symbol {symbol_id} (delivery)")
                                        # Create StrategyConfig from symbol data
                                        config_dict = {
                                            'id': row.config_id,
                                            'strategy_id': row.strategy_id,
                                            'name': row.config_name,
                                            'description': row.config_description,
                                            'exchange': row.exchange,
                                            'instrument': row.instrument,
                                            'trade': row.trade_config,
                                            'indicators': row.indicators_config,
                                            'symbol': row.symbol,
                                            'symbol_id': row.symbol_id,
                                            'strategy_key': row.strategy_key,
                                            'strategy_name': row.strategy_name,
                                            'order_type': row.order_type,
                                            'product_type': row.product_type
                                        }
                                        config = StrategyConfig(**config_dict)
                                        # Initialize strategy instance with setup
                                        strategy_instance = await initialize_strategy_instance(config, data_manager, order_manager)
                                        if strategy_instance:
                                            task = asyncio.create_task(run_strategy_config(strategy_instance, order_queue))
                                            running_tasks[symbol_id] = task
                    else:
                        logger.info("🟡 No active symbols found")
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