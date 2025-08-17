import asyncio
from algosat.common.logger import get_logger, set_strategy_context
from algosat.common.strategy_utils import wait_for_next_candle


logger = get_logger("strategy_runner")

async def handle_strategy_setup(strategy, strategy_name):
    """
    Handle strategy setup with infinite exponential backoff retry.
    This can take hours if needed (e.g., waiting for first candle).
    Returns True if setup succeeded, False if it should be abandoned.
    """
    backoff = 5  # initial seconds
    max_backoff = 600  # max 10 minutes
    
    logger.info(f"Starting setup for strategy '{strategy_name}'...")
    
    while True:
        try:
            await strategy.setup()
            logger.info(f"✅ Setup completed for strategy '{strategy_name}'")
            return True
            
        except Exception as e:
            logger.error(f"Error during setup of '{strategy_name}': {e}", exc_info=True)
            logger.info(f"Retrying setup for '{strategy_name}' after {backoff} seconds (exception)...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)
            continue
            
        # Check for strategy-specific setup failure flags
        if getattr(strategy, '_setup_failed', False):
            logger.warning(f"Setup failed for '{strategy_name}' (e.g., could not identify strikes). Retrying after {backoff} seconds...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)
            continue
            
        # If we get here, setup succeeded
        break
    
    return True


async def run_strategy_config(strategy_instance, order_queue):
    """
    Run strategy with its own setup and main polling loop.
    The strategy instance is lightweight and needs setup before processing cycles.
    All logs from this strategy (and any managers it calls) will be routed 
    to strategy-specific log files automatically.
    """
    strategy = strategy_instance
    strategy_name = strategy.__class__.__name__
    
    # Extract strategy key for logging context (normalize to lowercase)
    strategy_key = getattr(strategy.cfg, 'strategy_key', strategy_name)
    strategy_context = strategy_key.lower() if strategy_key else strategy_name.lower()
    
    # Set strategy context for all operations in this task
    with set_strategy_context(strategy_context):
        logger.info(f"Starting strategy runner for '{strategy_name}' for config {strategy.cfg.symbol}")
        
        # STEP 1: Handle strategy setup with retries (can take hours if needed)
        setup_success = await handle_strategy_setup(strategy, strategy_name)
        if not setup_success:
            logger.error(f"Failed to setup strategy '{strategy_name}' after multiple retries. Exiting runner.")
            return
        
        logger.info(f"✅ Strategy '{strategy_name}' setup completed successfully. Starting main loop.")
        
        # STEP 2: Determine cycle interval based on strategy type
        cycle_interval_minutes = 5  # Default fallback
        
        if strategy_name in ["OptionBuyStrategy", "OptionSellStrategy"]:
            # Option strategies: get interval_minutes from trade parameters
            trade_params = getattr(strategy, "trade", None)
            if trade_params and isinstance(trade_params, dict):
                cycle_interval_minutes = trade_params.get("interval_minutes", 5)
            logger.debug(f"Option strategy '{strategy_name}' using trade interval: {cycle_interval_minutes} minutes")
            
        elif strategy_name in ["SwingHighLowBuyStrategy", "SwingHighLowSellStrategy"]:
            # Swing strategies: get confirm_minutes from class attribute
            confirm_minutes = getattr(strategy, "confirm_minutes", None)
            if confirm_minutes:
                cycle_interval_minutes = confirm_minutes
            logger.debug(f"Swing strategy '{strategy_name}' using entry interval: {cycle_interval_minutes} minutes")
            
        else:
            # Other strategies: try trade.interval_minutes as fallback
            trade_params = getattr(strategy, "trade", None)
            if trade_params and isinstance(trade_params, dict):
                cycle_interval_minutes = trade_params.get("interval_minutes", 5)
            logger.debug(f"Strategy '{strategy_name}' using default interval: {cycle_interval_minutes} minutes")

        logger.info(f"Strategy '{strategy_name}' will process cycles every {cycle_interval_minutes} minutes")

        # STEP 3: Main strategy loop
        while True:
            try:
                order_result = await strategy.process_cycle()
                logger.info(f"Processed cycle for strategy '{strategy_name}' with order result: {order_result}")
                # Only push to queue if order was placed successfully
                if order_result and isinstance(order_result, dict) and order_result.get("order_id"):
                    # Queue the main order for monitoring
                    await order_queue.put({
                        "order_id": order_result["order_id"],
                        "strategy": strategy
                    })
                    
                    # Also queue hedge order if present
                    hedge_order_id = order_result.get("hedge_order_id")
                    if hedge_order_id:
                        logger.info(f"Queueing hedge order {hedge_order_id} for monitoring")
                        await order_queue.put({
                            "order_id": hedge_order_id,
                            "strategy": strategy
                        })
            except Exception as e:
                logger.error(f"Error in process_cycle for '{strategy_name}': {e}", exc_info=True)
            
            try:
                await wait_for_next_candle(cycle_interval_minutes)
            except Exception as e:
                logger.error(f"Error in wait_for_next_candle for '{strategy_name}': {e}", exc_info=True)
