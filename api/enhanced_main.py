"""
Enhanced FastAPI application with security, monitoring, and production features.
"""
import asyncio
import logging
import traceback
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Depends, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from algosat.common.logger import get_logger
from algosat.core.config_manager import ConfigManager

from core.config_manager import config_manager, settings
from core.security import security_manager, InputValidator
from core.monitoring import trading_metrics, health_checker, performance_monitor
from core.resilience import exception_handler
from api.routes import orders, strategies, brokers, health

logger = get_logger("api.main")

# Security
security = HTTPBearer()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management."""
    # Startup
    logger.info("Starting Algosat Trading System")
    
    # Validate configuration
    config_issues = config_manager.validate_configuration()
    if config_issues:
        logger.warning(f"Configuration issues detected: {config_issues}")
        if settings.is_production:
            logger.error("Configuration issues in production - startup aborted")
            raise RuntimeError("Invalid production configuration")
    
    # Initialize monitoring
    if config_manager.monitoring.prometheus_enabled:
        logger.info(f"Prometheus metrics enabled on port {config_manager.monitoring.metrics_port}")
    
    # Initialize health checks
    if config_manager.monitoring.enable_health_checks:
        logger.info(f"Health checks enabled with interval {config_manager.monitoring.health_check_interval}")
    
    # Startup complete
    logger.info("Algosat Trading System started successfully")
    
    yield
    
    # Shutdown
    logger.info("Shutting down Algosat Trading System")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Production-grade algorithmic trading system",
    lifespan=lifespan,
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None
)

# Middleware setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=config_manager.security.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if config_manager.security.trusted_proxies:
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=config_manager.security.trusted_proxies
    )


# Request/Response middleware for monitoring
@app.middleware("http")
async def monitoring_middleware(request: Request, call_next):
    """Monitor request metrics and performance."""
    start_time = time.time()
    
    # Extract request info
    method = request.method
    endpoint = request.url.path
    
    try:
        response = await call_next(request)
        status_code = response.status_code
        
        # Record metrics
        trading_metrics.requests_total.labels(
            method=method,
            endpoint=endpoint,
            status=status_code
        ).inc()
        
        duration = time.time() - start_time
        trading_metrics.request_duration.labels(
            method=method,
            endpoint=endpoint
        ).observe(duration)
        
        return response
        
    except Exception as e:
        # Record error metrics
        trading_metrics.errors_total.labels(
            component="api",
            error_type=type(e).__name__
        ).inc()
        
        logger.error(
            f"Request failed | method={method} | endpoint={endpoint} | error={str(e)}",
            exc_info=True
        )
        
        raise HTTPException(
            status_code=500,
            detail="Internal server error"
        )


# Authentication dependency
async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Authenticate user from JWT token."""
    try:
        token = credentials.credentials
        payload = security_manager.verify_api_key(token)
        
        if not payload:
            raise HTTPException(
                status_code=401,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        return payload
        
    except Exception as e:
        logger.warning(f"Authentication failed | error={str(e)}")
        raise HTTPException(
            status_code=401,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


# Optional authentication (for some endpoints)
async def get_optional_user(request: Request) -> Optional[Dict[str, Any]]:
    """Get user if authenticated, None otherwise."""
    try:
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return None
            
        token = auth_header.split(" ")[1]
        return security_manager.verify_api_key(token)
    except:
        return None


# Core API routes
app.include_router(orders.router, prefix="/api/v1/orders", tags=["orders"])
app.include_router(strategies.router, prefix="/api/v1/strategies", tags=["strategies"])
app.include_router(brokers.router, prefix="/api/v1/brokers", tags=["brokers"])
app.include_router(health.router, prefix="/api/v1/health", tags=["health"])


# System endpoints
@app.get("/")
async def root():
    """Root endpoint with system information."""
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment.value,
        "status": "operational"
    }


@app.get("/health")
async def health_check():
    """Basic health check endpoint."""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


@app.get("/health/detailed")
async def detailed_health_check(user: dict = Depends(get_current_user)):
    """Detailed health check with component status."""
    health_status = await health_checker.run_checks()
    return health_status


@app.get("/metrics")
async def metrics_endpoint():
    """Prometheus metrics endpoint."""
    if not config_manager.monitoring.prometheus_enabled:
        raise HTTPException(status_code=404, detail="Metrics not enabled")
    
    metrics_data = generate_latest(trading_metrics.registry)
    return Response(content=metrics_data, media_type=CONTENT_TYPE_LATEST)


@app.get("/config")
async def get_configuration(user: dict = Depends(get_current_user)):
    """Get system configuration (admin only)."""
    if user.get('role') != 'admin':
        raise HTTPException(status_code=403, detail="Admin access required")
    
    # Return sanitized configuration (no secrets)
    config_dict = config_manager.to_dict()
    
    # Remove sensitive information
    if 'security' in config_dict:
        config_dict['security'].pop('master_key', None)
        config_dict['security'].pop('jwt_secret', None)
    
    for broker_config in config_dict.get('brokers', {}).values():
        broker_config.pop('credentials', None)
    
    return config_dict


@app.post("/config/reload")
async def reload_configuration(user: dict = Depends(get_current_user)):
    """Reload system configuration (admin only)."""
    if user.get('role') != 'admin':
        raise HTTPException(status_code=403, detail="Admin access required")
    
    try:
        # Reload configuration
        global config_manager
        config_manager = ConfigManager()
        
        # Validate new configuration
        issues = config_manager.validate_configuration()
        
        return {
            "status": "reloaded",
            "issues": issues,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Configuration reload failed | error={str(e)}")
        raise HTTPException(status_code=500, detail=f"Reload failed: {str(e)}")


@app.get("/errors")
async def get_error_summary(user: dict = Depends(get_current_user)):
    """Get error summary and statistics."""
    error_summary = exception_handler.get_error_summary()
    return error_summary


@app.get("/performance")
async def get_performance_metrics(user: dict = Depends(get_current_user)):
    """Get performance metrics and alerts."""
    performance_monitor.check_thresholds()
    
    return {
        "alerts": performance_monitor.alerts[-50:],  # Last 50 alerts
        "thresholds": performance_monitor.thresholds,
        "timestamp": datetime.utcnow().isoformat()
    }


# Error handlers
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions with proper logging."""
    logger.warning(
        f"HTTP exception | status_code={exc.status_code} | detail={exc.detail} | path={request.url.path} | method={request.method}"
    )
    
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "status_code": exc.status_code,
            "timestamp": datetime.utcnow().isoformat()
        }
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle general exceptions with proper logging."""
    error_id = str(uuid.uuid4())
    
    logger.error(
        f"Unhandled exception | error_id={error_id} | error_type={type(exc).__name__} | error_message={str(exc)} | path={request.url.path} | method={request.method}",
        exc_info=True
    )
    
    # Record error metrics
    trading_metrics.errors_total.labels(
        component="api",
        error_type=type(exc).__name__
    ).inc()
    
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "error_id": error_id,
            "timestamp": datetime.utcnow().isoformat()
        }
    )


# WebSocket endpoint for real-time updates
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time trading updates."""
    await websocket.accept()
    
    try:
        # Authenticate WebSocket connection
        auth_data = await websocket.receive_json()
        token = auth_data.get('token')
        
        if not token:
            await websocket.close(code=4001, reason="Authentication required")
            return
        
        user = security_manager.verify_api_key(token)
        if not user:
            await websocket.close(code=4001, reason="Invalid token")
            return
        
        # Handle WebSocket communication
        while True:
            try:
                data = await websocket.receive_json()
                
                # Process WebSocket messages
                message_type = data.get('type')
                
                if message_type == 'subscribe_orders':
                    # Subscribe to order updates
                    pass
                elif message_type == 'subscribe_positions':
                    # Subscribe to position updates
                    pass
                else:
                    await websocket.send_json({
                        "error": f"Unknown message type: {message_type}"
                    })
                    
            except Exception as e:
                logger.error(f"WebSocket error | error={str(e)}")
                break
                
    except Exception as e:
        logger.error(f"WebSocket connection error | error={str(e)}")
    finally:
        try:
            await websocket.close()
        except:
            pass


if __name__ == "__main__":
    import time
    import uuid
    from datetime import datetime
    from fastapi import WebSocket
    
    # Configure logging
    logging.basicConfig(
        level=getattr(logging, config_manager.monitoring.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    # Start the application
    uvicorn.run(
        "api.enhanced_main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.is_development,
        log_level=config_manager.monitoring.log_level.lower(),
        access_log=True
    )
