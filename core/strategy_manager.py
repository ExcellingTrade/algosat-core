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

logger = get_logger("strategy_manager")

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
        self._positions_cache = None
        self._cache_timestamp = None
        self._cache_duration = 30  # Cache for 30 seconds
        
    async def check_broker_risk_limits(self):
        """
        Check if any broker has exceeded max_loss or max_profit limits.
        Returns True if emergency stop should be triggered.
        Only checks during market hours for efficiency.
        """
        # Skip risk checks during market close
        if not MarketHours.is_market_open():
            logger.debug("🌙 Market closed - skipping risk limit checks")
            return False
            
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
                        logger.critical(f"🚨 EMERGENCY STOP: Broker {broker_name} exceeded max loss! "
                                      f"Current P&L: {current_pnl}, Max Loss: {max_loss}")
                        return True
                    
                    # Check if current profit exceeds max_profit (optional - for profit booking)
                    if max_profit > 0 and current_pnl > max_profit:
                        logger.critical(f"🚨 EMERGENCY STOP: Broker {broker_name} exceeded max profit! "
                                      f"Current P&L: {current_pnl}, Max Profit: {max_profit}")
                        return True
                        
                return False
                
        except Exception as e:
            logger.error(f"Error checking broker risk limits: {e}")
            return False
    
    async def _calculate_broker_pnl(self, session, broker_name: str) -> float:
        """
        Calculate current P&L for a specific broker using actual broker positions.
        This matches entry executions with current positions to get real P&L from broker APIs.
        """
        try:
            from algosat.core.dbschema import broker_executions
            from sqlalchemy import select, func
            from datetime import date
            
            # Get all broker positions (with cache)
            all_positions = await self._get_all_broker_positions_with_cache()
            if not all_positions or broker_name.lower() not in all_positions:
                logger.debug(f"No positions found for broker {broker_name}")
                return 0.0
            
            broker_positions = all_positions.get(broker_name.lower(), [])
            total_pnl = 0.0
            
            # Get today's ENTRY executions for this broker
            today = date.today()
            entry_query = select(broker_executions).where(
                and_(
                    broker_executions.c.broker_name == broker_name,
                    broker_executions.c.side == 'ENTRY',
                    func.date(broker_executions.c.execution_time) == today
                )
            )
            
            entry_executions = await session.execute(entry_query)
            entry_executions = entry_executions.fetchall()
            
            # Match entry executions with current positions (similar to OrderMonitor logic)
            for execution in entry_executions:
                symbol_val = execution.symbol
                execution_price = float(execution.execution_price)
                product_type = execution.product_type
                executed_qty = execution.executed_quantity
                action = execution.action
                
                # Find matching position using broker-specific logic
                matched_pos = None
                
                if broker_name.lower() == "zerodha":
                    for pos in broker_positions:
                        try:
                            # Match by tradingsymbol, product, and buy_quantity
                            product_match = (str(pos.get('product')).upper() == str(product_type).upper()) if product_type else True
                            entry_price_match = (float(pos.get('buy_price', 0)) == float(execution_price)) if execution_price else True
                            qty_match = (int(pos.get('buy_quantity', 0)) == int(executed_qty)) or (int(pos.get('overnight_quantity', 0)) == int(executed_qty))
                            
                            if (pos.get('tradingsymbol') == symbol_val and 
                                qty_match and product_match and entry_price_match):
                                matched_pos = pos
                                break
                        except Exception as e:
                            logger.error(f"Error matching Zerodha position: {e}")
                
                elif broker_name.lower() == "fyers":
                    for pos in broker_positions:
                        try:
                            # Fyers fields: 'symbol', 'qty', 'productType', 'buyAvg', 'side'
                            product_match = (str(pos.get('productType')).upper() == str(product_type).upper()) if product_type else True
                            qty_match = (int(pos.get('buyQty', 0)) == int(executed_qty))
                            symbol_match = (pos.get('symbol') == symbol_val)
                            
                            if symbol_match and qty_match and product_match:
                                matched_pos = pos
                                break
                        except Exception as e:
                            logger.error(f"Error matching Fyers position: {e}")
                
                elif broker_name.lower() == "angel":
                    # Add Angel One specific matching logic here
                    for pos in broker_positions:
                        try:
                            # Assuming Angel has similar fields - adjust as needed
                            product_match = (str(pos.get('product')).upper() == str(product_type).upper()) if product_type else True
                            symbol_match = (pos.get('symbol') == symbol_val or pos.get('tradingsymbol') == symbol_val)
                            
                            if symbol_match and product_match:
                                matched_pos = pos
                                break
                        except Exception as e:
                            logger.error(f"Error matching Angel position: {e}")
                
                # Extract P&L from matched position
                if matched_pos:
                    pnl_val = 0.0
                    
                    if broker_name.lower() == "zerodha":
                        pnl_val = float(matched_pos.get('pnl', 0))
                    elif broker_name.lower() == "fyers":
                        pnl_val = float(matched_pos.get('pl', 0))
                    elif broker_name.lower() == "angel":
                        # Angel might use 'pnl' or 'unrealisedpnl' - adjust as needed
                        pnl_val = float(matched_pos.get('pnl', 0)) or float(matched_pos.get('unrealisedpnl', 0))
                    
                    total_pnl += pnl_val
                    logger.debug(f"Matched position P&L for {symbol_val}: {pnl_val} (Broker: {broker_name})")
            
            logger.debug(f"Total calculated P&L for broker {broker_name}: {total_pnl}")
            return float(total_pnl)
            
        except Exception as e:
            logger.error(f"Error calculating P&L for broker {broker_name}: {e}")
            return 0.0
    
    async def _get_all_broker_positions_with_cache(self):
        """
        Get all broker positions with caching (similar to OrderMonitor approach).
        Returns dict: {'fyers': [...], 'zerodha': [...], 'angel': [...]}
        """
        try:
            import time
            
            # Check cache validity
            current_time = time.time()
            if (self._positions_cache is not None and 
                self._cache_timestamp is not None and 
                (current_time - self._cache_timestamp) < self._cache_duration):
                logger.debug("Using cached broker positions")
                return self._positions_cache
            
            # Cache expired or doesn't exist, fetch fresh data
            logger.debug("Fetching fresh broker positions")
            
            # Get all positions using broker_manager (same as OrderMonitor)
            if hasattr(self.order_manager, 'broker_manager'):
                all_positions = await self.order_manager.broker_manager.get_all_broker_positions()
            else:
                logger.warning("order_manager.broker_manager not found - using empty positions")
                all_positions = {}
            
            # Cache the results
            self._positions_cache = all_positions
            self._cache_timestamp = current_time
            
            logger.debug(f"Cached positions for brokers: {list(all_positions.keys()) if all_positions else 'None'}")
            return all_positions
            
        except Exception as e:
            logger.error(f"Error fetching broker positions: {e}")
            return {}
    
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
    
    # Check if strategy instance already exists in cache
    if symbol_id in strategy_cache:
        logger.debug(f"Retrieved strategy instance from cache for symbol_id={symbol_id}")
        return strategy_cache[symbol_id]
    
    # Create lightweight strategy instance (no setup)
    strategy_instance = await create_strategy_instance_only(config, data_manager, order_manager)
    
    # Store in cache if successfully created
    if strategy_instance:
        strategy_cache[symbol_id] = strategy_instance
        logger.debug(f"Cached new lightweight strategy instance for symbol_id={symbol_id}")
    
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

def remove_strategy_from_cache(symbol_id: int):
    """
    Remove strategy instance from cache when no longer needed.
    Called when strategies are stopped or cancelled.
    """
    global strategy_cache
    
    if symbol_id in strategy_cache:
        del strategy_cache[symbol_id]
        logger.debug(f"Removed strategy instance from cache for symbol_id={symbol_id}")

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
    global order_cache, risk_manager, config_timestamps
    
    # Initialize OrderCache and RiskManager (only during market hours)
    if order_cache is None:
        order_cache = OrderCache(order_manager)
        if MarketHours.is_market_open():
            market_info = MarketHours.get_market_status_info()
            logger.info(f"📈 Market is open ({market_info['current_time']}). Starting OrderCache.")
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
                risk_limit_exceeded = await risk_manager.check_broker_risk_limits()
                
                if risk_limit_exceeded and not risk_manager.is_emergency_stop_active():
                    # Trigger emergency stop (only during market hours)
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
                            symbol_id = row.symbol_id
                            config_id = row.config_id
                            product_type = row.product_type  # Now comes from strategy table
                            
                            # Check for configuration changes
                            config_updated_at = getattr(row, 'config_updated_at', None)
                            strategy_updated_at = getattr(row, 'strategy_updated_at', None)
                            latest_update = max(config_updated_at, strategy_updated_at) if config_updated_at and strategy_updated_at else (config_updated_at or strategy_updated_at)
                            
                            # Detect configuration changes and restart strategy if needed
                            config_changed = False
                            if latest_update and symbol_id in config_timestamps:
                                if latest_update > config_timestamps[symbol_id]:
                                    config_changed = True
                                    logger.info(f"🔄 Configuration changed for symbol {symbol_id}, restarting strategy")
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
                                    config = StrategyConfig(**config_dict)
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