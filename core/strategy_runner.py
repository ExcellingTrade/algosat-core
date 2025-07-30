import asyncio
from algosat.common.logger import get_logger
from algosat.common.strategy_utils import wait_for_next_candle


logger = get_logger("strategy_runner")

async def run_strategy_config(strategy_instance, order_queue):
    """
    Given an initialized strategy instance, run the main polling loop.
    The strategy instance is already set up and ready to process cycles.
    """
    strategy = strategy_instance
    strategy_name = strategy.__class__.__name__
    
    logger.info(f"Starting strategy polling loop for '{strategy_name}' for config {strategy.cfg.symbol}")

    # Determine cycle interval based on strategy type
    # For Option strategies: use trade.interval_minutes
    # For Swing strategies: use confirm_minutes from class
    cycle_interval_minutes = 5  # Default fallback
    
    if strategy_name in ["OptionBuy", "OptionSell"]:
        # Option strategies: get interval_minutes from trade parameters
        trade_params = getattr(strategy, "trade", None)
        if trade_params and isinstance(trade_params, dict):
            cycle_interval_minutes = trade_params.get("interval_minutes", 5)
        logger.debug(f"Option strategy '{strategy_name}' using trade interval: {cycle_interval_minutes} minutes")
        
    elif strategy_name in ["SwingHighLowBuy", "SwingHighLowSell"]:
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

    while True:
        try:
            order_result = await strategy.process_cycle()
            logger.info(f"Processed cycle for strategy '{strategy_name}' with order result: {order_result}")
            # Only push to queue if order was placed successfully
            if order_result and isinstance(order_result, dict) and order_result.get("order_id"):
                await order_queue.put({
                    "order_id": order_result["order_id"],
                    "strategy": strategy
                })
        except Exception as e:
            logger.error(f"Error in process_cycle for '{strategy_name}': {e}", exc_info=True)
        try:
            await wait_for_next_candle(cycle_interval_minutes)
        except Exception as e:
            logger.error(f"Error in wait_for_next_candle for '{strategy_name}': {e}", exc_info=True)
