"""
Utilities for handling Bracket Order (BO) and Cover Order (CO) execution tracking.
"""
from typing import Dict, List, Optional
from algosat.core.order_request import ExecutionSide
from algosat.core.order_manager import OrderManager
from algosat.common.logger import get_logger

logger = get_logger("BOUtils")

class BracketOrderProcessor:
    """
    Handles the complex logic of tracking BO/CO executions where:
    - Entry order creates the initial position
    - SL and Target orders are child orders that can execute independently
    - Manual exits can happen outside of the BO framework
    """
    
    def __init__(self, order_manager: OrderManager):
        self.order_manager = order_manager
    
    async def process_bo_entry_execution(
        self,
        parent_order_id: int,
        broker_name: str,
        entry_order_data: dict
    ):
        """
        Process the entry leg of a BO order.
        
        Args:
            parent_order_id: Logical order ID
            broker_name: Broker name
            entry_order_data: Entry order execution data
        """
        try:
            # Mark as ENTRY execution
            entry_order_data['is_exit'] = False
            entry_order_data['notes'] = 'BO Entry Leg'
            
            await self.order_manager.process_broker_order_update(
                parent_order_id, broker_name, entry_order_data
            )
            
            logger.info(f"Processed BO entry for order {parent_order_id}")
            
        except Exception as e:
            logger.error(f"Error processing BO entry: {e}", exc_info=True)
    
    async def process_bo_exit_execution(
        self,
        parent_order_id: int,
        broker_name: str,
        exit_order_data: dict,
        exit_type: str = "SL"  # "SL", "TARGET", or "MANUAL"
    ):
        """
        Process the exit leg of a BO order (SL, Target, or Manual).
        
        Args:
            parent_order_id: Logical order ID
            broker_name: Broker name
            exit_order_data: Exit order execution data
            exit_type: Type of exit - "SL", "TARGET", or "MANUAL"
        """
        try:
            # Mark as EXIT execution
            exit_order_data['is_exit'] = True
            exit_order_data['notes'] = f'BO {exit_type} Leg'
            
            await self.order_manager.process_broker_order_update(
                parent_order_id, broker_name, exit_order_data
            )
            
            logger.info(f"Processed BO {exit_type} exit for order {parent_order_id}")
            
        except Exception as e:
            logger.error(f"Error processing BO exit: {e}", exc_info=True)
    
    async def handle_bo_status_update(
        self,
        parent_order_id: int,
        broker_name: str,
        bo_status_data: dict
    ):
        """
        Handle comprehensive BO status update including all legs.
        
        Expected bo_status_data format:
        {
            "entry_order": {
                "order_id": "123-BO-1",
                "status": "FILLED",
                "executed_qty": 100,
                "executed_price": 245.50,
                ...
            },
            "sl_order": {
                "order_id": "124-BO-2",
                "status": "CANCELLED",  # or "FILLED"
                ...
            },
            "target_order": {
                "order_id": "125-BO-3",
                "status": "CANCELLED",  # or "FILLED"
                ...
            }
        }
        """
        try:
            # Process entry order
            entry_order = bo_status_data.get('entry_order')
            if entry_order and entry_order.get('status') in ['FILLED', 'PARTIAL']:
                await self.process_bo_entry_execution(
                    parent_order_id, broker_name, entry_order
                )
            
            # Process SL order if filled
            sl_order = bo_status_data.get('sl_order')
            if sl_order and sl_order.get('status') in ['FILLED', 'PARTIAL']:
                await self.process_bo_exit_execution(
                    parent_order_id, broker_name, sl_order, "SL"
                )
            
            # Process Target order if filled
            target_order = bo_status_data.get('target_order')
            if target_order and target_order.get('status') in ['FILLED', 'PARTIAL']:
                await self.process_bo_exit_execution(
                    parent_order_id, broker_name, target_order, "TARGET"
                )
            
            logger.info(f"Processed complete BO status update for order {parent_order_id}")
            
        except Exception as e:
            logger.error(f"Error handling BO status update: {e}", exc_info=True)
    
    async def handle_manual_exit(
        self,
        parent_order_id: int,
        broker_name: str,
        manual_exit_data: dict
    ):
        """
        Handle manual exit outside of BO framework.
        This happens when user manually squares off position or when
        max loss triggers force square-off.
        """
        try:
            manual_exit_data['is_exit'] = True
            manual_exit_data['notes'] = 'Manual Exit'
            
            await self.order_manager.process_broker_order_update(
                parent_order_id, broker_name, manual_exit_data
            )
            
            logger.info(f"Processed manual exit for order {parent_order_id}")
            
        except Exception as e:
            logger.error(f"Error processing manual exit: {e}", exc_info=True)

def determine_execution_side_from_order_id(broker_order_id: str) -> ExecutionSide:
    """
    Utility function to determine if an order ID represents entry or exit
    based on broker naming conventions.
    
    Examples:
    - "123456-BO-1" -> ENTRY (main leg)
    - "123457-BO-2" -> EXIT (SL leg)  
    - "123458-BO-3" -> EXIT (Target leg)
    - "999999" -> ENTRY (regular order, assume entry)
    """
    if "-BO-1" in broker_order_id:
        return ExecutionSide.ENTRY
    elif "-BO-2" in broker_order_id or "-BO-3" in broker_order_id:
        return ExecutionSide.EXIT
    else:
        # For non-BO orders, we need additional context
        # This could be enhanced with order tracking state
        return ExecutionSide.ENTRY

def parse_bo_order_response(broker_response: dict) -> dict:
    """
    Parse complex BO order response from broker into structured format.
    
    Different brokers have different response formats for BO orders.
    This function normalizes them into a standard format.
    """
    # This is a placeholder - actual implementation would depend on
    # specific broker response formats
    
    if "fyers" in str(broker_response).lower():
        # Handle Fyers BO response format
        return parse_fyers_bo_response(broker_response)
    elif "zerodha" in str(broker_response).lower():
        # Handle Zerodha BO response format
        return parse_zerodha_bo_response(broker_response)
    else:
        # Generic fallback
        return broker_response

def parse_fyers_bo_response(response: dict) -> dict:
    """Parse Fyers-specific BO response format."""
    # Placeholder for Fyers-specific parsing
    return {
        "entry_order": response.get("entry_order", {}),
        "sl_order": response.get("sl_order", {}),
        "target_order": response.get("target_order", {})
    }

def parse_zerodha_bo_response(response: dict) -> dict:
    """Parse Zerodha-specific BO response format."""
    # Placeholder for Zerodha-specific parsing
    return {
        "entry_order": response.get("entry_order", {}),
        "sl_order": response.get("sl_order", {}),
        "target_order": response.get("target_order", {})
    }
