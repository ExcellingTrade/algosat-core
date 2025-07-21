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
from algosat.common.strategy_utils import wait_for_next_candle, fetch_instrument_history

logger = get_logger("OrderMonitor")

class OrderMonitor:
    def __init__(
        self,
        order_id: int,
        data_manager: DataManager,
        order_manager: OrderManager,
        order_cache: OrderCache,  # new dependency
        price_order_monitor_seconds: float = 60.0,  # 1 minute default
        signal_monitor_seconds: int = None  # will be set from strategy config
    ):
        self.order_id: int = order_id
        self.data_manager: DataManager = data_manager
        self.order_manager: OrderManager = order_manager
        self.order_cache: OrderCache = order_cache
        self.price_order_monitor_seconds: float = price_order_monitor_seconds
        self.signal_monitor_seconds: int = signal_monitor_seconds
                # --- Add position cache fields ---
        self._positions_cache = None
        self._positions_cache_time = None
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
        Fetch order, strategy_symbol, strategy_config, and strategy for this order_id, cache the result.
        Returns (order, strategy_symbol, strategy_config, strategy) tuple. Always checks cache first.
        If order is missing, logs error and stops the monitor.
        """
        # Check cache first
        if order_id in self._order_strategy_cache:
            return self._order_strategy_cache[order_id]
        # Lazy-load session if not present
        from algosat.core.db import AsyncSessionLocal, get_order_by_id, get_strategy_symbol_by_id, get_strategy_by_id, get_strategy_config_by_id
        # Fetch order, strategy_symbol, strategy_config, and strategy in one go
        async with AsyncSessionLocal() as session:
            order = await get_order_by_id(session, order_id)
            if not order:
                logger.error(f"OrderMonitor: No order found for order_id={order_id}")
                self._order_strategy_cache[order_id] = (None, None, None, None)
                self.stop()
                return None, None, None, None
            strategy_symbol_id = order.get('strategy_symbol_id')
            if not strategy_symbol_id:
                logger.error(f"OrderMonitor: No strategy_symbol_id for order_id={order_id}")
                self._order_strategy_cache[order_id] = (order, None, None, None)
                return order, None, None, None
            strategy_symbol = await get_strategy_symbol_by_id(session, strategy_symbol_id)
            if not strategy_symbol:
                logger.error(f"OrderMonitor: No strategy_symbol found for id={strategy_symbol_id}")
                self._order_strategy_cache[order_id] = (order, None, None, None)
                return order, None, None, None
            config_id = strategy_symbol.get('config_id')
            strategy_config = None
            if config_id:
                strategy_config = await get_strategy_config_by_id(session, config_id)
                if not strategy_config:
                    logger.error(f"OrderMonitor: No strategy_config found for id={config_id}")
            strategy_id = strategy_symbol.get('strategy_id')
            if not strategy_id:
                logger.error(f"OrderMonitor: No strategy_id in strategy_symbol for id={strategy_symbol_id}")
                self._order_strategy_cache[order_id] = (order, strategy_symbol, strategy_config, None)
                return order, strategy_symbol, strategy_config, None
            strategy = await get_strategy_by_id(session, strategy_id)
            self._order_strategy_cache[order_id] = (order, strategy_symbol, strategy_config, strategy)
            return order, strategy_symbol, strategy_config, strategy

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
                # If order is deleted, stop monitoring this order_id
                if "not found" in str(e).lower() or "deleted" in str(e).lower():
                    logger.info(f"OrderMonitor: Stopping monitor for order_id={self.order_id} as order is deleted.")
                    self.stop()
                    return
                await asyncio.sleep(self.price_order_monitor_seconds)
                continue
            # Fetch order, strategy_symbol, strategy_config, and strategy in one go (cached)
            order_row, strategy_symbol, strategy_config, strategy = await self._get_order_and_strategy(self.order_id)
            if order_row is None:
                logger.info(f"OrderMonitor: Stopping monitor for order_id={self.order_id} as order_row is None (order deleted).")
                self.stop()
                return
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
            try:
                for bro in entry_broker_db_orders:
                    try:
                        broker_exec_id = getattr(bro, 'id', None)
                        broker_order_id = getattr(bro, 'order_id', None)
                        broker_id = getattr(bro, 'broker_id', None)
                        broker_name = None
                        if broker_id is not None:
                            try:
                                broker_name = await self.data_manager.get_broker_name_by_id(broker_id)
                            except Exception as e:
                                logger.error(f"OrderMonitor: Could not get broker name for broker_id={broker_id}: {e}")
                        # If broker_order_id is None or empty, order is not placed, set status to FAILED
                        cache_order = None
                        if not broker_order_id:
                            broker_status = "FAILED"
                        else:
                            cache_lookup_order_id = self._get_cache_lookup_order_id(
                                broker_order_id, broker_name, product_type
                            )
                            # Fetch live broker order from order_cache
                            if broker_name and cache_lookup_order_id:
                                try:
                                    cache_order = await self.order_cache.get_order_by_id(broker_name, cache_lookup_order_id)
                                except Exception as e:
                                    logger.error(f"OrderMonitor: Error fetching order from cache for broker_name={broker_name}, order_id={cache_lookup_order_id}: {e}")
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
                    except Exception as e:
                        logger.error(f"OrderMonitor: Unexpected error processing broker order (exec_id={getattr(bro, 'id', None)}): {e}", exc_info=True)
                        all_statuses.append("FAILED")
                        status_set.add("FAILED")
                    last_status = last_broker_statuses.get(broker_exec_id)
                    # --- Enhancement: Also check executed_quantity for PARTIALLY_FILLED updates ---
                    # Get executed_quantity from broker (cache or bro)
                    broker_executed_quantity = None
                    broker_placed_quantity = None
                    if cache_order:
                        broker_executed_quantity = cache_order.get("executed_quantity") or cache_order.get("filled_quantity") or cache_order.get("filledQty")
                        broker_placed_quantity = cache_order.get("quantity") or cache_order.get("qty") or cache_order.get("filledQty")
                    # if broker_executed_quantity is None:
                        # broker_executed_quantity = getattr(bro, "executed_quantity", None) or getattr(bro, "filled_quantity", None) or getattr(bro, "filledQty", None)
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
                            from datetime import datetime, timezone
                            executed_quantity = broker_executed_quantity
                            quantity = broker_placed_quantity
                            symbol_val = None
                            # Prefer cache_order for execution details, fallback to bro
                            if cache_order:
                                execution_price = cache_order.get("exec_price") or cache_order.get("execution_price") or cache_order.get("average_price") or cache_order.get("tradedPrice")
                                order_type = cache_order.get("order_type")
                                product_type_val = cache_order.get("product_type")
                                # Get quantity from cache_order (qty or quantity)
                                quantity = cache_order.get("qty") or cache_order.get("quantity")
                                # Get symbol from cache_order (symbol or tradingsymbol)
                                symbol_val = cache_order.get("symbol") or cache_order.get("tradingsymbol")
                            if execution_price is None:
                                execution_price = getattr(bro, "exec_price", None) or getattr(bro, "execution_price", None) or getattr(bro, "average_price", None) or getattr(bro, "tradedPrice", None)
                            if order_type is None:
                                order_type = getattr(bro, "order_type", None)
                            if product_type_val is None:
                                product_type_val = getattr(bro, "product_type", None)
                            # if quantity is None:
                            #     quantity = getattr(bro, "qty", None) or getattr(bro, "quantity", None)
                            if symbol_val is None:
                                symbol_val = getattr(bro, "symbol", None) or getattr(bro, "tradingsymbol", None)
                            execution_time = datetime.now(timezone.utc)
                            await self.order_manager.update_broker_exec_status_in_db(
                                broker_exec_id,
                                broker_status,
                                executed_quantity=executed_quantity,
                                quantity = quantity,
                                execution_price=execution_price,
                                order_type=order_type,
                                product_type=product_type_val,
                                execution_time=execution_time,
                                symbol=symbol_val
                            )
                        else:
                            await self.order_manager.update_broker_exec_status_in_db(broker_exec_id, broker_status)
                        last_broker_statuses[broker_exec_id] = broker_status
            except Exception as e:
                logger.error(f"OrderMonitor: Unexpected error in broker order status loop: {e}", exc_info=True)
               

            # --- Aggregate and update Orders table with sum of broker_execs quantities ---
            try:
                from algosat.core.db import AsyncSessionLocal, update_rows_in_table, get_order_by_id
                from algosat.core.dbschema import orders, broker_executions
                async with AsyncSessionLocal() as session:
                    # Fetch all broker_executions for this order with side='ENTRY' (fresh from DB for latest values)
                    from algosat.core.db import get_broker_executions_for_order
                    broker_exec_rows = await get_broker_executions_for_order(session, self.order_id, side='ENTRY')
                    total_quantity = 0
                    total_executed_quantity = 0
                    vwap_total_value = 0.0
                    vwap_total_qty = 0.0
                    for be in broker_exec_rows:
                        q = be.get('quantity') or 0
                        eq = be.get('executed_quantity') or 0
                        exec_price = be.get('execution_price') or 0
                        try:
                            q = float(q) if q is not None else 0
                        except Exception:
                            q = 0
                        try:
                            eq = float(eq) if eq is not None else 0
                        except Exception:
                            eq = 0
                        try:
                            exec_price = float(exec_price) if exec_price is not None else 0
                        except Exception:
                            exec_price = 0
                        total_quantity += q
                        total_executed_quantity += eq
                        vwap_total_value += eq * exec_price
                        vwap_total_qty += eq
                    entry_price = round(vwap_total_value / vwap_total_qty, 2) if vwap_total_qty > 0 else None
                    # Fetch current order values from DB
                    current_order = await get_order_by_id(session, self.order_id)
                    current_qty = current_order.get('qty') if current_order else None
                    current_executed_quantity = current_order.get('executed_quantity') if current_order else None
                    current_entry_price = current_order.get('entry_price') if current_order else None
                    # Only update if any value changed
                    if (
                        float(total_quantity) != float(current_qty or 0) or
                        float(total_executed_quantity) != float(current_executed_quantity or 0) or
                        (entry_price is not None and float(entry_price) != float(current_entry_price or 0))
                    ):
                        update_fields = {"qty": total_quantity, "executed_quantity": total_executed_quantity}
                        if entry_price is not None:
                            update_fields["entry_price"] = entry_price
                        await update_rows_in_table(
                            target_table=orders,
                            condition=orders.c.id == self.order_id,
                            new_values=update_fields
                        )
                        logger.info(f"OrderMonitor: Updated Orders table for order_id={self.order_id} with qty={total_quantity}, executed_quantity={total_executed_quantity}, entry_price={entry_price}")
                    else:
                        logger.debug(f"OrderMonitor: No change in qty, executed_quantity, entry_price for order_id={self.order_id}. Skipping DB update.")
            except Exception as e:
                logger.error(f"OrderMonitor: Error updating aggregated quantity/executed_quantity for order_id={self.order_id}: {e}")
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
            elif all(s == "FAILED" for s in all_statuses) and all_statuses:
                main_status = OrderStatus.FAILED
            elif all(s in ("REJECTED", "FAILED") for s in all_statuses) and all_statuses:
                main_status = OrderStatus.CANCELLED
            # Only update Orders table if status changed
            if main_status is not None and main_status != last_main_status:
                if main_status == OrderStatus.OPEN and any(s in ("FILLED", "PARTIALLY_FILLED") for s in status_set):
                    from datetime import datetime, timezone
                    entry_time = datetime.now(timezone.utc)
                    logger.info(f"OrderMonitor: Updating order_id={self.order_id} to {main_status} with entry_time={entry_time}")
                    await self.order_manager.update_order_status_in_db(self.order_id, main_status)
                    await self.order_manager.update_order_stop_loss_in_db(self.order_id, order_row.get('stop_loss'))
                    from algosat.core.db import AsyncSessionLocal, update_rows_in_table
                    from algosat.core.dbschema import orders

                    await update_rows_in_table(
                        target_table=orders,
                        condition=orders.c.id == self.order_id,
                        new_values={"entry_time": entry_time}
                    )
                else:
                    logger.info(f"OrderMonitor: Updating order_id={self.order_id} to {main_status}")
                    await self.order_manager.update_order_status_in_db(self.order_id, main_status)
                last_main_status = main_status
                if main_status in (OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.FAILED):
                    self.stop()
                    return
                
            # --- monitor positions if status is OPEN ---
            # Only for OPEN status, check broker positions and update order status/PnL based on positions
            if last_main_status == str(OrderStatus.OPEN) or (main_status == OrderStatus.OPEN):
                try:
                    # Use new helper to get all broker positions (with cache)
                    all_positions = await self._get_all_broker_positions_with_cache()
                    # Map broker_id to positions
                    broker_positions_map = {}
                    if all_positions and isinstance(all_positions, dict):
                        broker_positions_map = all_positions
                    # For each broker_exec in ENTRY, match to broker positions by broker, symbol, quantity, product
                    async with AsyncSessionLocal() as session:
                    # entry_broker_db_orders = [bro for bro in agg.broker_orders if getattr(bro, 'side', None) == 'ENTRY']
                        entry_broker_db_orders = await get_broker_executions_for_order(session, self.order_id, side='ENTRY')
                    total_pnl = 0.0
                    all_closed = True
                    for bro in entry_broker_db_orders:
                        broker_id = getattr(bro, 'broker_id', None)
                        broker_name = None
                        if broker_id is not None:
                            try:
                                broker_name = await self.data_manager.get_broker_name_by_id(broker_id)
                            except Exception as e:
                                logger.error(f"OrderMonitor: Could not get broker name for broker_id={broker_id}: {e}")
                        # broker_name = await self.data_manager.get_broker_name_by_id(bro.get("broker_id"))
                        symbol_val = bro.get('symbol', None) or bro.get('tradingsymbol', None)
                        qty = bro.get('quantity', None)
                        product = bro.get('product_type', None) or bro.get('product', None)
                        exec_price = bro.get('execution_price', None)
                        # Find matching position for this broker
                        positions = broker_positions_map.get(broker_name.lower() if broker_name else "", None)
                        matched_pos = None
                        if positions:
                            # Zerodha: positions is a dict with 'net' key
                            if broker_name and broker_name.lower() == "zerodha":
                                for pos in positions:
                                    try:
                                        # Match by tradingsymbol, product, and buy_quantity or overnight_quantity
                                        product_match = (str(pos.get('product')).upper() == str(product).upper()) if product else True
                                        entry_price_match = (float(pos.get('buy_price', 0)) == float(exec_price)) if exec_price else True
                                        qty_match = (int(pos.get('buy_quantity', 0)) == int(qty)) or (int(pos.get('overnight_quantity', 0)) == int(qty))
                                        if (
                                            pos.get('tradingsymbol') == symbol_val and
                                            qty_match and
                                            product_match and
                                            entry_price_match
                                        ):
                                            matched_pos = pos
                                            break
                                    except Exception as e:
                                        logger.error(f"OrderMonitor: Error matching Zerodha position: {e}")
                            # Fyers: positions is a list of dicts
                            elif broker_name and broker_name.lower() == "fyers":
                                for pos in positions:
                                    try:
                                        # Fyers fields: 'symbol', 'qty', 'productType', 'buyAvg', 'side'
                                        product_match = (str(pos.get('productType')).upper() == str(product).upper()) if product else True
                                        qty_match = (int(pos.get('buyQty', 0)) == int(qty))
                                        symbol_match = (pos.get('symbol') == symbol_val)
                                        if symbol_match and qty_match and product_match:
                                            matched_pos = pos
                                            break
                                    except Exception as e:
                                        logger.error(f"OrderMonitor: Error matching Fyers position: {e}")
                        # If match found, update order/broker_exec status and accumulate PnL
                        if matched_pos:
                            # Zerodha: use 'pnl' field; Fyers: use 'pl' field
                            pnl_val = 0.0
                            closed = False
                            if broker_name and broker_name.lower() == "zerodha":
                                pnl_val = float(matched_pos.get('pnl', 0))
                                # If quantity is 0, consider squared off
                                if int(matched_pos.get('quantity', 0)) == 0:
                                    closed = True
                            elif broker_name and broker_name.lower() == "fyers":
                                pnl_val = float(matched_pos.get('pl', 0))
                                if int(matched_pos.get('qty', 0)) == 0:
                                    closed = True
                            total_pnl += pnl_val
                            if closed:
                                # --- Enhancement: Insert EXIT broker_execution before marking CLOSED ---
                                try:
                                    from datetime import datetime, timezone
                                    execution_time = datetime.now(timezone.utc)
                                    orig_side = (bro.get('action') or '').upper()
                                    if orig_side == 'BUY':
                                        exit_action = 'SELL'
                                    elif orig_side == 'SELL':
                                        exit_action = 'BUY'
                                    else:
                                        exit_action = ''
                                    execution_price = None
                                    executed_quantity = None
                                    symbol_val_exit = bro.get('symbol', None) or bro.get('tradingsymbol', None)
                                    product = bro.get('product_type', None) or bro.get('product', None)
                                    broker_id = bro.get("broker_id")
                                    broker_order_id = bro.get("broker_order_id")
                                    # Zerodha
                                    if broker_name and broker_name.lower() == "zerodha":
                                        if orig_side and orig_side.upper() == "BUY":
                                            execution_price = matched_pos.get('sell_price')
                                            executed_quantity = matched_pos.get('buy_quantity', None)
                                        elif orig_side and orig_side.upper() == "SELL":
                                            execution_price = matched_pos.get('buy_price')
                                            executed_quantity = matched_pos.get('sell_quantity', None)
                                        else:
                                            execution_price = matched_pos.get('sell_price') or matched_pos.get('buy_price')
                                            executed_quantity = matched_pos.get('quantity', None)
                                    # Fyers
                                    elif broker_name and broker_name.lower() == "fyers":
                                        # Fyers fields: 'side' (BUY/SELL), 'sellAvg', 'buyAvg', 'qty'
                                        if orig_side and orig_side.upper() == "BUY":
                                            execution_price = matched_pos.get('sellAvg', None)
                                            executed_quantity = matched_pos.get('buyQty', None)
                                        elif orig_side and orig_side.upper() == "SELL":
                                            execution_price = matched_pos.get('buyAvg', None)
                                            executed_quantity = matched_pos.get('sellQty', None)
                                        else:
                                            execution_price = matched_pos.get('sellAvg', None) or matched_pos.get('buyAvg', None)
                                            executed_quantity = matched_pos.get('qty', None)
                                    # fallback
                                    if execution_price is None:
                                        execution_price = matched_pos.get('sell_price') or matched_pos.get('buy_price')
                                    if executed_quantity is None:
                                        executed_quantity = matched_pos.get('quantity', None)
                                    # Use close time as now


                                    # Check if EXIT broker_execution already exists for this parent_order_id, broker_id, broker_order_id
                                    from algosat.core.db import AsyncSessionLocal, get_broker_executions_for_order
                                    async with AsyncSessionLocal() as session:
                                        existing_execs = await get_broker_executions_for_order(
                                            session,
                                            self.order_id,
                                            side='EXIT'
                                        )
                                    found = None
                                    for ex in existing_execs:
                                        if ex.get('broker_id') == broker_id and ex.get('broker_order_id') == broker_order_id:
                                            found = ex
                                            break
                                    if found:
                                        # Update only execution_price
                                        await self.order_manager.update_broker_execution_price(found.get('id'), execution_price)
                                        logger.info(f"OrderMonitor: Updated execution_price for EXIT broker_execution id={found.get('id')}")
                                    else:
                                        await self.order_manager.insert_broker_execution(
                                            parent_order_id=self.order_id,
                                            broker_id=broker_id,
                                            broker_order_id=broker_order_id,
                                            action=exit_action,
                                            side='EXIT',
                                            status='FILLED',
                                            executed_quantity=be.get('executed_quantity', 0),
                                            execution_price=execution_price,
                                            product_type=product_type,
                                            order_type='MARKET',
                                            order_messages=f"Order exited:",
                                            symbol=symbol_val_exit,
                                            execution_time=execution_time,
                                            notes=f"Order Exited"
                                        )
                                        logger.info(f"OrderMonitor: Inserted new EXIT broker_execution for parent_order_id={self.order_id}, broker_id={broker_id}, broker_order_id={broker_order_id}")
                                except Exception as e:
                                    logger.error(f"OrderMonitor: Error inserting/updating EXIT broker_execution: {e}")
                            else:
                                all_closed = False
                        else:
                            all_closed = False
                    # Update order PnL field in DB
                    try:
                        await self.order_manager.update_order_pnl_in_db(self.order_id, total_pnl)
                        logger.debug(f"OrderMonitor: Updated PnL for order_id={self.order_id}: {total_pnl}")
                    except Exception as e:
                        logger.error(f"OrderMonitor: Error updating order PnL for order_id={self.order_id}: {e}")
                    # If all positions are squared off, update status to CLOSED/EXITED
                    if all_closed and entry_broker_db_orders:
                        try:
                            from datetime import datetime, timezone
                            from algosat.core.db import AsyncSessionLocal, update_rows_in_table, get_broker_executions_for_order
                            from algosat.core.dbschema import orders
                            # Calculate VWAP exit price for each broker
                            async with AsyncSessionLocal() as session:
                                exit_execs = await get_broker_executions_for_order(session, self.order_id, side='EXIT')
                            broker_vwap = {}
                            broker_qty = {}
                            for ex in exit_execs:
                                broker_id = ex.get('broker_id')
                                exec_price = float(ex.get('execution_price') or 0)
                                exec_qty = int(ex.get('executed_quantity') or 0)
                                if broker_id not in broker_vwap:
                                    broker_vwap[broker_id] = 0.0
                                    broker_qty[broker_id] = 0
                                broker_vwap[broker_id] += exec_price * exec_qty
                                broker_qty[broker_id] += exec_qty
                            # Compute VWAP per broker
                            broker_exit_prices = {}
                            for broker_id in broker_vwap:
                                qty = broker_qty[broker_id]
                                vwap = broker_vwap[broker_id] / qty if qty > 0 else 0.0
                                broker_exit_prices[broker_id] = vwap
                            # For orders table, set exit_price as the average VWAP across all brokers
                            total_vwap = sum(broker_vwap.values())
                            total_qty = sum(broker_qty.values())
                            avg_exit_price = total_vwap / total_qty if total_qty > 0 else None
                            update_fields = {
                                "status": "CLOSED",
                                "exit_time": datetime.now(timezone.utc)
                            }
                            if avg_exit_price is not None:
                                update_fields["exit_price"] = round(avg_exit_price, 2)
                            await update_rows_in_table(
                                target_table=orders,
                                condition=orders.c.id == self.order_id,
                                new_values=update_fields
                            )
                            logger.info(
                                f"OrderMonitor: All broker positions squared off for order_id={self.order_id}. "
                                f"Updated orders table with {update_fields} (VWAP exit_price: {avg_exit_price})"
                            )
                            self.stop()
                            return
                        except Exception as e:
                            logger.error(f"OrderMonitor: Error updating order status to CLOSED: {e}")
                except Exception as e:
                    logger.error(f"OrderMonitor: Error in broker position monitoring: {e}", exc_info=True)
            await asyncio.sleep(self.price_order_monitor_seconds)
        logger.info(f"OrderMonitor: Stopping price monitor for order_id={self.order_id} (last status: {last_main_status})")
    


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
                # Fetch order, strategy_symbol, strategy_config, and strategy (cached)
                order_row, strategy_symbol, strategy_config, strategy = await self._get_order_and_strategy(self.order_id)
            except Exception as e:
                logger.error(f"OrderMonitor: Error in _get_order_and_strategy for order_id={self.order_id}: {e}", exc_info=True)
                await asyncio.sleep(self.signal_monitor_seconds)
                continue

            if strategy is None or order_row is None:
                logger.warning(f"OrderMonitor: Missing strategy or order_row for order_id={self.order_id}. Skipping iteration.")
                await asyncio.sleep(self.signal_monitor_seconds)
                continue

            # Determine strategy_id
            strategy_id = None
            if isinstance(strategy, dict):
                strategy_id = strategy.get('id')
            else:
                strategy_id = getattr(strategy, 'id', None)

            logger.info(f"OrderMonitor: Calling evaluate_exit for order_id={self.order_id}, strategy_id={strategy_id}")
            try:
                evaluate_exit_fn = getattr(strategy, "evaluate_exit", None)
                if evaluate_exit_fn is None:
                    logger.warning(f"OrderMonitor: Strategy missing evaluate_exit method for order_id={self.order_id}")
                    await asyncio.sleep(self.signal_monitor_seconds)
                    continue
                result = evaluate_exit_fn(order_row)
                if asyncio.iscoroutine(result):
                    should_exit = await result
                else:
                    should_exit = result
            except Exception as e:
                logger.error(f"OrderMonitor: Exception in evaluate_exit for order_id={self.order_id}: {e}", exc_info=True)
                await asyncio.sleep(self.signal_monitor_seconds)
                continue

            if should_exit:
                logger.info(f"OrderMonitor: evaluate_exit returned True for order_id={self.order_id}. Exiting order.")
                try:
                    await self.order_manager.exit_order(self.order_id)
                except Exception as e:
                    logger.error(f"OrderMonitor: Failed to exit order {self.order_id}: {e}", exc_info=True)
                self.stop()
                return

            await asyncio.sleep(self.signal_monitor_seconds)

    async def start(self) -> None:
        # Fetch signal_monitor_seconds from strategy config if not set
        if self.signal_monitor_seconds is None:
            # Use unified cache-based access for strategy_config and strategy
            _, _, strategy_config, strategy = await self._get_order_and_strategy(self.order_id)
            strategy_id = None
            if strategy:
                # Try to get id from strategy object (dict or object)
                strategy_id = getattr(strategy, 'id', None)
                if strategy_id is None and isinstance(strategy, dict):
                    strategy_id = strategy.get('id')
            import json
            trade_param = strategy_config.get('trade') if strategy_config else None
            if strategy_id in (1, 2):
                # For strategy_id 1, 2: use interval_minutes from trade param
                interval_minutes = None
                if trade_param:
                    try:
                        trade_param_dict = json.loads(trade_param) if isinstance(trade_param, str) else trade_param
                        interval_minutes = trade_param_dict.get('interval_minutes')
                    except Exception as e:
                        logger.error(f"OrderMonitor: Could not parse trade_param for order_id={self.order_id}: {e}")
                if interval_minutes:
                    self.signal_monitor_seconds = int(interval_minutes) * 60
                else:
                    self.signal_monitor_seconds = 5 * 60  # fallback default
            elif strategy_id in (3, 4):
                # For strategy_id 3, 4: use stoploss.timeframe from trade param
                stoploss_timeframe = None
                if trade_param:
                    try:
                        trade_param_dict = json.loads(trade_param) if isinstance(trade_param, str) else trade_param
                        stoploss_section = trade_param_dict.get('stoploss', {})
                        stoploss_timeframe = stoploss_section.get('timeframe')
                    except Exception as e:
                        logger.error(f"OrderMonitor: Could not parse stoploss section for order_id={self.order_id}: {e}")
                if stoploss_timeframe:
                    # Remove 'm' prefix if present and convert to int
                    if isinstance(stoploss_timeframe, str) and stoploss_timeframe.endswith('m'):
                        stoploss_timeframe = stoploss_timeframe[:-1]
                    try:
                        self.signal_monitor_seconds = int(stoploss_timeframe) * 60
                    except Exception as e:
                        logger.error(f"OrderMonitor: Could not convert stoploss_timeframe to int for order_id={self.order_id}: {e}")
                        self.signal_monitor_seconds = 5 * 60
                else:
                    self.signal_monitor_seconds = 5 * 60
            else:
                # fallback default
                self.signal_monitor_seconds = 5 * 60
        logger.info(f"Starting monitors for order_id={self.order_id} (price: {self.price_order_monitor_seconds}s, signal: {self.signal_monitor_seconds}s)")
        await asyncio.gather(self._price_order_monitor())  #, self._signal_monitor())

    def stop(self) -> None:
        self._running = False

    @property
    async def strategy(self):
        """
        Returns the strategy dict for this order_id (uses unified order/strategy cache).
        """
        _, _, _, strategy = await self._get_order_and_strategy(self.order_id)
        return strategy

    async def _get_all_broker_positions_with_cache(self):
        """
        Helper to get all broker positions, with 10s cache to avoid repeated API calls.
        """
        import time
        now = time.time()
        if (
            hasattr(self, "_positions_cache")
            and hasattr(self, "_positions_cache_time")
            and self._positions_cache is not None
            and self._positions_cache_time is not None
            and (now - self._positions_cache_time) < 10
        ):
            return self._positions_cache
        try:
            positions = await self.order_manager.broker_manager.get_all_broker_positions()
            self._positions_cache = positions
            self._positions_cache_time = now
            return positions
        except Exception as e:
            logger.error(f"OrderMonitor: Error fetching broker positions: {e}")
            return self._positions_cache