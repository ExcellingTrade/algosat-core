# core/order_manager.py
"""
OrderManager: Responsible for managing the lifecycle of orders across all brokers that are trade enabled and live/authenticated.
"""
from typing import Optional, Dict, Any, List # Added typing imports
from algosat.core.db import get_trade_enabled_brokers, AsyncSessionLocal, insert_order, get_broker_by_name
from algosat.brokers.factory import get_broker
from algosat.common.logger import get_logger
from algosat.core.dbschema import trade_logs
from algosat.core.broker_manager import BrokerManager
from algosat.core.order_request import OrderRequest, OrderStatus, Side, OrderType
from algosat.core.dbschema import orders as orders_table
from algosat.models.strategy_config import StrategyConfig
from algosat.models.order_aggregate import OrderAggregate, BrokerOrder
import json
import numpy as np

logger = get_logger("OrderManager")

class OrderManager:
    def __init__(self, broker_manager: BrokerManager):
        self.broker_manager: BrokerManager = broker_manager

    @staticmethod
    def extract_strategy_config_id(config):
        """
        Extract strategy_config_id from a StrategyConfig dataclass, dict, or ORM row.
        """
        if isinstance(config, StrategyConfig):
            return config.id
        # Direct attribute or key
        for key in ("strategy_config_id", "id"):  # prefer explicit field if present
            if isinstance(config, dict) and key in config:
                return config[key]
            if hasattr(config, key):
                return getattr(config, key)
        # Nested under 'config' attribute or key
        for key in ("config",):
            nested = None
            if isinstance(config, dict) and key in config:
                nested = config[key]
            elif hasattr(config, key):
                nested = getattr(config, key)
            if nested:
                for subkey in ("strategy_config_id", "id"):
                    if isinstance(nested, dict) and subkey in nested:
                        return nested[subkey]
                    if hasattr(nested, subkey):
                        return getattr(nested, subkey)
        return None

    async def place_order(
        self,
        config,
        order_payload: OrderRequest,
        strategy_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Places an order through all configured and authenticated trade-enabled brokers.
        Updates the order status in the database based on broker responses.

        Args:
            config: The strategy configuration (StrategyConfig instance).
            order_payload: The OrderRequest object detailing the order.
            strategy_name: Optional name of the strategy placing the order.

        Returns:
            A dictionary containing the overall status and individual broker responses.
        """
        if not isinstance(config, StrategyConfig):
            logger.error("OrderManager.place_order: config must be a StrategyConfig instance.")
            # Potentially return or raise an error indicating misconfiguration
            # For now, we'll try to proceed if strategy_id can be found, but this is not ideal.
            strategy_id_for_db = None
        else:
            strategy_id_for_db = config.id

        if not isinstance(order_payload, OrderRequest):
            logger.error("OrderManager.place_order: order_payload must be an OrderRequest instance.")
            return { # Return a more informative error structure
                "overall_status": "error",
                "message": "Invalid order_payload type.",
                "broker_responses": {}
            }

        # Initial status before sending to any broker
        # This status will be updated based on broker responses
        initial_order_status_for_db = OrderStatus.AWAITING_ENTRY 

        # Insert initial order record with AWAITING_ENTRY status
        # This gives us an order_id even if all broker placements fail
        # The status will be updated to FAILED or another appropriate status later
        local_order_id = await self._insert_and_get_order_id(
            order_payload,
            strategy_id_for_db, # Use the id from StrategyConfig
            initial_order_status_for_db, # Initial status
            broker_message="Order initiated. Awaiting broker confirmation."
        )

        if local_order_id is None:
            logger.error("Failed to insert initial order record into DB. Aborting placement.")
            return {
                "overall_status": "error",
                "message": "Database error: Failed to create initial order record.",
                "broker_responses": {}
            }
        
        order_payload.local_order_id = local_order_id # Assign local_order_id to the payload for broker use

        all_broker_responses = {}
        successful_placements = 0
        failed_placements = 0

        active_trade_brokers = await self.broker_manager.get_active_trade_brokers()
        if not active_trade_brokers:
            logger.warning("No active trade-enabled brokers found to place the order.")
            await self.update_order_status_in_db(
                local_order_id, 
                OrderStatus.FAILED, 
                broker_order_id=None, # No broker order ID yet
                broker_message="No active trade brokers available."
            )
            return {
                "overall_status": "error",
                "message": "No active trade brokers available.",
                "broker_responses": {},
                "local_order_id": local_order_id
            }

        for broker_name, broker_instance in active_trade_brokers.items():
            if not broker_instance:  # Should not happen if get_active_trade_brokers works correctly
                logger.warning(f"Broker instance for {broker_name} is None. Skipping.")
                all_broker_responses[broker_name] = {
                    "status": "error",
                    "message": "Broker instance not available."
                }
                failed_placements += 1
                continue
            
            # Enrich order_payload with broker-specific details if necessary
            # For example, resolving the symbol to a broker-specific instrument ID
            try:
                # Assuming broker_instance has a method like get_instrument_details or similar
                # This is a conceptual step; actual implementation depends on broker adapter capabilities
                # For now, we pass the symbol as is, assuming adapters handle it.
                pass
            except Exception as e:
                logger.error(f"Error preparing order for broker {broker_name}: {e}")
                all_broker_responses[broker_name] = {"status": "error", "message": f"Error preparing order: {e}"}
                failed_placements += 1
                continue

            logger.info(f"Placing order with {broker_name} for symbol {order_payload.symbol}")
            try:
                # The place_order method in broker adapters should return a standardized dict:
                # {"status": "success"/"error", "broker_order_id": "some_id_or_none", "message": "...", "raw_response": {...}}
                broker_response = await broker_instance.place_order(order_payload)
                all_broker_responses[broker_name] = broker_response

                # --- Status update logic based on broker_response --- 
                current_order_status_for_db = initial_order_status_for_db # Default to AWAITING_ENTRY if successful
                broker_message_for_db = broker_response.get("message", "No message from broker.")
                broker_order_id_for_db = broker_response.get("broker_order_id")

                if broker_response.get("status") == "success":
                    successful_placements += 1
                    # Status remains AWAITING_ENTRY as per initial logic, or could be more specific if broker confirms entry
                    logger.info(f"Order placed successfully with {broker_name}. Broker Order ID: {broker_order_id_for_db}")
                else: # error or any other non-success status
                    failed_placements += 1
                    current_order_status_for_db = OrderStatus.FAILED # Update to FAILED if this specific broker failed
                    logger.error(f"Order placement failed with {broker_name}: {broker_message_for_db}")
                
                # Update the DB record for this specific broker placement (or the main order if only one broker)
                # If multiple brokers, this logic might need refinement on how to aggregate statuses.
                # For now, let's assume we update the main order record with the latest significant status.
                # If any broker fails, the overall order might be considered FAILED or PARTIALLY_FAILED.
                # This example updates the main order record based on each broker's response.
                await self.update_order_status_in_db(
                    local_order_id,
                    current_order_status_for_db,
                    broker_order_id=broker_order_id_for_db, # Store the actual broker order ID
                    broker_name=broker_name, # Store which broker this ID belongs to
                    broker_message=broker_message_for_db,
                    # raw_broker_response=broker_response.get("raw_response") # If you have a field for this
                )

            except Exception as e:
                logger.error(f"Exception during order placement with {broker_name}: {e}", exc_info=True)
                all_broker_responses[broker_name] = {"status": "error", "message": str(e)}
                failed_placements += 1
                await self.update_order_status_in_db(
                    local_order_id, 
                    OrderStatus.FAILED, 
                    broker_name=broker_name,
                    broker_message=f"SDK/Network Exception: {str(e)}"
                )
        
        # Determine overall status after all broker attempts
        final_overall_status = "error" # Default to error
        final_db_status = OrderStatus.FAILED # Default DB status if all else fails

        if successful_placements > 0 and failed_placements == 0:
            final_overall_status = "success"
            final_db_status = OrderStatus.AWAITING_ENTRY # All brokers succeeded
        elif successful_placements > 0 and failed_placements > 0:
            final_overall_status = "partial_success"
            final_db_status = OrderStatus.PARTIALLY_FILLED # Or some other partial status; AWAITING_ENTRY if at least one is good.
                                                        # Let's stick to AWAITING_ENTRY if at least one succeeded for now.
            final_db_status = OrderStatus.AWAITING_ENTRY 
        elif successful_placements == 0 and failed_placements > 0:
            final_overall_status = "error"
            final_db_status = OrderStatus.FAILED # All brokers failed
        else: # No brokers attempted or other edge case
            final_overall_status = "error"
            final_db_status = OrderStatus.FAILED
            if not active_trade_brokers: # Already handled, but as a fallback
                 final_db_status = OrderStatus.FAILED

        # Final update to the main order record if its status needs to reflect the aggregate outcome.
        # This might overwrite individual broker updates if not careful. 
        # The current loop updates the DB per broker. This final update should reflect the *overall* state.
        # Let's assume the per-broker updates are sufficient for now, and this final status is for the return dict.
        # However, if the order has multiple legs/brokers, the main `orders` table entry needs a summary status.
        # We will update the main order record if its status is still the initial AWAITING_ENTRY and a more definitive FAILED status is now known.
        
        # If the initial status was AWAITING_ENTRY, and now the aggregate is FAILED, update it.
        # This logic needs to be robust. If one broker succeeded, it's AWAITING_ENTRY.
        # If ALL brokers failed, then it's FAILED.
        if final_db_status == OrderStatus.FAILED and successful_placements == 0:
             await self.update_order_status_in_db(
                    local_order_id, 
                    OrderStatus.FAILED, 
                    broker_message="Overall placement failed across all brokers or no successful placements."
                )
        elif final_db_status == OrderStatus.AWAITING_ENTRY and successful_placements > 0:
            # If at least one succeeded, ensure the status reflects that (it should already from the loop)
            # This is more of a confirmation or setting a general success message if needed.
            # The individual broker_order_id and message are more critical from the loop.
            pass # Status is already AWAITING_ENTRY or similar from the loop.

        return {
            "overall_status": final_overall_status,
            "message": f"Order placement summary: {successful_placements} successful, {failed_placements} failed.",
            "broker_responses": all_broker_responses,
            "local_order_id": local_order_id
        }

    async def _set_parent_order_id(self, order_id, parent_order_id):
        """
        Update the parent_order_id of an order row after insert.
        """
        from algosat.core.db import AsyncSessionLocal, update_rows_in_table
        from algosat.core.dbschema import orders
        async with AsyncSessionLocal() as session:
            await update_rows_in_table(
                target_table=orders,
                condition=orders.c.id == order_id,
                new_values={"parent_order_id": parent_order_id}
            )

    async def _insert_and_get_order_id(self, config, order_payload, broker_name, result, parent_order_id):
        """
        Insert order into DB and return the local order_id. Sets parent_order_id if provided.
        Handles both success and failure cases, storing raw broker response if failed.
        """
        def to_native(val):
            if isinstance(val, np.generic):
                return val.item()
            # Ensure Enums are converted to their values *before* other checks
            if hasattr(val, 'value') and isinstance(val, (Side, OrderType)): # More specific check for our enums
                return val.value
            if hasattr(val, 'name') and isinstance(val, (Side, OrderType)): # Fallback for name if value isn't the target (though .value is standard)
                 return val.name
            import pandas as pd
            if isinstance(val, (pd.Timestamp, np.datetime64)):
                if hasattr(val, 'to_pydatetime'):
                    return val.to_pydatetime()
                else:
                    return pd.to_datetime(val).to_pydatetime()
            return val

        async with AsyncSessionLocal() as sess:
            broker_row = await get_broker_by_name(sess, broker_name)
            broker_id = broker_row["id"] if broker_row else None
            strategy_config_id = self.extract_strategy_config_id(config)
            if not strategy_config_id:
                logger.error(f"[OrderManager] Could not extract strategy_config_id from config: {repr(config)}. Order will not be inserted.")
                return None # MODIFIED: Return None if strategy_config_id is not found

            # Initialize order_data with defaults or None
            order_data = {
                "strategy_config_id": None, "broker_id": None, "symbol": None,
                "candle_range": None, "entry_price": None, "stop_loss": None,
                "target_price": None, "signal_time": None, "entry_time": None,
                "exit_time": None, "exit_price": None, "status": "AWAITING_ENTRY",
                "reason": None, "atr": None, "supertrend_signal": None,
                "lot_qty": None, "side": None, "order_ids": json.dumps([]),
                "order_messages": json.dumps({}), "parent_order_id": parent_order_id,
                "qty": None
            }
            
            order_data["strategy_config_id"] = to_native(strategy_config_id)
            order_data["broker_id"] = to_native(broker_id)
            order_data["parent_order_id"] = parent_order_id


            if isinstance(order_payload, OrderRequest):
                # Directly map OrderRequest fields
                order_data["symbol"] = to_native(order_payload.symbol)
                order_data["qty"] = to_native(order_payload.quantity) # Map OrderRequest.quantity to db.qty
                order_data["lot_qty"] = to_native(order_payload.quantity) # Also map to lot_qty for consistency if used elsewhere
                order_data["side"] = to_native(order_payload.side) # to_native will handle Enum.value
                # order_data["order_type_db_col"] = to_native(order_payload.order_type) # If you have a column for order_type
                order_data["entry_price"] = to_native(order_payload.price) # Assuming OrderRequest.price is entry_price

                # Fields from OrderRequest.extra
                extra_data = order_payload.extra if order_payload.extra else {}
                order_data["candle_range"] = to_native(extra_data.get("candle_range"))
                order_data["stop_loss"] = to_native(extra_data.get("stopLoss", extra_data.get("stop_loss")))
                order_data["target_price"] = to_native(extra_data.get("profit", extra_data.get("target_price")))
                order_data["signal_time"] = to_native(extra_data.get("signal_time"))
                order_data["entry_time"] = to_native(extra_data.get("entry_time"))
                order_data["exit_time"] = to_native(extra_data.get("exit_time"))
                order_data["exit_price"] = to_native(extra_data.get("exit_price"))
                order_data["status"] = to_native(extra_data.get("status", order_data["status"])) # Default to AWAITING_ENTRY if not in extra
                order_data["reason"] = to_native(extra_data.get("reason"))
                order_data["atr"] = to_native(extra_data.get("atr"))
                order_data["supertrend_signal"] = to_native(extra_data.get("supertrend_signal"))
                # order_ids and order_messages are typically populated based on broker response, not from initial OrderRequest.extra
                # If they can come from extra, uncomment and adjust:
                # order_data["order_ids"] = json.dumps(extra_data.get("order_ids", []))
                # order_data["order_messages"] = json.dumps(extra_data.get("order_messages", {}))

            else: # Fallback for direct dict payloads (legacy or other parts of system)
                logger.warning("OrderManager received a dict payload instead of OrderRequest. Mapping based on common keys.")
                order_payload_dict = order_payload # It's already a dict
                extra_payload = order_payload_dict.get("extra", {})

                order_data["symbol"] = to_native(order_payload_dict.get("symbol"))
                order_data["qty"] = to_native(order_payload_dict.get("qty", order_payload_dict.get("quantity")))
                order_data["lot_qty"] = to_native(order_payload_dict.get("lot_qty", order_payload_dict.get("quantity")))
                
                side_val = order_payload_dict.get("side")
                if isinstance(side_val, Side): # Handles direct Side enum if passed in dict
                    order_data["side"] = side_val.value
                elif isinstance(side_val, str) and side_val.upper() in [s.value for s in Side]:
                    order_data["side"] = side_val.upper()
                elif isinstance(side_val, int): # Legacy integer side
                    order_data["side"] = "SELL" if side_val == -1 else ("BUY" if side_val == 1 else str(side_val))
                else:
                    order_data["side"] = to_native(side_val)

                order_data["entry_price"] = to_native(order_payload_dict.get("entry_price", order_payload_dict.get("price")))
                
                order_data["candle_range"] = to_native(order_payload_dict.get("candle_range", extra_payload.get("candle_range")))
                order_data["stop_loss"] = to_native(order_payload_dict.get("stop_loss", extra_payload.get("stopLoss")))
                order_data["target_price"] = to_native(order_payload_dict.get("target_price", extra_payload.get("profit")))
                order_data["signal_time"] = to_native(order_payload_dict.get("signal_time", extra_payload.get("signal_time")))
                order_data["entry_time"] = to_native(order_payload_dict.get("entry_time", extra_payload.get("entry_time")))
                order_data["exit_time"] = to_native(order_payload_dict.get("exit_time", extra_payload.get("exit_time")))
                order_data["exit_price"] = to_native(order_payload_dict.get("exit_price", extra_payload.get("exit_price")))
                order_data["status"] = to_native(order_payload_dict.get("status", extra_payload.get("status", order_data["status"])))
                order_data["reason"] = to_native(order_payload_dict.get("reason", extra_payload.get("reason")))
                order_data["atr"] = to_native(order_payload_dict.get("atr", extra_payload.get("atr")))
                order_data["supertrend_signal"] = to_native(order_payload_dict.get("supertrend_signal", extra_payload.get("supertrend_signal")))
                # order_data["order_ids"] = json.dumps(order_payload_dict.get("order_ids", extra_payload.get("order_ids", [])))
                # order_data["order_messages"] = json.dumps(order_payload_dict.get("order_messages", extra_payload.get("order_messages", {})))


            # Process broker response (result)
            current_order_messages = json.loads(order_data["order_messages"]) # Start with any messages from payload
            current_order_ids = json.loads(order_data["order_ids"]) # Start with any ids from payload

            if isinstance(result, dict):
                if not result.get("status", True): # Broker indicates failure
                    order_data["status"] = "FAILED"
                    # Store raw broker response, potentially merging if some messages already existed
                    current_order_messages["raw_broker_response"] = result 
                else: # Broker indicates success or partial success
                    # If broker provides an explicit status, use it if it's more specific than "AWAITING_ENTRY"
                    # or if the current status is still the default.
                    broker_status = result.get("status_message") # Assuming broker might send 'status_message' or similar
                    if broker_status and (order_data["status"] == "AWAITING_ENTRY" or order_data["status"] == "PENDING"): # PENDING might be another initial state
                         order_data["status"] = broker_status

                    # Extract order IDs from broker response
                    # This part is highly dependent on the structure of `result`
                    broker_order_id = result.get("order_id", result.get("id")) # Common keys for order ID
                    if broker_order_id and broker_order_id not in current_order_ids:
                        current_order_ids.append(broker_order_id)
                    
                    # You might also want to store other parts of the successful broker response
                    # For example, if it contains timestamps or filled quantities not in the original request
                    if "message" in result and result["message"]:
                         current_order_messages[f"{broker_name}_response"] = result["message"]


            elif isinstance(result, str): # Simple string response, could be an error or simple ID
                # Heuristic: if it looks like an error message, mark as FAILED
                if "error" in result.lower() or "fail" in result.lower() or "invalid" in result.lower():
                    order_data["status"] = "FAILED"
                current_order_messages[f"{broker_name}_response"] = result


            order_data["order_ids"] = json.dumps(current_order_ids)
            order_data["order_messages"] = json.dumps(current_order_messages)
            
            # Final check for side, ensuring it's a string like "BUY" or "SELL"
            # The to_native function should handle enums correctly.
            # This is an additional safeguard if side somehow bypassed to_native or was set directly.
            if isinstance(order_data.get("side"), Side):
                order_data["side"] = order_data["side"].value
            elif hasattr(order_data.get("side"), 'name') and not isinstance(order_data.get("side"), str): # Catch other potential objects
                 logger.warning(f"Side was an unexpected object: {order_data.get('side')}. Attempting to use its .name or .value.")
                 side_val_temp = order_data.get("side")
                 order_data["side"] = getattr(side_val_temp, 'value', getattr(side_val_temp, 'name', str(side_val_temp)))


            # Log the relevant data for candle_range before insertion
            if isinstance(order_payload, OrderRequest):
                logger.debug(f"Checking order_payload.extra for candle_range: {order_payload.extra}")
            logger.debug(f"Value for 'candle_range' in order_data before DB insert: {order_data.get('candle_range')}")

            # Remove keys with None values before insertion to use DB defaults if any, or avoid type errors for non-nullable columns without defaults.
            # However, be cautious: if a column is non-nullable and has no DB default, this will error.
            # It's often better to ensure all required fields have a valid value (e.g. empty string, 0, default date)
            # For now, keeping all keys as dbschema.py defines defaults for many.
            # order_data_cleaned = {k: v for k, v in order_data.items() if v is not None}


            inserted = await insert_order(sess, order_data) # Use the full order_data
            return inserted["id"] if inserted else None

    async def _get_broker_id(self, broker_name):
        async with AsyncSessionLocal() as sess:
            broker_row = await get_broker_by_name(sess, broker_name)
            return broker_row["id"] if broker_row else None

    async def get_broker_symbol(self, broker_name, symbol, instrument_type=None):
        """
        Returns the correct symbol/token for the given broker using BrokerManager.get_symbol_info.
        """
        return await self.broker_manager.get_symbol_info(broker_name, symbol, instrument_type)

    async def get_order_status(self, order_id):
        """
        Fetch the order status from the DB for a given order_id.
        """
        from algosat.core.db import AsyncSessionLocal, get_order_by_id # Local import
        async with AsyncSessionLocal() as session:
            order = await get_order_by_id(session, order_id)
            return order.get("status") if order else None

    async def update_order_status_in_db(self, order_id, status):
        """
        Update the order status in the DB for a given order_id.
        """
        from algosat.core.db import AsyncSessionLocal, update_rows_in_table # Local import
        from algosat.core.dbschema import orders # Local import
        async with AsyncSessionLocal() as session:
            await update_rows_in_table(
                target_table=orders,
                condition=orders.c.id == order_id,
                new_values={"status": status}
            )
            logger.debug(f"Order {order_id} status updated to {status} in DB.")

_order_manager_instance = None

def get_order_manager(broker_manager: BrokerManager) -> OrderManager:
    global _order_manager_instance
    # Ensure BrokerManager is passed for the first instantiation
    # or if the existing instance was created with a different broker_manager (though this simple version doesn't check that)
    if _order_manager_instance is None or _order_manager_instance.broker_manager != broker_manager:
        _order_manager_instance = OrderManager(broker_manager)
    return _order_manager_instance
