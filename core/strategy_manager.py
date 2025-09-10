# algosat/core/strategy_manager.py

import asyncio
import datetime
from typing import Dict
from sqlalchemy.exc import ProgrammingError
from sqlalchemy import case, and_
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
from algosat.strategies.option_sell import OptionSellStrategy
from algosat.strategies.swing_highlow_sell import SwingHighLowSellStrategy
from algosat.utils.telegram_notify import telegram_bot, send_telegram_async

logger = get_logger("strategy_manager")
send_telegram_async("🚀 Strategy Manager initialized")

# 🕐 CENTRALIZED MARKET HOURS UTILITY
class MarketHours:
    """Centralized market hours management utility"""
    
    @staticmethod
    def get_market_hours():
        """Get default market hours (can be made configurable later)"""
        return datetime.time(9, 0), datetime.time(15, 30)  # 9:00 AM - 3:30 PM
        # return datetime.time(4, 0), datetime.time(23, 30)  # 9:00 AM - 3:30 PM
    
    @staticmethod
    def is_market_open(current_time: datetime.time = None) -> bool:
        """
        Check if market is currently open.
        
        Args:
            current_time: Time to check (defaults to current IST time)
            
        Returns:
            bool: True if market is open, False otherwise
        """
        if current_time is None:
            current_time = get_ist_datetime().time()
            
        market_start, market_end = MarketHours.get_market_hours()
        
        if market_start < market_end:
            return market_start <= current_time < market_end
        else:
            # Handle overnight markets (not applicable for Indian stock market but good practice)
            return market_start <= current_time or current_time < market_end
    
    @staticmethod
    def get_market_status_info(current_time: datetime.time = None) -> dict:
        """
        Get detailed market status information.
        
        Args:
            current_time: Time to check (defaults to current IST time)
            
        Returns:
            dict: Market status information
        """
        if current_time is None:
            current_time = get_ist_datetime().time()
            
        market_start, market_end = MarketHours.get_market_hours()
        is_open = MarketHours.is_market_open(current_time)
        
        return {
            'current_time': current_time,
            'market_start': market_start,
            'market_end': market_end,
            'is_open': is_open,
            'status': 'OPEN' if is_open else 'CLOSED'
        }

# Map strategy names (as stored in config.strategy_name) to classes
STRATEGY_MAP = {
    "OptionBuy": OptionBuyStrategy,
    "SwingHighLowBuy": SwingHighLowBuyStrategy,
    "OptionSell": OptionSellStrategy,
    "SwingHighLowSell": SwingHighLowSellStrategy,
}

# Strategy instance cache - indexed by symbol_id for sharing between components
strategy_cache: Dict[int, object] = {}

class RiskManager:
    """
    Manages risk limits at broker level and trade level.
    Monitors P&L and triggers emergency stops when limits are breached.
    """
    
    def __init__(self, order_manager: OrderManager):
        self.order_manager = order_manager
        self.emergency_stop_active = False
        
    async def check_broker_risk_limits(self):
        """
        Check if any broker has exceeded max_loss or max_profit limits.
        Returns tuple (breach_found: bool, broker_name: str, reason: str) for broker-specific handling.
        Only checks during market hours for efficiency.
        """
        # Skip risk checks during market close
        if not MarketHours.is_market_open():
            logger.debug("🌙 Market closed - skipping risk limit checks")
            return False, None, None
            
        try:
            from algosat.core.db import get_broker_risk_summary, AsyncSessionLocal
            
            async with AsyncSessionLocal() as session:
                risk_data = await get_broker_risk_summary(session)
                
                for broker in risk_data.get('brokers', []):
                    broker_name = broker.get('broker_name')
                    max_loss = broker.get('max_loss', 0)
                    max_profit = broker.get('max_profit', 0)
                    
                    # Calculate current P&L for this broker
                    current_pnl = await self._calculate_broker_pnl(session, broker_name)
                    
                    # Check if current loss exceeds max_loss
                    if current_pnl < -abs(max_loss):
                        logger.critical(f"🚨 BROKER RISK BREACH: {broker_name} exceeded max loss! "
                                      f"Current P&L: {current_pnl}, Max Loss: {max_loss}")
                        return True, broker_name, f"Max loss breached: P&L {current_pnl} vs limit {max_loss}"
                    
                    # Check if current profit exceeds max_profit (optional - for profit booking)
                    if max_profit > 0 and current_pnl > max_profit:
                        logger.critical(f"🚨 BROKER RISK BREACH: {broker_name} exceeded max profit! "
                                      f"Current P&L: {current_pnl}, Max Profit: {max_profit}")
                        return True, broker_name, f"Max profit target hit: P&L {current_pnl} vs target {max_profit}"
                        
                return False, None, None
                
        except Exception as e:
            logger.error(f"Error checking broker risk limits: {e}")
            return False, None, None
    
    async def _calculate_broker_pnl(self, session, broker_name: str) -> float:
        """
        Calculate current P&L for a specific broker using live broker positions.
        This fetches real-time P&L data directly from the broker instead of database calculations.
        More accurate and reflects real-time market conditions.
        
        Field mappings based on actual broker responses:
        - Fyers: uses 'overall.pl_realized' + 'overall.pl_unrealized' for total P&L
        - Zerodha: sums 'pnl' field from individual positions  
        - Angel: uses various P&L field names
        """
        try:
            # Get broker manager instance to fetch positions
            from algosat.core.broker_manager import BrokerManager
            
            # Create broker manager if not available
            if not hasattr(self, '_broker_manager'):
                self._broker_manager = BrokerManager()
            
            # Get the specific broker instance to fetch raw positions
            enabled_brokers = await self._broker_manager.get_all_trade_enabled_brokers()
            
            if broker_name not in enabled_brokers:
                logger.debug(f"Broker {broker_name} not found in enabled brokers")
                return 0.0
            
            broker = enabled_brokers[broker_name]
            if broker is None or not hasattr(broker, "get_positions"):
                logger.debug(f"Broker {broker_name} does not support get_positions")
                return 0.0
            
            # Fetch raw positions directly from broker (before processing)
            raw_positions = await broker.get_positions()
            
            # Calculate P&L based on broker-specific format
            total_pnl = 0.0
            
            if broker_name.lower() == 'fyers':
                # For Fyers: use overall P&L from raw response
                # Structure: {'netPositions': [...], 'overall': {'pl_realized': -2576.25, 'pl_unrealized': 0}}
                if isinstance(raw_positions, dict) and 'overall' in raw_positions:
                    overall = raw_positions.get('overall', {})
                    pl_realized = float(overall.get('pl_realized', 0.0))
                    pl_unrealized = float(overall.get('pl_unrealized', 0.0))
                    total_pnl = pl_realized + pl_unrealized
                    logger.debug(f"Fyers overall P&L for {broker_name}: realized={pl_realized}, unrealized={pl_unrealized}, total={total_pnl}")
                elif isinstance(raw_positions, dict) and 'netPositions' in raw_positions:
                    # Fallback: sum individual position 'pl' fields (which equal 'realized_profit')
                    net_positions = raw_positions.get('netPositions', [])
                    for position in net_positions:
                        position_pnl = float(position.get('pl', position.get('realized_profit', 0.0)))
                        total_pnl += position_pnl
                    logger.debug(f"Fyers individual P&L sum for {broker_name}: {total_pnl}")
                elif isinstance(raw_positions, list):
                    # Already processed netPositions list - sum 'pl' fields
                    for position in raw_positions:
                        position_pnl = float(position.get('pl', position.get('realized_profit', 0.0)))
                        total_pnl += position_pnl
                    logger.debug(f"Fyers netPositions P&L for {broker_name}: {total_pnl}")
            
            elif broker_name.lower() == 'zerodha':
                # For Zerodha: sum 'pnl' field from individual positions
                # Structure: [{'pnl': -15, ...}, {'pnl': 22.5, ...}, ...]
                positions_list = raw_positions if isinstance(raw_positions, list) else raw_positions.get('net', [])
                for position in positions_list:
                    # Zerodha uses 'pnl' field for total P&L per position
                    position_pnl = float(position.get('pnl', 0.0))
                    total_pnl += position_pnl
                logger.debug(f"Zerodha P&L for {broker_name}: {total_pnl} (from {len(positions_list)} positions)")
            
            elif broker_name.lower() == 'angel':
                # For Angel: positions structure may vary
                positions_list = raw_positions.get('data', raw_positions) if isinstance(raw_positions, dict) else raw_positions
                if isinstance(positions_list, list):
                    for position in positions_list:
                        # Angel may use different field names - check common ones
                        position_pnl = float(position.get('pnl', 
                                           position.get('unrealizedprofitandloss', 
                                           position.get('realizedprofitandloss', 
                                           position.get('totalprofitandloss', 0.0)))))
                        total_pnl += position_pnl
                logger.debug(f"Angel P&L for {broker_name}: {total_pnl}")
            
            else:
                # Generic approach for other brokers
                positions_list = raw_positions if isinstance(raw_positions, list) else raw_positions.get('positions', raw_positions.get('data', []))
                if isinstance(positions_list, list):
                    for position in positions_list:
                        # Try common P&L field names
                        position_pnl = float(position.get('pnl', 
                                           position.get('pl', 
                                           position.get('profit_loss', 
                                           position.get('realized_profit', 0.0)))))
                        total_pnl += position_pnl
                logger.debug(f"Generic P&L for {broker_name}: {total_pnl}")
            
            logger.info(f"Live P&L for broker {broker_name}: {total_pnl}")
            return total_pnl
            
        except Exception as e:
            logger.error(f"Error calculating live P&L for broker {broker_name}: {e}")
            return 0.0
    
    async def emergency_stop_all_strategies(self):
        """
        Emergency stop: Exit all orders and disable all strategies in database.
        This approach lets the normal polling logic handle stopping runners cleanly.
        """
        if self.emergency_stop_active:
            return
            
        self.emergency_stop_active = True
        logger.critical("🚨 INITIATING EMERGENCY STOP - EXITING ALL ORDERS AND DISABLING STRATEGIES")
        
        try:
            from algosat.core.db import get_active_strategy_symbols_with_configs, disable_strategy, AsyncSessionLocal
            
            async with AsyncSessionLocal() as session:
                # 1. Get all active strategy IDs that need to be disabled
                active_symbols = await get_active_strategy_symbols_with_configs(session)
                unique_strategy_ids = set(row.strategy_id for row in active_symbols)
                
                logger.critical(f"🚨 Disabling {len(unique_strategy_ids)} strategies: {list(unique_strategy_ids)}")
                
                # 2. Disable all active strategies in database
                for strategy_id in unique_strategy_ids:
                    try:
                        await disable_strategy(session, strategy_id)
                        logger.info(f"🚨 Disabled strategy ID: {strategy_id}")
                    except Exception as e:
                        logger.error(f"Error disabling strategy {strategy_id}: {e}")
                
                # 3. Commit the strategy disables
                await session.commit()
                
            # 4. Exit all active orders
            await self.order_manager.exit_all_orders(reason="Emergency Stop - Max Loss Exceeded")
            
            logger.critical("🚨 Emergency stop completed - strategies disabled, orders exited")
            logger.critical("🚨 Strategy runners will stop automatically on next poll cycle")
            
        except Exception as e:
            logger.error(f"Error during emergency stop: {e}")
            # If database operations fail, still try to exit orders
            try:
                await self.order_manager.exit_all_orders(reason="Emergency Stop - Error Fallback")
            except Exception as exit_error:
                logger.error(f"Failed to exit orders during emergency fallback: {exit_error}")
    
    async def emergency_stop_broker_orders(self, broker_name: str, reason: str = "Broker risk limit exceeded"):
        """
        Emergency stop for a specific broker: Exit all orders for that broker only.
        This keeps other brokers' orders open while closing only the problematic broker.
        
        Args:
            broker_name: Name of the broker to stop (e.g., "zerodha", "fyers")
            reason: Reason for the broker-specific emergency stop
        """
        try:
            logger.critical(f"🚨 BROKER-SPECIFIC EMERGENCY STOP: {broker_name} - {reason}")
            
            # Exit all orders for the specific broker only
            await self.order_manager.exit_all_orders(
                exit_reason=f"Broker Emergency Stop - {reason}",
                broker_names_filter=[broker_name]
            )
            
            logger.critical(f"🚨 Broker-specific emergency stop completed for {broker_name}")
            send_telegram_async(f"🛑⚠️ <b>BROKER EMERGENCY STOP</b> ⚠️🛑\n<b>Broker:</b> <code>{broker_name}</code>\n<b>Reason:</b> {reason}\n<b>Action:</b> Exited all orders for this broker only")
            
        except Exception as e:
            logger.error(f"Error during broker-specific emergency stop for {broker_name}: {e}")
            # If exit fails, log the error but don't raise to avoid stopping the monitoring loop
    
    def is_emergency_stop_active(self):
        """Check if emergency stop is currently active."""
        return self.emergency_stop_active
    
    def reset_emergency_stop(self):
        """Reset emergency stop (use with caution - should be manual intervention)."""
        self.emergency_stop_active = False
        logger.warning("🟡 Emergency stop has been reset")
    
    async def re_enable_strategies(self, strategy_ids: list = None):
        """
        Re-enable strategies after emergency stop.
        If strategy_ids is None, this would need manual specification of which strategies to re-enable.
        """
        if not self.emergency_stop_active:
            logger.warning("Cannot re-enable strategies - emergency stop is not active")
            return
        
        try:
            from algosat.core.db import update_strategy, AsyncSessionLocal
            
            if not strategy_ids:
                logger.error("strategy_ids must be specified for re-enabling strategies")
                return
            
            async with AsyncSessionLocal() as session:
                for strategy_id in strategy_ids:
                    try:
                        await update_strategy(session, strategy_id, {'enabled': True})
                        logger.info(f"🟢 Re-enabled strategy ID: {strategy_id}")
                    except Exception as e:
                        logger.error(f"Error re-enabling strategy {strategy_id}: {e}")
                
                await session.commit()
                
            # Reset emergency stop state
            self.reset_emergency_stop()
            logger.info("🟢 Strategies re-enabled and emergency stop reset")
            
        except Exception as e:
            logger.error(f"Error re-enabling strategies: {e}")

# Track running strategy runner tasks by config ID
running_tasks: Dict[int, asyncio.Task] = {}
order_monitors: Dict[str, asyncio.Task] = {}
order_queue = asyncio.Queue()

# Track configuration timestamps for change detection
config_timestamps: Dict[int, datetime.datetime] = {}

order_cache = None  # Will be initialized in run_poll_loop
risk_manager = None  # Will be initialized in run_poll_loop

async def create_lightweight_strategy_instance(symbol_id: int, config: StrategyConfig, data_manager: DataManager, order_manager: OrderManager):
    """
    Create a lightweight strategy instance WITHOUT setup() - just instantiation.
    Setup will be handled by the strategy runner task itself.
    Used for active strategy launches to ensure non-blocking task creation.
    """
    global strategy_cache
    
    # Use strategy_symbol_id (config.symbol_id) as cache key to support multiple configs per symbol
    cache_key = config.symbol_id if config.symbol_id else symbol_id
    
    logger.debug(f"🔧 Cache check for cache_key={cache_key}: cache_size={len(strategy_cache)}, keys={list(strategy_cache.keys())}")
    
    # Check if strategy instance already exists in cache
    if cache_key in strategy_cache:
        cached_instance = strategy_cache[cache_key]
        # Check if the cached instance has the correct configuration
        if hasattr(cached_instance, 'cfg') and hasattr(cached_instance.cfg, 'enable_smart_levels'):
            cached_smart_levels = cached_instance.cfg.enable_smart_levels
            new_smart_levels = config.enable_smart_levels
            if cached_smart_levels != new_smart_levels:
                logger.warning(f"🔧 Cache config mismatch for cache_key={cache_key}: cached={cached_smart_levels}, new={new_smart_levels}. Recreating instance.")
                # Remove the old cached instance and create a new one
                del strategy_cache[cache_key]
            else:
                logger.debug(f"Retrieved strategy instance from cache for cache_key={cache_key} (symbol_id={symbol_id}) - config matches")
                return cached_instance
        else:
            logger.debug(f"Retrieved strategy instance from cache for cache_key={cache_key} (symbol_id={symbol_id}) - no config check possible")
            return cached_instance
    
    # Create lightweight strategy instance (no setup)
    strategy_instance = await create_strategy_instance_only(config, data_manager, order_manager)
    
    # Store in cache if successfully created
    if strategy_instance:
        strategy_cache[cache_key] = strategy_instance
        logger.debug(f"Cached new lightweight strategy instance for cache_key={cache_key} (symbol_id={symbol_id})")
    
    return strategy_instance

async def get_strategy_for_order(order_id: str, data_manager: DataManager, order_manager: OrderManager):
    """
    Retrieve strategy instance for existing orders.
    Looks up order details and creates/retrieves strategy instance from cache.
    Used for existing orders on startup.
    """
    try:
        from algosat.core.db import get_order_with_strategy_config, AsyncSessionLocal
        
        # Get order with complete strategy configuration
        async with AsyncSessionLocal() as session:
            order_data = await get_order_with_strategy_config(session, int(order_id))
        
        if not order_data:
            logger.warning(f"No strategy config found for order_id={order_id}")
            return None
        
        # Extract symbol_id and create StrategyConfig
        symbol_id = order_data.get('symbol_id')
        if not symbol_id:
            logger.warning(f"No symbol_id found for order_id={order_id}")
            return None
        
        # Create StrategyConfig from order data
        config_dict = {
            'id': order_data.get('config_id'),
            'strategy_id': order_data.get('strategy_id'),
            'name': order_data.get('config_name'),
            'description': order_data.get('config_description'),
            'exchange': order_data.get('exchange'),
            'instrument': order_data.get('instrument'),
            'trade': order_data.get('trade_config'),
            'indicators': order_data.get('indicators_config'),
            'symbol': order_data.get('symbol'),
            'symbol_id': symbol_id,
            'strategy_key': order_data.get('strategy_key'),
            'strategy_name': order_data.get('strategy_name'),
            'order_type': order_data.get('order_type'),
            'product_type': order_data.get('product_type')
        }
        config = StrategyConfig(**config_dict)
        
        # Get or create strategy instance using caching
        strategy_instance = await create_lightweight_strategy_instance(symbol_id, config, data_manager, order_manager)
        
        return strategy_instance
        
    except Exception as e:
        logger.error(f"Error getting strategy for order_id={order_id}: {e}")
        return None

def remove_strategy_from_cache(strategy_symbol_id: int):
    """
    Remove strategy instance from cache when no longer needed.
    Called when strategies are stopped or cancelled.
    
    Args:
        strategy_symbol_id: The strategy_symbols.id (used as cache key)
    """
    global strategy_cache
    
    if strategy_symbol_id in strategy_cache:
        del strategy_cache[strategy_symbol_id]
        logger.debug(f"Removed strategy instance from cache for strategy_symbol_id={strategy_symbol_id}")
    else:
        logger.debug(f"No cache entry found for strategy_symbol_id={strategy_symbol_id}")

async def create_strategy_instance_only(config: StrategyConfig, data_manager: DataManager, order_manager: OrderManager):
    """
    Create strategy instance WITHOUT setup - just basic instantiation.
    This is lightweight and non-blocking. Setup will be handled by strategy runner.
    """
    strategy_name = getattr(config, "strategy_key", None)
    logger.debug(f"Creating lightweight strategy instance: '{strategy_name}' for config {config.symbol}")
    
    StrategyClass = STRATEGY_MAP.get(strategy_name)
    if not StrategyClass:
        logger.debug(f"No strategy class found for '{strategy_name}'")
        return None

    # Basic broker initialization (lightweight)
    symbol = config.symbol
    instrument_type = config.instrument
    await data_manager.ensure_broker()  # Ensure broker is initialized
    broker_name = data_manager.get_current_broker_name()
    
    # Get symbol info for strategy
    symbol_info = None
    if broker_name and symbol:
        symbol_info = await data_manager.get_broker_symbol(symbol, instrument_type)

    # Create strategy instance (lightweight - no setup)
    try:
        config_for_strategy = config.copy().dict()
        config_for_strategy['symbol_info'] = symbol_info
        if symbol_info and 'symbol' in symbol_info:
            config_for_strategy['symbol'] = symbol_info['symbol']
        
        strategy = StrategyClass(StrategyConfig(**config_for_strategy), data_manager, order_manager)
        logger.debug(f"✅ Created lightweight strategy instance: '{strategy_name}'")
        return strategy
        
    except Exception as e:
        logger.error(f"Exception during lightweight strategy instantiation: {e}", exc_info=True)
        return None

async def order_monitor_loop(order_queue, data_manager, order_manager):
    global order_cache
    while True:
        order_info = await order_queue.get()
        if order_info is None:
            logger.info("Order monitor received shutdown sentinel, exiting loop")
            break
        
        # Check if market is open before starting order monitoring
        if not MarketHours.is_market_open():
            logger.debug(f"🌙 Market closed. Skipping order monitor for order_id={order_info['order_id']}")
            continue  # Skip this order and get next one from queue
        
        order_id = order_info["order_id"]
        strategy_instance = order_info.get("strategy")  # Extract strategy instance from order_info
        
        # If no strategy instance provided (e.g., for existing orders), try to get from cache
        if strategy_instance is None:
            strategy_instance = await get_strategy_for_order(order_id, data_manager, order_manager)
        
        if order_id not in order_monitors:
            logger.debug(f"📊 Market open - starting order monitor for order_id={order_id}")
            monitor = OrderMonitor(
                order_id=order_id,
                data_manager=data_manager,
                order_manager=order_manager,
                order_cache=order_cache,
                strategy_instance=strategy_instance  # Pass strategy instance to OrderMonitor
            )
            order_monitors[order_id] = asyncio.create_task(monitor.start())
    logger.info("Order monitor loop has exited")

async def run_poll_loop(data_manager: DataManager, order_manager: OrderManager):
    global order_cache, risk_manager, config_timestamps, strategy_cache
    
    # Clear strategy cache on startup to ensure fresh instances
    logger.info("🧹 Clearing strategy cache on startup")
    strategy_cache.clear()
    
    # Initialize OrderCache and RiskManager (only during market hours)
    if order_cache is None:
        # Import the constant to keep cache and monitor intervals in sync
        from algosat.core.order_monitor import DEFAULT_ORDER_MONITOR_INTERVAL
        # Set cache refresh interval to match order monitoring frequency
        order_cache = OrderCache(order_manager, refresh_interval=DEFAULT_ORDER_MONITOR_INTERVAL)
        if MarketHours.is_market_open():
            market_info = MarketHours.get_market_status_info()
            logger.info(f"📈 Market is open ({market_info['current_time']}). Starting OrderCache with {DEFAULT_ORDER_MONITOR_INTERVAL}s refresh interval.")
            await order_cache.start()
        else:
            market_info = MarketHours.get_market_status_info()
            logger.info(f"🌙 Market is closed ({market_info['current_time']}). OrderCache initialized but not started.")
    
    if risk_manager is None:
        risk_manager = RiskManager(order_manager)
    
    # --- Start monitors for existing open orders on startup (only during market hours) ---
    if MarketHours.is_market_open():
        market_info = MarketHours.get_market_status_info()
        logger.info(f"📈 Market is open ({market_info['current_time']}). Starting order monitors for existing open orders.")
        from algosat.core.db import get_all_open_orders
        
        # Use a dedicated session for startup order loading
        async with AsyncSessionLocal() as startup_session:
            try:
                open_orders = await get_all_open_orders(startup_session)
                for order in open_orders:
                    # Get strategy instance for existing orders
                    order_id = str(order["id"])
                    strategy_instance = await get_strategy_for_order(order_id, data_manager, order_manager)
                    order_info = {"order_id": order["id"], "strategy": strategy_instance}
                    await order_queue.put(order_info)
                logger.info(f"📊 Queued {len(open_orders)} existing orders for monitoring")
            except Exception as e:
                logger.error(f"Error loading existing orders: {e}")
    else:
        market_info = MarketHours.get_market_status_info()
        logger.info(f"🌙 Market is closed ({market_info['current_time']}). Skipping order monitor startup.")
    
    # --- Start monitor loop for new orders ---
    asyncio.create_task(order_monitor_loop(order_queue, data_manager, order_manager))
    
    try:
        while True:
            try:
                # Get current IST time for all time-based logic
                now = get_ist_datetime().time()
                
                # 🚨 MARKET HOURS CHECK: Skip all operations during market close
                if not MarketHours.is_market_open(now):
                    # Market is closed - skip all strategy, order, and risk management operations
                    market_info = MarketHours.get_market_status_info(now)
                    logger.debug(f"🌙 Market closed (current: {now}, hours: {market_info['market_start']}-{market_info['market_end']}). Skipping all operations (strategies, orders, risk management).")
                    
                    # If any strategies are running, stop them during market close
                    if running_tasks:
                        logger.info(f"🛑 Market closed - stopping {len(running_tasks)} running strategies")
                        for symbol_id in list(running_tasks):
                            logger.debug(f"Stopping strategy for symbol {symbol_id} (market closed)")
                            running_tasks[symbol_id].cancel()
                            running_tasks.pop(symbol_id, None)
                            remove_strategy_from_cache(symbol_id)
                    
                    # Sleep and continue to next iteration without any processing (no risk checks, no order management)
                    logger.debug(f"⏳ Market closed - sleeping for {settings.poll_interval} seconds...")
                    await asyncio.sleep(settings.poll_interval)
                    continue
                
                # Market is open - proceed with normal operations
                market_info = MarketHours.get_market_status_info(now)
                logger.debug(f"📈 Market open (current: {now}, hours: {market_info['market_start']}-{market_info['market_end']}). Processing strategies, orders, and risk management.")
                
                # Start OrderCache if not already started (when market opens)
                if order_cache and not hasattr(order_cache, '_started'):
                    logger.info(f"📈 Market opened - starting OrderCache")
                    await order_cache.start()
                    order_cache._started = True
                
                # 🚨 PRIORITY 1: Check risk limits before any strategy operations (only during market hours)
                risk_limit_exceeded, breached_broker, breach_reason = await risk_manager.check_broker_risk_limits()
                
                if risk_limit_exceeded and not risk_manager.is_emergency_stop_active():
                    if breached_broker:
                        # Trigger broker-specific emergency stop (only exit orders for that broker)
                        await risk_manager.emergency_stop_broker_orders(breached_broker, breach_reason)
                    else:
                        # Fallback to full emergency stop if broker name is not available
                        await risk_manager.emergency_stop_all_strategies()
                
                # Continue normal strategy management (emergency stop disables strategies in DB)
                # The polling logic will naturally stop runners when no active symbols are found
                # Use a fresh session for each iteration to prevent connection pool exhaustion
                async with AsyncSessionLocal() as session:
                    active_symbols = await get_active_strategy_symbols_with_configs(session)
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
                                # Remove strategy from cache
                                remove_strategy_from_cache(symbol_id)

                        # Launch/stop tasks for symbols based on time (unified schedule for both product types)
                        for row in active_symbols:
                            logger.debug(f"Processing active symbol: {row.symbol} (ID: {row.symbol_id}, Strategy: {row.strategy_name})")
                            symbol_id = row.symbol_id
                            config_id = row.config_id
                            product_type = row.product_type  # Now comes from strategy table
                            
                            # Check for configuration changes
                            config_updated_at = getattr(row, 'config_updated_at', None)
                            strategy_updated_at = getattr(row, 'strategy_updated_at', None)
                            symbol_updated_at = getattr(row, 'symbol_updated_at', None)
                            latest_update = max(filter(None, [config_updated_at, strategy_updated_at, symbol_updated_at])) if any([config_updated_at, strategy_updated_at, symbol_updated_at]) else None
                            
                            # Detect configuration changes and restart strategy if needed
                            config_changed = False
                            if latest_update and symbol_id in config_timestamps:
                                if latest_update > config_timestamps[symbol_id]:
                                    config_changed = True
                                    # Debug logging to identify which component triggered the restart
                                    change_sources = []
                                    if config_updated_at and config_updated_at == latest_update:
                                        change_sources.append("config")
                                    if strategy_updated_at and strategy_updated_at == latest_update:
                                        change_sources.append("strategy")
                                    if symbol_updated_at and symbol_updated_at == latest_update:
                                        change_sources.append("symbol")
                                    logger.info(f"🔄 Configuration changed for symbol {symbol_id} (source: {'/'.join(change_sources)}), restarting strategy")
                                    if symbol_id in running_tasks:
                                        running_tasks[symbol_id].cancel()
                                        running_tasks.pop(symbol_id, None)
                                        remove_strategy_from_cache(symbol_id)
                            
                            # Update timestamp tracking
                            if latest_update:
                                config_timestamps[symbol_id] = latest_update
                            
                            # Unified schedule: 9:00 AM - 3:30 PM for both INTRADAY and DELIVERY
                            # Use configurable times with fallbacks
                            trade_config = row.trade_config or {}
                            # start_time_str = "04:00" #trade_config.get("start_time", "09:00")  # 9:00 AM default
                            start_time_str = trade_config.get("start_time", "09:00")  # 9:00 AM default
                            square_off_time_str = trade_config.get("square_off_time", "15:30")  # 3:30 PM default
                            # square_off_time_str = "23:30" #trade_config.get("square_off_time", "15:30")  # 3:30 PM default
                            
                            try:
                                st_time = datetime.datetime.strptime(start_time_str, "%H:%M").time()
                                sq_time = datetime.datetime.strptime(square_off_time_str, "%H:%M").time()
                            except ValueError:
                                # Fallback to default times if parsing fails
                                st_time = datetime.time(9, 0)   # 9:00 AM
                                sq_time = datetime.time(15, 30) # 3:30 PM
                                logger.warning(f"Invalid time format in config for symbol {symbol_id}, using defaults")
                            
                            def is_time_between(start, end, now):
                                if start < end:
                                    return start <= now < end
                                else:
                                    return start <= now or now < end
                            
                            # Check if current time is within trading hours (same logic for both product types)
                            if is_time_between(st_time, sq_time, now):
                                if symbol_id not in running_tasks or config_changed:
                                    logger.debug(f"Starting runner task for symbol {symbol_id} ({product_type}, trading hours: {start_time_str}-{square_off_time_str})")
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
                                        'product_type': row.product_type,
                                        'enable_smart_levels': row.enable_smart_levels
                                    }
                                    logger.debug(f"🔧 DEBUG: Building config for symbol_id {symbol_id} - enable_smart_levels from DB: {row.enable_smart_levels}, config_dict value: {config_dict['enable_smart_levels']}")
                                    config = StrategyConfig(**config_dict)
                                    logger.debug(f"🔧 DEBUG: Created StrategyConfig for symbol_id {symbol_id} - enable_smart_levels: {config.enable_smart_levels}")
                                    # Create lightweight strategy instance (no blocking setup)
                                    strategy_instance = await create_lightweight_strategy_instance(symbol_id, config, data_manager, order_manager)
                                    if strategy_instance:
                                        task = asyncio.create_task(run_strategy_config(strategy_instance, order_queue))
                                        running_tasks[symbol_id] = task
                            else:
                                # Outside trading hours - stop the strategy runner
                                if symbol_id in running_tasks:
                                    logger.info(f"Stopping runner for symbol {symbol_id} ({product_type}, outside trading hours: {start_time_str}-{square_off_time_str})")
                                    running_tasks[symbol_id].cancel()
                                    running_tasks.pop(symbol_id, None)
                                    # Remove strategy from cache
                                    remove_strategy_from_cache(symbol_id)
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
        # Clear strategy cache on shutdown
        strategy_cache.clear()
        for task in order_monitors.values():
            task.cancel()
        order_monitors.clear()
        return