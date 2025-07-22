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

    # Main loop: run process_cycle every interval_minutes candle
    # Use strategy.trade if available for interval_minutes
    interval_minutes = getattr(strategy, "trade", None)
    if interval_minutes:
        interval_minutes = interval_minutes.get("interval_minutes", 5)
    else:
        interval_minutes = 5

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
            await wait_for_next_candle(interval_minutes)
        except Exception as e:
            logger.error(f"Error in wait_for_next_candle for '{strategy_name}': {e}", exc_info=True)
