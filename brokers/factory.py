from typing import Dict, Any, Type
import inspect
from brokers.base import BrokerInterface
from brokers.fyers import FyersWrapper
from brokers.zerodha import ZerodhaWrapper
from brokers.angel import AngelWrapper
from common.logger import get_logger

logger = get_logger("broker_factory")

# Registry mapping broker keys to their wrapper classes
BROKER_REGISTRY: Dict[str, Type[BrokerInterface]] = {
    "fyers": FyersWrapper,
    "zerodha": ZerodhaWrapper,
    "angel": AngelWrapper,
}

# Registry to cache broker instances for reuse
BROKER_INSTANCES: Dict[str, BrokerInterface] = {}


def get_broker(name: str) -> BrokerInterface:
    """
    Factory function to instantiate a broker wrapper.
    Uses a singleton pattern to ensure the same instance is returned for the same broker name.

    Args:
        name: The broker key (e.g., 'fyers', 'zerodha', 'angel').

    Returns:
        An instance of BrokerInterface for the given broker.

    Raises:
        ValueError: If the broker key is unknown.
    """
    key = name.lower()
    
    # Return existing instance if available
    if key in BROKER_INSTANCES:
        logger.debug(f"Reusing existing broker instance for {key}")
        return BROKER_INSTANCES[key]
        
    # Create a new instance if not found
    BrokerClass = BROKER_REGISTRY.get(key)
    if not BrokerClass:
        valid = ", ".join(BROKER_REGISTRY.keys())
        raise ValueError(f"Unknown broker '{name}'. Valid options: {valid}")

    # Instantiate, cache, and return
    logger.info(f"Creating new broker instance for {key}")
    
    # Check if the class has a __init__ method that accepts broker_name
    if hasattr(BrokerClass, "__init__"):
        init_signature = inspect.signature(BrokerClass.__init__)
        if "broker_name" in init_signature.parameters:
            broker_instance = BrokerClass(broker_name=key)
        else:
            # If the class doesn't accept broker_name, instantiate without it
            broker_instance = BrokerClass()
    else:
        # Static or no __init__ method, just instantiate without parameters
        broker_instance = BrokerClass()
        
    BROKER_INSTANCES[key] = broker_instance
    return broker_instance
