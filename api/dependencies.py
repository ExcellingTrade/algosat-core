from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from algosat.core.db import AsyncSessionLocal

# Security setup
security = HTTPBearer(auto_error=False)

# Import SecurityManager - we'll initialize it globally
from algosat.core.security import SecurityManager
security_manager = SecurityManager()

# Global instances for dependency injection
_broker_manager_instance = None
_order_manager_instance = None

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

async def get_broker_manager():
    """
    Get or create the global BrokerManager instance with proper initialization.
    """
    global _broker_manager_instance
    if _broker_manager_instance is None:
        from algosat.core.broker_manager import BrokerManager
        _broker_manager_instance = BrokerManager()
        # Initialize the broker manager if not already done
        await _broker_manager_instance.setup()
    return _broker_manager_instance

async def get_order_manager(broker_manager = Depends(get_broker_manager)):
    """
    Get or create the global OrderManager instance with BrokerManager dependency.
    """
    global _order_manager_instance
    if _order_manager_instance is None:
        from algosat.core.order_manager import OrderManager
        _order_manager_instance = OrderManager(broker_manager)
    return _order_manager_instance
