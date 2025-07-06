from __future__ import annotations
from typing import Optional, Any
import asyncio
from datetime import datetime
from algosat.common.logger import get_logger
from algosat.models.order_aggregate import OrderAggregate

from algosat.core.data_manager import DataManager
from algosat.core.order_manager import FYERS_STATUS_MAP, OrderManager
from algosat.core.order_cache import OrderCache
from algosat.core.order_request import OrderStatus
from algosat.common.strategy_utils import wait_for_next_candle, fetch_strikes_history

logger = get_logger("OrderMonitor")

class OrderMonitor:
    def __init__(
        self,
        order_id: int,
        data_manager: DataManager,
        order_manager: OrderManager,
        order_cache: OrderCache,  # new dependency
        price_order_monitor_seconds: float = 60.0,  # 1 minute default
        signal_monitor_minutes: int = None  # will be set from strategy config
    ):
        self.order_id: int = order_id
        self.data_manager: DataManager = data_manager
        self.order_manager: OrderManager = order_manager
        self.order_cache: OrderCache = order_cache
        self.price_order_monitor_seconds: float = price_order_monitor_seconds
        self.signal_monitor_minutes: int = signal_monitor_minutes
        self._running: bool = True
        # Track last main order status to avoid redundant DB updates
        self._last_main_status = None
        # Track last broker order statuses to avoid redundant broker_execs updates
        self._last_broker_statuses = {}
        # Unified cache: order_id -> (order, strategy_symbol, strategy)
        self._order_strategy_cache = {}
        # self._db_session = None  # Will be set when needed

    async def _get_order_and_strategy(self, order_id: int):
        """
        Fetch order, strategy_symbol, and strategy for this order_id, cache the result.
        Returns (order, strategy_symbol, strategy) tuple. Always checks cache first.
        If order is missing, logs error and stops the monitor.
        """
        # Check cache first
        if order_id in self._order_strategy_cache:
            return self._order_strategy_cache[order_id]
        # Lazy-load session if not present
        from algosat.core.db import AsyncSessionLocal, get_order_by_id, get_strategy_symbol_by_id, get_strategy_by_id
        # if self._db_session is None:
        #     self._db_session = AsyncSessionLocal()
        #     self._db_session_obj = await self._db_session.__aenter__()
        # session = self._db_session_obj
        # order = await get_order_by_id(session, order_id)
        # if not order:
        #     logger.error(f"OrderMonitor: No order found for order_id={order_id}")
        #     self._order_strategy_cache[order_id] = (None, None, None)
        #     self.stop()
        #     return None, None, None
        # strategy_symbol_id = order.get('strategy_symbol_id')
        # if not strategy_symbol_id:
        #     logger.error(f"OrderMonitor: No strategy_symbol_id for order_id={order_id}")
        #     self._order_strategy_cache[order_id] = (order, None, None)
        #     return order, None, None
        # strategy_symbol = await get_strategy_symbol_by_id(session, strategy_symbol_id)
        # if not strategy_symbol:
        #     logger.error(f"OrderMonitor: No strategy_symbol found for id={strategy_symbol_id}")
        #     self._order_strategy_cache[order_id] = (order, None, None)
        #     return order, None, None
        # strategy_id = strategy_symbol.get('strategy_id')
        # if not strategy_id:
        #     logger.error(f"OrderMonitor: No strategy_id in strategy_symbol for id={strategy_symbol_id}")
        #     self._order_strategy_cache[order_id] = (order, strategy_symbol, None)
        #     return order, strategy_symbol, None
        # strategy = await get_strategy_by_id(session, strategy_id)
        # self._order_strategy_cache[order_id] = (order, strategy_symbol, strategy)
        # return order, strategy_symbol, strategy
        async with AsyncSessionLocal() as session:
            order = await get_order_by_id(session, order_id)
            if not order:
                logger.error(f"OrderMonitor: No order found for order_id={order_id}")
                self._order_strategy_cache[order_id] = (None, None, None)
                self.stop()
                return None, None, None
            strategy_symbol_id = order.get('strategy_symbol_id')
            if not strategy_symbol_id:
                logger.error(f"OrderMonitor: No strategy_symbol_id for order_id={order_id}")
                self._order_strategy_cache[order_id] = (order, None, None)
                return order, None, None
            strategy_symbol = await get_strategy_symbol_by_id(session, strategy_symbol_id)
            if not strategy_symbol:
                logger.error(f"OrderMonitor: No strategy_symbol found for id={strategy_symbol_id}")
                self._order_strategy_cache[order_id] = (order, None, None)
                return order, None, None
            strategy_id = strategy_symbol.get('strategy_id')
            if not strategy_id:
                logger.error(f"OrderMonitor: No strategy_id in strategy_symbol for id={strategy_symbol_id}")
                self._order_strategy_cache[order_id] = (order, strategy_symbol, None)
                return order, strategy_symbol, None
            strategy = await get_strategy_by_id(session, strategy_id)
            self._order_strategy_cache[order_id] = (order, strategy_symbol, strategy)
            return order, strategy_symbol, strategy

    async def _price_order_monitor(self) -> None:
        """
        Main loop for price-based monitoring and exit.
        Uses unified order/strategy cache and helper methods for DRYness and efficiency.
        """
        await self.data_manager.ensure_broker()
        last_main_status = self._last_main_status
        last_broker_statuses = self._last_broker_statuses
        while self._running:
            try:
                agg: OrderAggregate = await self.data_manager.get_order_aggregate(self.order_id)
            except Exception as e:
                logger.error(f"OrderMonitor: Error in get_order_aggregate for order_id={self.order_id}: {e}")
                await asyncio.sleep(self.price_order_monitor_seconds)
                continue
            # Fetch order, strategy_symbol, and strategy in one go (cached)
            order_row, strategy_symbol, strategy = await self._get_order_and_strategy(self.order_id)
            if order_row is None:
                break
            # Initialize last_broker_statuses from agg.broker_orders if empty (first run or after restart)
            if not last_broker_statuses:
                for bro in agg.broker_orders:
                    broker_exec_id = getattr(bro, 'id', None)
                    status = getattr(bro, 'status', None)
                    if broker_exec_id is not None and status is not None:
                        last_broker_statuses[broker_exec_id] = str(status)
            if last_main_status is None and order_row and order_row.get('status') is not None:
                last_main_status = str(order_row.get('status'))
                self._last_main_status = last_main_status
            # --- Use live broker order data from order_cache for ENTRY side ---
            product_type = None
            if strategy:
                product_type = strategy.get('product_type') or strategy.get('producttype')
            entry_broker_db_orders = [bro for bro in agg.broker_orders if getattr(bro, 'side', None) == 'ENTRY']
            all_statuses = []
            status_set = set()
            for bro in entry_broker_db_orders:
                broker_exec_id = getattr(bro, 'id', None)
                broker_order_id = getattr(bro, 'order_id', None)
                broker_id = getattr(bro, 'broker_id', None)
                broker_name = None
                if broker_id is not None:
                    try:
                        broker_name = await self.data_manager.get_broker_name_by_id(broker_id)
                    except Exception as e:
                        logger.error(f"OrderMonitor: Could not get broker name for broker_id={broker_id}: {e}")
                cache_lookup_order_id = self._get_cache_lookup_order_id(
                    broker_order_id, broker_name, product_type
                )
                # Fetch live broker order from order_cache
                cache_order = None
                if broker_name and cache_lookup_order_id:
                    cache_order = await self.order_cache.get_order_by_id(broker_name, cache_lookup_order_id)
                # Use status from cache_order if available, else fallback to DB
                broker_status = None
                if cache_order and 'status' in cache_order:
                    broker_status = cache_order['status']
                else:
                    broker_status = getattr(bro, 'status', None)
                if broker_status and isinstance(broker_status, int) and broker_name == "fyers":
                    broker_status = FYERS_STATUS_MAP.get(broker_status, broker_status)
                # Normalize broker_status
                if broker_status and isinstance(broker_status, str) and broker_status.startswith("OrderStatus."):
                    broker_status = broker_status.split(".")[-1]
                elif broker_status and isinstance(broker_status, OrderStatus):
                    broker_status = broker_status.value
            
                
                all_statuses.append(broker_status)
                status_set.add(broker_status)
                last_status = last_broker_statuses.get(broker_exec_id)
                # --- Enhancement: Also check executed_quantity for PARTIALLY_FILLED updates ---
                # Get executed_quantity from broker (cache or bro)
                broker_executed_quantity = None
                if cache_order:
                    broker_executed_quantity = cache_order.get("executed_quantity") or cache_order.get("filled_quantity") or cache_order.get("filledQty")
                if broker_executed_quantity is None:
                    broker_executed_quantity = getattr(bro, "executed_quantity", None) or getattr(bro, "filled_quantity", None) or getattr(bro, "filledQty", None)
                # Get DB executed_quantity (from bro)
                db_executed_quantity = getattr(bro, "executed_quantity", None) or getattr(bro, "filled_quantity", None) or getattr(bro, "filledQty", None)
                # Only update if status changed, or for PARTIALLY_FILLED if executed_quantity increased
                should_update = False
                if broker_status != last_status:
                    should_update = True
                elif broker_status in ("PARTIALLY_FILLED", "PARTIAL"):
                    try:
                        if broker_executed_quantity is not None and db_executed_quantity is not None:
                            if float(broker_executed_quantity) > float(db_executed_quantity):
                                should_update = True
                    except Exception as e:
                        logger.error(f"OrderMonitor: Error comparing executed_quantity for broker_exec_id={broker_exec_id}: {e}")
                if should_update:
                    # If status transitions from PENDING/PARTIAL to FILLED/PARTIAL, update all fields
                    transition_to_filled = (
                        (last_status in ("PENDING", "PARTIAL", "PARTIALLY_FILLED")) and
                        (broker_status in ("FILLED", "PARTIAL", "PARTIALLY_FILLED"))
                    )
                    if transition_to_filled:
                        executed_quantity = broker_executed_quantity
                        execution_price = None
                        order_type = None
                        product_type_val = None
                        # Prefer cache_order for execution details, fallback to bro
                        if cache_order:
                            execution_price = cache_order.get("exec_price") or cache_order.get("execution_price") or cache_order.get("average_price") or cache_order.get("tradedPrice")
                            order_type = cache_order.get("order_type")
                            product_type_val = cache_order.get("product_type")
                        if execution_price is None:
                            execution_price = getattr(bro, "exec_price", None) or getattr(bro, "execution_price", None) or getattr(bro, "average_price", None) or getattr(bro, "tradedPrice", None)
                        if order_type is None:
                            order_type = getattr(bro, "order_type", None)
                        if product_type_val is None:
                            product_type_val = getattr(bro, "product_type", None)
                        await self.order_manager.update_broker_exec_status_in_db(
                            broker_exec_id,
                            broker_status,
                            executed_quantity=executed_quantity,
                            execution_price=execution_price,
                            order_type=order_type,
                            product_type=product_type_val
                        )
                    else:
                        await self.order_manager.update_broker_exec_status_in_db(broker_exec_id, broker_status)
                    last_broker_statuses[broker_exec_id] = broker_status
            logger.info(f"OrderMonitor: Order {self.order_id} ENTRY broker statuses (live): {all_statuses}")
            # --- Decision logic for main order status ---
            main_status = None
            if any(s in ("FILLED", "PARTIALLY_FILLED", "OPEN") for s in status_set):
                main_status = OrderStatus.OPEN
            elif all(s == "PENDING" for s in all_statuses) and all_statuses:
                main_status = OrderStatus.AWAITING_ENTRY
            elif all(s == "CANCELLED" for s in all_statuses) and all_statuses:
                main_status = OrderStatus.CANCELLED
            elif all(s == "REJECTED" for s in all_statuses) and all_statuses:
                main_status = OrderStatus.REJECTED
            # Only update Orders table if status changed
            if main_status is not None and main_status != last_main_status:
                if main_status == OrderStatus.OPEN and any(s in ("FILLED", "PARTIALLY_FILLED") for s in status_set):
                    from datetime import datetime, timezone
                    entry_time = datetime.now(timezone.utc)
                    await self.order_manager.update_order_status_in_db(self.order_id, main_status)
                    await self.order_manager.update_order_stop_loss_in_db(self.order_id, order_row.get('stop_loss'))
                    from algosat.core.db import AsyncSessionLocal, update_rows_in_table
                    from algosat.core.dbschema import orders
                    async with AsyncSessionLocal() as session:
                        await update_rows_in_table(
                            target_table=orders,
                            condition=orders.c.id == self.order_id,
                            new_values={"entry_time": entry_time}
                        )
                else:
                    await self.order_manager.update_order_status_in_db(self.order_id, main_status)
                last_main_status = main_status
                if main_status in (OrderStatus.CANCELLED, OrderStatus.REJECTED):
                    self.stop()
                    return
            symbol = agg.symbol
            ltp = None
            try:
                ltp_response = await self.data_manager.get_ltp(symbol)
                if isinstance(ltp_response, dict):
                    ltp = ltp_response.get(symbol)
                else:
                    ltp = ltp_response
            except Exception as e:
                logger.error(f"OrderMonitor: Error in get_ltp for symbol={symbol}, order_id={self.order_id}: {e}")
                ltp = None
            if ltp is not None and isinstance(ltp, (int, float)):
                try:
                    if order_row:
                        entry_price = order_row.get('entry_price')
                        qty = order_row.get('qty')
                        side = order_row.get('side')
                        if None not in (entry_price, qty, side):
                            if side == 'BUY':
                                pnl = (ltp - entry_price) * qty
                            elif side == 'SELL':
                                pnl = (entry_price - ltp) * qty
                            else:
                                pnl = 0.0
                            await self.order_manager.update_order_pnl_in_db(self.order_id, pnl)
                            logger.debug(f"OrderMonitor: Updated PnL for order_id={self.order_id}: {pnl}")
                except Exception as e:
                    logger.error(f"OrderMonitor: Error calculating/updating PnL for order_id={self.order_id}: {e}")
                try:
                    exit_reason = self._evaluate_price_exit_logic(order_row, ltp)
                except Exception as e:
                    logger.error(f"OrderMonitor: Error in price exit evaluation for order_id={self.order_id}: {e}")
                    exit_reason = None
                if exit_reason:
                    await self.order_manager.exit_order(self.order_id, exit_reason=exit_reason, ltp=ltp)
                    await self.order_manager.update_order_status_in_db(self.order_id, "CLOSED")
                    self.stop()
                    return
            await asyncio.sleep(self.price_order_monitor_seconds)
        logger.info(f"OrderMonitor: Stopping price monitor for order_id={self.order_id} (last status: {last_main_status})")
    def _evaluate_price_exit_logic(self, order, ltp):
        """
        Deduplicated price-based exit logic for all strategies.
        Returns exit_reason string if exit conditions are met, else None.
        """
        if not order:
            logger.error(f"OrderMonitor: No order found in _evaluate_price_exit_logic")
            return None
        stop_loss = order.get('stop_loss')
        target_price = order.get('target_price')
        entry_price = order.get('entry_price')
        side = order.get('side')
        qty = order.get('qty')
        if None in (stop_loss, target_price, entry_price, side, qty):
            logger.error(f"OrderMonitor: Missing fields for price exit evaluation (order_id={self.order_id})")
            return None
        exit_reason = None
        if side == 'BUY':
            if ltp <= stop_loss:
                exit_reason = 'STOP_LOSS'
            elif ltp >= target_price:
                exit_reason = 'TARGET'
        elif side == 'SELL':
            if ltp >= stop_loss:
                exit_reason = 'STOP_LOSS'
            elif ltp <= target_price:
                exit_reason = 'TARGET'
        return exit_reason

    def _get_cache_lookup_order_id(self, broker_order_id, broker_name, product_type):
        """
        Helper to determine cache key for broker order id (handles Fyers intraday hack).
        """
        if (
            product_type
            and product_type.lower() == 'intraday'
            and broker_name
            and broker_name.lower() == 'fyers'
            and broker_order_id
        ):
            return f"{broker_order_id}-BO-1"
        return broker_order_id

    async def _get_normalized_broker_status(self, bro, broker_name, cache_lookup_order_id):
        """
        Helper to get latest broker status from cache (if available), fallback to DB, and normalize.
        """
        latest_status = None
        if broker_name and cache_lookup_order_id:
            cache_order = await self.order_cache.get_order_by_id(broker_name, cache_lookup_order_id)
            if cache_order:
                latest_status = str(cache_order.get("status"))
        broker_status = latest_status if latest_status is not None else str(bro.status)
        # Normalize broker_status to plain value (e.g., 'TRIGGER_PENDING')
        if broker_status.startswith("OrderStatus."):
            broker_status = broker_status.split(".")[-1]
        return broker_status

    async def _signal_monitor(self) -> None:
        await self.data_manager.ensure_broker()
        while self._running:
            try:
                agg: OrderAggregate = await self.data_manager.get_order_aggregate(self.order_id)
            except Exception as e:
                logger.error(f"OrderMonitor: Error in get_order_aggregate (signal) for order_id={self.order_id}: {e}")
                await asyncio.sleep(self.signal_monitor_minutes * 60)
                continue
            # Fetch order, strategy_symbol, and strategy from unified cache
            order_row, strategy_symbol, strategy = await self._get_order_and_strategy(self.order_id)
            if strategy is None:
                # If strategy is missing, just skip this iteration
                await asyncio.sleep(self.signal_monitor_minutes * 60)
                continue
            try:
                interval = getattr(strategy, "entry_interval", 1)
                lookback = getattr(strategy, "exit_lookback", 1) + 1
                history = await self.data_manager.fetch_history(
                    agg.symbol,
                    interval_minutes=interval,
                    lookback=lookback
                )
            except Exception as e:
                logger.error(f"OrderMonitor: Error in fetch_history (slow) for symbol={agg.symbol}, order_id={self.order_id}: {e}")
                history = None
            try:
                ltp = await self.data_manager.get_ltp(agg.symbol)
            except Exception as e:
                logger.error(f"OrderMonitor: Error in get_ltp (slow) for symbol={agg.symbol}, order_id={self.order_id}: {e}")
                ltp = None
            strategy.update_trailing_stop_loss(self.order_id, ltp, history, self.order_manager)
            try:
                exit_req = await strategy.evaluate_candle_exit(self.order_id, history)
            except Exception as e:
                logger.error(f"OrderMonitor: Error in evaluate_candle_exit for order_id={self.order_id}: {e}")
                exit_req = None
            if exit_req:
                await self.order_manager.place_order(exit_req, strategy_name=strategy.name)
                self.stop()
                return
            await asyncio.sleep(self.signal_monitor_minutes * 60)

    async def start(self) -> None:
        # Fetch signal_monitor_minutes from strategy config if not set
        if self.signal_monitor_minutes is None:
            # Use unified cache-based access for strategy
            _, _, strategy_config = await self._get_order_and_strategy(self.order_id)
            if strategy_config:
                # Try to get interval_minutes from trade_param
                import json
                trade_param = strategy_config.get('trade_param')
                interval_minutes = None
                if trade_param:
                    try:
                        trade_param_dict = json.loads(trade_param) if isinstance(trade_param, str) else trade_param
                        interval_minutes = trade_param_dict.get('interval_minutes')
                    except Exception as e:
                        logger.error(f"OrderMonitor: Could not parse trade_param for order_id={self.order_id}: {e}")
                if interval_minutes:
                    self.signal_monitor_minutes = interval_minutes
                else:
                    self.signal_monitor_minutes = 5  # fallback default
        logger.debug(f"Starting monitors for order_id={self.order_id} (price: {self.price_order_monitor_seconds}s, signal: {self.signal_monitor_minutes}m)")
        await asyncio.gather(self._price_order_monitor())#, self._signal_monitor())

    def stop(self) -> None:
        self._running = False
        # Close DB session if open
        # if self._db_session is not None:
        #     async def _close_session():
        #         try:
        #             if hasattr(self._db_session, '__aexit__'):
        #                 await self._db_session.__aexit__(None, None, None)
        #         except Exception as e:
        #             logger.error(f"OrderMonitor: Error closing DB session: {e}")
        #     try:
        #         import asyncio
        #         if asyncio.get_event_loop().is_running():
        #             asyncio.create_task(_close_session())
        #         else:
        #             loop = asyncio.get_event_loop()
        #             loop.run_until_complete(_close_session())
        #     except Exception:
        #         pass
        #     self._db_session = None
        #     self._db_session_obj = None

    @property
    async def strategy(self):
        """
        Returns the strategy dict for this order_id (uses unified order/strategy cache).
        """
        _, _, strategy = await self._get_order_and_strategy(self.order_id)
        return strategy
