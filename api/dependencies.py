from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from algosat.core.db import AsyncSessionLocal

# Security setup
security = HTTPBearer(auto_error=False)

# Import SecurityManager - we'll initialize it globally
from algosat.core.security import SecurityManager
security_manager = SecurityManager()

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
