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

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Authenticate user and return user info."""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )
    
    try:
        # Validate token with security manager
        user_info = await security_manager.validate_token(credentials.credentials)
        if not user_info:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token"
            )
        return user_info
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed"
        )
