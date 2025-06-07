"""
Enhanced FastAPI application with integrated security, monitoring, and resilience.
Production-grade API server for Algosat trading system.
"""
import asyncio
import logging
import traceback
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List
import os

from dotenv import load_dotenv

import psutil  # Add at the top with other imports
import uvicorn
from fastapi import FastAPI, HTTPException, Depends, Request, Response, status, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, OAuth2PasswordRequestForm
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from algosat.common.logger import get_logger
from pydantic import BaseModel # Added
from sqlalchemy import select
import aiohttp

# Load .env at startup
load_dotenv()

# Import our enhanced modules
from algosat.core.security import SecurityManager, EnhancedInputValidator, User, InvalidInputError
from algosat.core.resilience import ErrorTracker, resilient_operation, AlgosatError
from algosat.core.monitoring import TradingMetrics, HealthChecker
# from algosat.core.vps_performance import VPSOptimizer  # Temporarily disabled
from algosat.core.db import AsyncSessionLocal, get_user_by_username, get_user_by_email, create_user  # For database operations

# Import get_current_user from auth_dependencies instead of defining here
from .auth_dependencies import get_current_user

# Import existing API routes
from .routes import strategies, brokers, positions, trades, orders, nse_data, balance # Uncommented

# Use default port for now
API_PORT = 8000

logger = get_logger("api.app")

# Global instances
security_manager = None
error_tracker = None
trading_metrics = None
health_checker = None
# vps_optimizer = None  # Temporarily disabled
input_validator = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global security_manager, error_tracker, trading_metrics, health_checker, input_validator
    # In lifespan, set security_manager in auth_dependencies
    import algosat.api.auth_dependencies as auth_deps
    
    try:
        logger.info("Starting Algosat API consumer service")
        
        # Initialize security manager (minimal setup without config files)
        security_manager = SecurityManager(
            data_dir="/tmp/algosat_api_security"  # Temporary directory for API security
        )
        auth_deps.security_manager = security_manager
        
        # Initialize error tracking (minimal setup)
        error_tracker = ErrorTracker(
            data_dir="/tmp/algosat_api_errors"  # Temporary directory for API errors
        )
        
        # Initialize monitoring
        trading_metrics = TradingMetrics()
        health_checker = HealthChecker()
        
        # Initialize VPS optimizer - temporarily disabled for testing
        # vps_optimizer = VPSOptimizer()
        # await vps_optimizer.start()
        
        # Initialize input validator
        input_validator = EnhancedInputValidator()
        
        # Test database connection
        try:
            async with AsyncSessionLocal() as session:
                from sqlalchemy import text
                await session.execute(text("SELECT 1"))
            logger.info("Database connection verified")
        except Exception as db_error:
            logger.error(f"Database connection failed | error={str(db_error)}")
            raise
        
        logger.info("Algosat API consumer service initialized successfully")
        yield
        
    except Exception as e:
        logger.error(f"Failed to initialize API consumer service | error={str(e)} | traceback={traceback.format_exc()}")
        raise
    finally:
        # Cleanup
        logger.info("Shutting down Algosat API consumer service")
        # if vps_optimizer:
        #     await vps_optimizer.stop()

# Create FastAPI app with lifespan
app = FastAPI(
    title="Algosat Trading API",
    description="Production-grade trading system API with enhanced security and monitoring",
    version="2.0.0",
    lifespan=lifespan
)

# Pydantic model for token responses
class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int # in seconds
    user_info: Dict[str, Any]

# Pydantic model for login requests
class LoginRequest(BaseModel):
    username: str
    password: str

# Security and middleware setup
from fastapi.middleware.cors import CORSMiddleware
import re

def get_allowed_origins():
    """
    Get allowed CORS origins dynamically.
    This includes common development setups and can be extended for production.
    """
    base_origins = [
        # Development - localhost and 127.0.0.1 with various ports
        "http://localhost:3000",
        "http://127.0.0.1:3000", 
        "http://localhost:3001",
        "http://127.0.0.1:3001",
        "http://localhost:5173",  # Vite dev server
        "http://127.0.0.1:5173",
        # Production/VPS IP address - both HTTP and HTTPS
        "http://82.25.109.188:3000",
        "https://82.25.109.188:3000",
        # Allow all origins for testing (remove in production)
        "*"
    ]
    
    return base_origins

def is_origin_allowed(origin: str) -> bool:
    """
    Check if an origin is allowed.
    This function can be used for more complex origin validation.
    """
    if not origin:
        return False
    
    allowed_origins = get_allowed_origins()
    
    # Check exact matches
    if origin in allowed_origins:
        return True
    
    # Check IP-based patterns for local network access
    ip_patterns = [
        r"http://192\.168\.\d{1,3}\.\d{1,3}:3000",
        r"http://10\.\d{1,3}\.\d{1,3}\.\d{1,3}:3000", 
        r"http://172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}:3000",
        # Pattern for any public IP (be careful with this in production)
        r"http://\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:3000",
    ]
    
    for pattern in ip_patterns:
        if re.match(pattern, origin):
            return True
    
    return False

security = HTTPBearer(auto_error=False)

# Use a more flexible CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_allowed_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["localhost", "127.0.0.1", "82.25.109.188", "*.local", "*"]
)

@app.post("/auth/token/refresh", response_model=TokenResponse, tags=["Authentication"])
async def refresh_token(current_user_info: Dict[str, Any] = Depends(get_current_user)):
    """Refresh JWT token."""
    global security_manager, error_tracker, logger # Ensure globals are accessible
    if not security_manager:
        logger.error("Security manager not available for token refresh")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Security manager not initialized")

    try:
        # Define new token duration
        new_token_duration = timedelta(hours=1) # Example: 1 hour new duration
        
        # Assumes SecurityManager has a method like regenerate_token
        # that takes user_info and an expiry delta, and returns (new_token_string, new_expires_in_seconds)
        new_token_str, new_expires_in_seconds = await security_manager.regenerate_token(
            user_info=current_user_info, 
            expires_delta=new_token_duration
        )

        return TokenResponse(
            access_token=new_token_str,
            token_type="bearer",
            expires_in=new_expires_in_seconds,
            user_info=current_user_info 
        )
    except HTTPException:
        raise
    except Exception as e:
        if error_tracker:
            error_tracker.track_error(error=e, function_name="refresh_token")
        logger.error(f"Token refresh failed | error={str(e)} | exc_info={traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Token refresh service error"
        )

# Request logging middleware
@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    """Log all requests and track metrics."""
    start_time = datetime.now(timezone.utc)
    request_id = f"req_{int(start_time.timestamp() * 1000)}"
    client_ip = request.client.host if request.client else "unknown"
    
    try:
        # Security validation
        await security_manager.validate_request(request)
        
        # Rate limiting
        if not await security_manager.check_rate_limit(client_ip, request.url.path):
            trading_metrics.requests_total.labels(
                method=request.method,
                endpoint=request.url.path,
                status="429"
            ).inc()
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded"
            )
        
        # Process request
        response = await call_next(request)
        
        # Track metrics
        duration = (datetime.now(timezone.utc) - start_time).total_seconds()
        trading_metrics.request_duration.labels(
            method=request.method,
            endpoint=request.url.path
        ).observe(duration)
        
        trading_metrics.requests_total.labels(
            method=request.method,
            endpoint=request.url.path,
            status=str(response.status_code)
        ).inc()
        
        # Log request
        logger.info(
            f"Request processed | request_id={request_id} | method={request.method} | path={request.url.path} | status_code={response.status_code} | duration={duration} | client_ip={client_ip}"
        )
        
        return response
        
    except HTTPException as e:
        # Track HTTP exceptions
        trading_metrics.requests_total.labels(
            method=request.method,
            endpoint=request.url.path,
            status=str(e.status_code)
        ).inc()
        
        logger.warning(
            f"HTTP exception | request_id={request_id} | method={request.method} | path={request.url.path} | status_code={e.status_code} | detail={e.detail}"
        )
        raise
        
    except Exception as e:
        # Track unexpected errors
        error_tracker.track_error(
            error=e,
            function_name="api_middleware"
        )
        
        trading_metrics.errors_total.labels(
            component="api_middleware",
            error_type=type(e).__name__
        ).inc()
        
        logger.error(
            f"Unexpected error | request_id={request_id} | error={str(e)} | traceback={traceback.format_exc()}"
        )
        
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error", "request_id": request_id}
        )

# Enhanced API endpoints

@app.get("/health")
@resilient_operation(max_retries=1, timeout_seconds=5.0)
async def health_check():
    """Comprehensive health check endpoint."""
    try:
        health_status = await health_checker.run_checks()
        
        # Check individual components
        component_status = {
            "database": True,  # Basic health check
            "security": True,  # Security manager is running
            # "vps": True,  # VPS optimizer temporarily disabled
        }
        
        overall_healthy = health_status["status"] == "healthy"
        
        response = {
            "status": "healthy" if overall_healthy else "unhealthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "components": component_status,
            "details": health_status
        }
        
        status_code = status.HTTP_200_OK if overall_healthy else status.HTTP_503_SERVICE_UNAVAILABLE
        
        return JSONResponse(content=response, status_code=status_code)
        
    except Exception as e:
        error_tracker.track_error(
            error=e,
            function_name="health_check"
        )
        return JSONResponse(
            content={
                "status": "error",
                "timestamp": datetime.utcnow().isoformat(),
                "error": str(e)
            },
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@app.get("/metrics")
async def get_metrics():
    """Prometheus metrics endpoint."""
    try:
        metrics_data = generate_latest(trading_metrics.registry)
        return Response(content=metrics_data, media_type=CONTENT_TYPE_LATEST)
    except Exception as e:
        error_tracker.track_error(
            error=e,
            function_name="metrics"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate metrics"
        )

# Hostinger VPS metrics integration
HOSTINGER_VM_ID = os.environ.get("HOSTINGER_VM_ID")
HOSTINGER_API_TOKEN = os.environ.get("HOSTINGER_API_TOKEN")
HOSTINGER_METRICS_URL = f"https://developers.hostinger.com/api/vps/v1/virtual-machines/{HOSTINGER_VM_ID}/metrics"
HOSTINGER_VM_URL = f"https://developers.hostinger.com/api/vps/v1/virtual-machines/{HOSTINGER_VM_ID}"

def get_hostinger_headers():
    if not HOSTINGER_API_TOKEN:
        raise RuntimeError("Hostinger API token not set in environment variable HOSTINGER_API_TOKEN")
    return {"Authorization": f"Bearer {HOSTINGER_API_TOKEN}", "Accept": "application/json"}

async def fetch_hostinger_metrics_last_hour() -> dict:
    """
    Fetch Hostinger metrics for the last 1 hour only.
    """
    url = HOSTINGER_METRICS_URL
    headers = get_hostinger_headers()
    now = datetime.now(timezone.utc)
    one_hour_ago = now - timedelta(hours=1)
    params = {"date_from": one_hour_ago.isoformat(), "date_to": now.isoformat()}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, params=params, timeout=10) as resp:
            if resp.status != 200:
                raise HTTPException(status_code=502, detail=f"Hostinger API error: {resp.status}")
            return await resp.json()

async def fetch_hostinger_vm_details() -> dict:
    """
    Fetch Hostinger VM details.
    """
    url = HOSTINGER_VM_URL
    headers = get_hostinger_headers()
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, timeout=10) as resp:
            if resp.status != 200:
                raise HTTPException(status_code=502, detail=f"Hostinger VM API error: {resp.status}")
            return await resp.json()

@app.get("/system/status")
async def get_system_status(current_user: Dict = Depends(get_current_user)):
    """Get comprehensive system status (authenticated endpoint, uses Hostinger VPS API)."""
    try:
        # Fetch metrics for the last 1 hour
        metrics_data = await fetch_hostinger_metrics_last_hour()
        # Extract the latest value for each metric field
        latest_metrics = {}
        # if metrics_data and "metrics" in metrics_data:
        #     for metric_name, metric_list in metrics_data["metrics"].items():
        #         if isinstance(metric_list, list) and metric_list:
        #             # Take the last (latest) value
        #             latest_metrics[metric_name] = metric_list[-1]
        # # Fetch VM details
        vm_details = await fetch_hostinger_vm_details()
        # Combine and return
        return {
            "vm": vm_details,
            "metrics": metrics_data
        }
    except Exception as e:
        error_tracker.track_error(
            error=e,
            function_name="system_status"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve system status"
        )

@app.post("/auth/login", response_model=TokenResponse, tags=["Authentication"]) # Added response_model
@resilient_operation(max_retries=2, timeout_seconds=10.0)
async def login(login_request: LoginRequest, request: Request):
    """Enhanced login endpoint with security features."""
    try:
        # Validate input
        validated_input = input_validator.validate_auth_input({
            "username": login_request.username,
            "password": login_request.password
        })
        
        # Attempt authentication
        auth_result = await security_manager.authenticate_user(
            username=validated_input["username"],
            password=validated_input["password"],
            request_info={
                "ip": request.client.host,
                "user_agent": request.headers.get("user-agent", ""),
                "timestamp": datetime.utcnow()
            }
        )
        
        if auth_result["success"]:
            # Return TokenResponse model
            return TokenResponse(
                access_token=auth_result["token"],
                expires_in=auth_result["expires_in"],
                user_info=auth_result["user_info"]
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=auth_result["message"]
            )
            
    except HTTPException:
        raise
    except Exception as e:
        error_tracker.track_error(
            error=e,
            function_name="login"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication service error"
        )

@app.post("/auth/logout")
async def logout(current_user: Dict = Depends(get_current_user)):
    """Logout endpoint."""
    try:
        await security_manager.logout_user(current_user["user_id"])
        return {"message": "Successfully logged out"}
    except Exception as e:
        error_tracker.track_error(
            error=e,
            function_name="logout"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Logout failed"
        )

@app.get("/config/summary")
async def get_config_summary(current_user: Dict = Depends(get_current_user)):
    """Get configuration summary from database (consumer-only API)."""
    try:
        # Return basic info since we're a consumer-only service
        return {
            "service_type": "consumer-only",
            "description": "This API service reads from shared database",
            "database_connected": True,
            "endpoints": [
                "/strategies - Read strategies from database",
                "/brokers - Read broker configs from database", 
                "/positions - Read positions from database",
                "/trades - Read trades from database",
                "/orders - Read orders from database"
            ]
        }
    except Exception as e:
        error_tracker.track_error(
            error=e,
            function_name="get_config_summary"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve configuration summary"
        )

@app.put("/config/update")
async def update_config(request: Request, current_user: Dict = Depends(get_current_user)):
    """Configuration updates not supported in consumer-only API."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Configuration updates not supported in consumer-only API service. Use the main backend service for configuration changes."
    )

# Exception handler for InvalidInputError
@app.exception_handler(InvalidInputError)
async def invalid_input_exception_handler(request: Request, exc: InvalidInputError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": str(exc)},
    )

# Register user endpoint
from algosat.api.schemas import UserRegisterRequest, UserResponse

@app.post("/auth/register", response_model=UserResponse, tags=["Authentication"])
async def register_user(user: UserRegisterRequest, request: Request):
    """User registration endpoint."""
    async with AsyncSessionLocal() as session:
        # Check if username or email already exists
        if await get_user_by_username(session, user.username):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")
        if await get_user_by_email(session, user.email):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already exists")
        # Hash password
        hashed_password = security_manager.hash_password(user.password)
        # Create user
        db_user = await create_user(
            session,
            username=user.username,
            email=user.email,
            hashed_password=hashed_password,
            full_name=user.full_name,
        )
        return UserResponse(**db_user)

# New endpoints to list and delete users
@app.get("/users", response_model=List[UserResponse], tags=["Users"])
async def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    current_user: Dict = Depends(get_current_user)
):
    """List all users (paginated, requires authentication)."""
    async with AsyncSessionLocal() as session:
        from algosat.core.dbschema import users
        result = await session.execute(select(users).offset(skip).limit(limit))
        users_list = [UserResponse(**dict(row._mapping)) for row in result.fetchall()]
        return users_list

@app.delete("/users/{user_id}", response_model=dict, tags=["Users"])
async def delete_user(user_id: int, current_user: Dict = Depends(get_current_user)):
    """Delete a user by user_id (requires authentication)."""
    async with AsyncSessionLocal() as session:
        from algosat.core.dbschema import users
        result = await session.execute(select(users).where(users.c.id == user_id))
        user = result.first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        await session.execute(users.delete().where(users.c.id == user_id))
        await session.commit()
        return {"detail": f"User {user_id} deleted"}

# Include existing routers with security wrapper
def create_secured_router(router, prefix: str, tags: List[str]):
    """Wrap existing router with security middleware."""
    # This would ideally wrap each route with security, but for now we'll include as-is
    # and add security at the middleware level
    app.include_router(router, prefix=prefix, tags=tags)

# Include existing API routes (commented out until routes are available)
create_secured_router(strategies.router, "/strategies", ["Strategies"]) # Uncommented
create_secured_router(brokers.router, "/brokers", ["Brokers"]) # Uncommented
create_secured_router(positions.router, "/positions", ["Positions"]) # Uncommented
create_secured_router(trades.router, "/trades", ["Trades"]) # Uncommented
create_secured_router(orders.router, "/orders", ["Orders"]) # Added orders router
create_secured_router(nse_data.router, "/nse", ["NSE Data"]) # Added NSE Data router
create_secured_router(balance.router, "/api/v1", ["Balance Summary"]) # Added balance router

@app.get("/")
async def root():
    """Root endpoint with system information."""
    return {
        "status": "ok",
        "message": "Algosat Trading API v2.0 (Consumer Service)",
        "service_type": "consumer-only",
        "description": "Database consumer API service - reads from shared database",
        "features": [
            "Enhanced Security",
            "Error Tracking", 
            "Performance Monitoring",
            # "VPS Optimization",  # Temporarily disabled
            "Database Consumer (Read-Only)"
        ],
        "endpoints": {
            "strategies": "Read strategies from database",
            "brokers": "Read broker configurations from database",
            "positions": "Read positions from database", 
            "trades": "Read trades from database",
            "orders": "Read orders from database"
        },
        "timestamp": datetime.utcnow().isoformat()
    }

# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler for unhandled errors."""
    request_id = f"err_{int(datetime.utcnow().timestamp() * 1000)}"
    
    if error_tracker:
        error_tracker.track_error(
            error=exc,
            function_name="global_handler"
        )
    
    logger.error(
        f"Unhandled exception | request_id={request_id} | error={str(exc)} | traceback={traceback.format_exc()}"
    )
    
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "Internal server error",
            "request_id": request_id,
            "timestamp": datetime.utcnow().isoformat()
        }
    )

# Define get_current_user here to use the correct security_manager
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
security = HTTPBearer(auto_error=False)

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    global security_manager
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )
    if not security_manager:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Security manager not initialized"
        )
    user_info = await security_manager.validate_token(credentials.credentials)
    if not user_info:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token"
        )
    return user_info

if __name__ == "__main__":
    uvicorn.run(
        app,  # Direct reference to app instead of string import
        host="0.0.0.0",
        port=int(os.environ.get("API_PORT", 8001)),  # Use API_PORT env variable or default to 8001
        reload=False,  # Disable in production
        workers=1,     # Single worker for VPS deployment
        log_level="info",
        access_log=True
    )
