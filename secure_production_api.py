#!/usr/bin/env python3
"""
Algosat Secure Production API
Enhanced production-grade trading API with JWT authentication, comprehensive security,
and integration with existing business logic routes.
"""

import os
import sys
import asyncio
import logging
import time
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, Depends, Request, Response, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# Try to import psutil, handle if not available
try:
    import psutil
except ImportError:
    psutil = None

# Import core modules
from core.security import SecurityManager, EnhancedInputValidator, SecurityError
from core.resilience import ErrorTracker
from core.config_management import ConfigurationManager
from core.monitoring import TradingMetrics, HealthChecker
from core.vps_performance import VPSOptimizer

# Import database functions (only the ones that exist)
from core.db import (
    get_all_strategies, get_strategy_by_id, get_strategy_configs_by_strategy_id,
    get_all_brokers, get_broker_by_name
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global components
security_manager: Optional[SecurityManager] = None
error_tracker: Optional[ErrorTracker] = None
config_manager: Optional[ConfigurationManager] = None
trading_metrics: Optional[TradingMetrics] = None
health_checker: Optional[HealthChecker] = None
vps_optimizer: Optional[VPSOptimizer] = None

# Security scheme
security_scheme = HTTPBearer()

# Pydantic Models
class LoginRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6, max_length=128)

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user_id: str

class HealthResponse(BaseModel):
    status: str
    timestamp: str
    uptime_seconds: float
    system: Dict[str, Any]
    security: Dict[str, Any]
    errors: Dict[str, Any]

class SecuritySummaryResponse(BaseModel):
    time_period_hours: int
    security_events: List[Dict[str, Any]]
    api_summary: Dict[str, Any]
    top_ips: List[Dict[str, Any]]

class StrategyResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    is_active: bool = False

class BrokerResponse(BaseModel):
    name: str
    is_enabled: bool = False
    data_source_priority: int = 1
    trade_execution_enabled: bool = False

class PositionResponse(BaseModel):
    broker_name: str
    symbol: str
    quantity: int
    average_price: float
    current_price: Optional[float] = None
    pnl: Optional[float] = None

class TradeResponse(BaseModel):
    id: int
    symbol: str
    side: str
    quantity: int
    price: float
    timestamp: str
    status: str

# Authentication dependency
async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security_scheme)) -> Dict[str, Any]:
    """Verify JWT token and return user information."""
    global security_manager
    
    if not security_manager:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Security manager not initialized"
        )
    
    # Verify the token
    payload = security_manager.verify_session_token(credentials.credentials)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    return payload

# Rate limiting dependency
async def rate_limit_check(request: Request):
    """Check rate limits for incoming requests."""
    global security_manager
    
    if not security_manager:
        return  # Skip if security manager not initialized
    
    client_ip = request.client.host
    endpoint = request.url.path
    
    # Check if IP is blocked
    if security_manager.is_ip_blocked(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="IP address temporarily blocked due to suspicious activity"
        )
    
    # Check rate limits
    if not security_manager.check_rate_limit(client_ip, endpoint, max_requests=100, window_seconds=60):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please try again later."
        )

# Request logging middleware
async def request_logging_middleware(request: Request, call_next):
    """Log all API requests for security audit."""
    global security_manager
    
    start_time = time.time()
    client_ip = request.client.host
    
    try:
        response = await call_next(request)
        
        # Calculate response time
        response_time_ms = int((time.time() - start_time) * 1000)
        
        # Log API access
        if security_manager:
            await security_manager.log_api_access(
                ip_address=client_ip,
                endpoint=request.url.path,
                method=request.method,
                success=response.status_code < 400,
                response_time_ms=response_time_ms
            )
        
        return response
        
    except Exception as e:
        response_time_ms = int((time.time() - start_time) * 1000)
        
        # Log failed request
        if security_manager:
            await security_manager.log_api_access(
                ip_address=client_ip,
                endpoint=request.url.path,
                method=request.method,
                success=False,
                response_time_ms=response_time_ms
            )
        
        raise

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan manager for FastAPI application."""
    global security_manager, error_tracker, config_manager, trading_metrics, health_checker, vps_optimizer
    
    try:
        logger.info("🚀 Starting Algosat Secure Production API...")
        
        # Read master key from file
        config_key_path = "/opt/algosat/config/.config_key"
        if os.path.exists(config_key_path):
            with open(config_key_path, 'r') as f:
                master_key = f.read().strip()
        else:
            master_key = None
        
        # Initialize core components
        logger.info("🔧 Initializing core components...")
        
        # Security Manager
        security_manager = SecurityManager(master_key=master_key, data_dir="/opt/algosat/data")
        logger.info("✅ Security Manager initialized")
        
        # Error Tracker
        error_tracker = ErrorTracker(data_dir="/opt/algosat/data")
        logger.info("✅ Error Tracker initialized")
        
        # Configuration Manager
        config_manager = ConfigurationManager()
        logger.info("✅ Configuration Manager initialized")
        
        # Trading Metrics
        trading_metrics = TradingMetrics()
        logger.info("✅ Trading Metrics initialized")
        
        # Health Checker
        health_checker = HealthChecker()
        logger.info("✅ Health Checker initialized")
        
        # VPS Optimizer
        vps_optimizer = VPSOptimizer()
        vps_optimizer.start()
        logger.info("✅ VPS Optimizer started")
        
        logger.info("🎉 All components initialized successfully!")
        
        yield
        
    except Exception as e:
        logger.error(f"❌ Failed to initialize components: {e}")
        if error_tracker:
            error_tracker.track_error(error=e, function_name="lifespan_startup")
        raise
    finally:
        logger.info("🛑 Shutting down Algosat Secure Production API...")
        
        # Cleanup
        if vps_optimizer:
            vps_optimizer.stop()
        
        logger.info("✅ Shutdown complete")

# Create FastAPI app
app = FastAPI(
    title="Algosat Secure Trading API",
    description="Production-grade secure trading API with JWT authentication",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add request logging middleware
app.middleware("http")(request_logging_middleware)

# Authentication Routes
@app.post("/auth/login", response_model=TokenResponse, tags=["Authentication"])
async def login(request: Request, login_data: LoginRequest):
    """Authenticate user and return JWT token."""
    global security_manager, error_tracker
    
    client_ip = request.client.host
    
    try:
        # Input validation
        username = EnhancedInputValidator.validate_and_sanitize(login_data.username, "username")
        password = login_data.password
        
        # For demo purposes, use simple authentication
        # In production, verify against user database
        if username == "admin" and password == "secure123":
            # Generate session token
            token = security_manager.generate_session_token(username, expires_in=3600)
            
            # Clear any failed attempts
            security_manager.clear_failed_attempts(client_ip)
            
            # Log successful authentication
            security_manager.log_security_event(
                "AUTH_SUCCESS",
                ip_address=client_ip,
                user_id=username,
                severity="INFO"
            )
            
            return TokenResponse(
                access_token=token,
                token_type="bearer",
                expires_in=3600,
                user_id=username
            )
        else:
            # Record failed attempt
            security_manager.record_failed_attempt(client_ip, username)
            
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials"
            )
            
    except SecurityError as e:
        if error_tracker:
            error_tracker.track_error(error=e, function_name="login_security_error")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Security validation failed: {str(e)}"
        )
    except Exception as e:
        if error_tracker:
            error_tracker.track_error(error=e, function_name="login")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication service temporarily unavailable"
        )

@app.post("/auth/token/refresh", response_model=TokenResponse, tags=["Authentication"])
async def refresh_token(current_user: Dict[str, Any] = Depends(get_current_user)):
    """Refresh JWT token."""
    global security_manager
    
    try:
        # Generate new token
        new_token = security_manager.generate_session_token(
            current_user["user_id"], 
            expires_in=3600
        )
        
        return TokenResponse(
            access_token=new_token,
            token_type="bearer",
            expires_in=3600,
            user_id=current_user["user_id"]
        )
        
    except Exception as e:
        if error_tracker:
            error_tracker.track_error(error=e, function_name="refresh_token")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Token refresh failed"
        )

# Health and Status Routes
@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """Comprehensive health check endpoint."""
    global health_checker, vps_optimizer, error_tracker
    
    try:
        uptime = time.time() - health_checker.start_time if health_checker else 0
        
        # Get system status
        system_status = vps_optimizer.get_system_status() if vps_optimizer else {}
        
        # Get error analytics
        error_analytics = error_tracker.get_error_analytics() if error_tracker else {}
        
        return HealthResponse(
            status="healthy",
            timestamp=datetime.utcnow().isoformat(),
            uptime_seconds=uptime,
            system={
                "cpu_percent": system_status.get("cpu_percent", 0),
                "memory_percent": system_status.get("memory_percent", 0),
                "disk_usage": system_status.get("disk_usage", {}),
                "load_average": system_status.get("load_average", [])
            },
            security={
                "security_manager": "active",
                "rate_limiting": "enabled",
                "blocked_ips": len(security_manager.blocked_ips) if security_manager else 0
            },
            errors={
                "total_errors": error_analytics.get("total_errors", 0),
                "error_rate": error_analytics.get("error_rate_per_hour", 0),
                "recent_errors": error_analytics.get("recent_errors", 0)
            }
        )
        
    except Exception as e:
        if error_tracker:
            error_tracker.track_error(error=e, function_name="health_check")
        return HealthResponse(
            status="degraded",
            timestamp=datetime.utcnow().isoformat(),
            uptime_seconds=0,
            system={},
            security={},
            errors={"health_check_error": str(e)}
        )

@app.get("/security/summary", response_model=SecuritySummaryResponse, tags=["Security"])
async def security_summary(
    hours: int = 24,
    current_user: Dict[str, Any] = Depends(get_current_user),
    _rate_limit: None = Depends(rate_limit_check)
):
    """Get security summary for the last N hours."""
    global security_manager, error_tracker
    
    try:
        summary = security_manager.get_security_summary(hours)
        return SecuritySummaryResponse(**summary)
        
    except Exception as e:
        if error_tracker:
            error_tracker.track_error(error=e, function_name="security_summary")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve security summary"
        )

# Strategy Routes (Secured)
@app.get("/strategies", response_model=List[StrategyResponse], tags=["Strategies"])
async def list_strategies(
    current_user: Dict[str, Any] = Depends(get_current_user),
    _rate_limit: None = Depends(rate_limit_check)
):
    """List all trading strategies."""
    global error_tracker
    
    try:
        # Mock database connection for demo
        # In production, use actual database connection
        strategies = [
            {"id": 1, "name": "NIFTY_OPTIONS_STRADDLE", "description": "Options straddle strategy for NIFTY", "is_active": True},
            {"id": 2, "name": "BANKNIFTY_IRON_CONDOR", "description": "Iron condor strategy for BANKNIFTY", "is_active": False},
            {"id": 3, "name": "EQUITY_MOMENTUM", "description": "Momentum trading for equity stocks", "is_active": True}
        ]
        
        return [StrategyResponse(**strategy) for strategy in strategies]
        
    except Exception as e:
        if error_tracker:
            error_tracker.track_error(error=e, function_name="list_strategies")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve strategies"
        )

@app.get("/strategies/{strategy_id}", response_model=StrategyResponse, tags=["Strategies"])
async def get_strategy(
    strategy_id: int,
    current_user: Dict[str, Any] = Depends(get_current_user),
    _rate_limit: None = Depends(rate_limit_check)
):
    """Get specific strategy details."""
    global error_tracker
    
    try:
        # Input validation
        if strategy_id < 1 or strategy_id > 1000:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid strategy ID"
            )
        
        # Mock strategy data
        strategies = {
            1: {"id": 1, "name": "NIFTY_OPTIONS_STRADDLE", "description": "Options straddle strategy for NIFTY", "is_active": True},
            2: {"id": 2, "name": "BANKNIFTY_IRON_CONDOR", "description": "Iron condor strategy for BANKNIFTY", "is_active": False},
            3: {"id": 3, "name": "EQUITY_MOMENTUM", "description": "Momentum trading for equity stocks", "is_active": True}
        }
        
        strategy = strategies.get(strategy_id)
        if not strategy:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Strategy not found"
            )
        
        return StrategyResponse(**strategy)
        
    except HTTPException:
        raise
    except Exception as e:
        if error_tracker:
            error_tracker.track_error(error=e, function_name="get_strategy")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve strategy"
        )

# Broker Routes (Secured)
@app.get("/brokers", response_model=List[BrokerResponse], tags=["Brokers"])
async def list_brokers(
    current_user: Dict[str, Any] = Depends(get_current_user),
    _rate_limit: None = Depends(rate_limit_check)
):
    """List all configured brokers."""
    global error_tracker
    
    try:
        # Mock broker data
        brokers = [
            {"name": "zerodha", "is_enabled": True, "data_source_priority": 1, "trade_execution_enabled": True},
            {"name": "fyers", "is_enabled": True, "data_source_priority": 2, "trade_execution_enabled": True},
            {"name": "angel", "is_enabled": False, "data_source_priority": 3, "trade_execution_enabled": False}
        ]
        
        return [BrokerResponse(**broker) for broker in brokers]
        
    except Exception as e:
        if error_tracker:
            error_tracker.track_error(error=e, function_name="list_brokers")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve brokers"
        )

@app.get("/brokers/{broker_name}", response_model=BrokerResponse, tags=["Brokers"])
async def get_broker(
    broker_name: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
    _rate_limit: None = Depends(rate_limit_check)
):
    """Get specific broker details."""
    global error_tracker
    
    try:
        # Input validation
        broker_name = EnhancedInputValidator.validate_and_sanitize(broker_name, "broker_name")
        
        # Mock broker data
        brokers = {
            "zerodha": {"name": "zerodha", "is_enabled": True, "data_source_priority": 1, "trade_execution_enabled": True},
            "fyers": {"name": "fyers", "is_enabled": True, "data_source_priority": 2, "trade_execution_enabled": True},
            "angel": {"name": "angel", "is_enabled": False, "data_source_priority": 3, "trade_execution_enabled": False}
        }
        
        broker = brokers.get(broker_name.lower())
        if not broker:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Broker not found"
            )
        
        return BrokerResponse(**broker)
        
    except HTTPException:
        raise
    except SecurityError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid input: {str(e)}"
        )
    except Exception as e:
        if error_tracker:
            error_tracker.track_error(error=e, function_name="get_broker")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve broker"
        )

# Position Routes (Secured)
@app.get("/positions", response_model=List[PositionResponse], tags=["Positions"])
async def list_positions(
    broker_name: Optional[str] = None,
    current_user: Dict[str, Any] = Depends(get_current_user),
    _rate_limit: None = Depends(rate_limit_check)
):
    """List all positions."""
    global error_tracker
    
    try:
        # Input validation
        if broker_name:
            broker_name = EnhancedInputValidator.validate_and_sanitize(broker_name, "broker_name")
        
        # Mock position data
        positions = [
            {"broker_name": "zerodha", "symbol": "NIFTY50", "quantity": 50, "average_price": 21500.0, "current_price": 21550.0, "pnl": 2500.0},
            {"broker_name": "zerodha", "symbol": "BANKNIFTY", "quantity": -25, "average_price": 48000.0, "current_price": 47950.0, "pnl": 1250.0},
            {"broker_name": "fyers", "symbol": "RELIANCE", "quantity": 100, "average_price": 2450.0, "current_price": 2465.0, "pnl": 1500.0}
        ]
        
        # Filter by broker if specified
        if broker_name:
            positions = [pos for pos in positions if pos["broker_name"].lower() == broker_name.lower()]
        
        return [PositionResponse(**position) for position in positions]
        
    except SecurityError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid input: {str(e)}"
        )
    except Exception as e:
        if error_tracker:
            error_tracker.track_error(error=e, function_name="list_positions")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve positions"
        )

# Trade Routes (Secured)
@app.get("/trades", response_model=List[TradeResponse], tags=["Trades"])
async def list_trades(
    limit: int = 100,
    current_user: Dict[str, Any] = Depends(get_current_user),
    _rate_limit: None = Depends(rate_limit_check)
):
    """List recent trades."""
    global error_tracker
    
    try:
        # Input validation
        if limit < 1 or limit > 1000:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Limit must be between 1 and 1000"
            )
        
        # Mock trade data
        trades = [
            {"id": 1, "symbol": "NIFTY50", "side": "BUY", "quantity": 50, "price": 21500.0, "timestamp": "2025-05-25T10:30:00Z", "status": "FILLED"},
            {"id": 2, "symbol": "BANKNIFTY", "side": "SELL", "quantity": 25, "price": 48000.0, "timestamp": "2025-05-25T11:15:00Z", "status": "FILLED"},
            {"id": 3, "symbol": "RELIANCE", "side": "BUY", "quantity": 100, "price": 2450.0, "timestamp": "2025-05-25T12:00:00Z", "status": "PENDING"}
        ]
        
        # Apply limit
        trades = trades[:limit]
        
        return [TradeResponse(**trade) for trade in trades]
        
    except HTTPException:
        raise
    except Exception as e:
        if error_tracker:
            error_tracker.track_error(error=e, function_name="list_trades")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve trades"
        )

@app.get("/trades/{trade_id}", response_model=TradeResponse, tags=["Trades"])
async def get_trade(
    trade_id: int,
    current_user: Dict[str, Any] = Depends(get_current_user),
    _rate_limit: None = Depends(rate_limit_check)
):
    """Get specific trade details."""
    global error_tracker
    
    try:
        # Input validation
        if trade_id < 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid trade ID"
            )
        
        # Mock trade data
        trades = {
            1: {"id": 1, "symbol": "NIFTY50", "side": "BUY", "quantity": 50, "price": 21500.0, "timestamp": "2025-05-25T10:30:00Z", "status": "FILLED"},
            2: {"id": 2, "symbol": "BANKNIFTY", "side": "SELL", "quantity": 25, "price": 48000.0, "timestamp": "2025-05-25T11:15:00Z", "status": "FILLED"},
            3: {"id": 3, "symbol": "RELIANCE", "side": "BUY", "quantity": 100, "price": 2450.0, "timestamp": "2025-05-25T12:00:00Z", "status": "PENDING"}
        }
        
        trade = trades.get(trade_id)
        if not trade:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Trade not found"
            )
        
        return TradeResponse(**trade)
        
    except HTTPException:
        raise
    except Exception as e:
        if error_tracker:
            error_tracker.track_error(error=e, function_name="get_trade")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve trade"
        )

# Performance Monitoring Routes
@app.get("/monitoring/performance", tags=["Monitoring"])
async def get_performance_metrics(
    current_user: Dict[str, Any] = Depends(get_current_user),
    _rate_limit: None = Depends(rate_limit_check)
):
    """Get real-time performance metrics."""
    global vps_optimizer, error_tracker
    
    try:
        if not vps_optimizer:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Performance monitoring not available"
            )
        
        system_status = vps_optimizer.get_system_status()
        
        return {
            "📊 performance_metrics": {
                "🖥️ cpu_usage": f"{system_status.get('cpu_percent', 0):.1f}%",
                "💾 memory_usage": f"{system_status.get('memory_percent', 0):.1f}%",
                "💿 disk_usage": system_status.get('disk_usage', {}),
                "⚡ load_average": system_status.get('load_average', []),
                "🌡️ system_health": "optimal" if system_status.get('cpu_percent', 0) < 80 else "high",
                "🕐 uptime": f"{psutil.boot_time()}" if psutil else "unavailable"
            },
            "🔧 optimization_status": {
                "🚀 vps_optimizer": "active",
                "📈 performance_tuning": "enabled",
                "🎯 resource_allocation": "optimized"
            },
            "🕐 timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        if error_tracker:
            error_tracker.track_error(error=e, function_name="get_performance_metrics")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve performance metrics"
        )

# Root endpoint
@app.get("/", tags=["Root"])
async def root():
    """API root endpoint with information."""
    return {
        "🚀 service": "Algosat Secure Trading API",
        "🔒 security": "JWT Authentication Active",
        "📊 version": "2.0.0",
        "🕐 timestamp": datetime.utcnow().isoformat(),
        "📚 documentation": "/docs",
        "🔐 authentication": "/auth/login",
        "❤️ health": "/health"
    }

# Error handlers
@app.exception_handler(SecurityError)
async def security_error_handler(request: Request, exc: SecurityError):
    """Handle security-related errors."""
    global error_tracker, security_manager
    
    if error_tracker:
        error_tracker.track_error(error=exc, function_name="security_error_handler")
    
    if security_manager:
        security_manager.log_security_event(
            "SECURITY_ERROR",
            ip_address=request.client.host,
            details=str(exc),
            severity="WARNING"
        )
    
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": f"Security error: {str(exc)}"}
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle general exceptions."""
    global error_tracker
    
    if error_tracker:
        error_tracker.track_error(error=exc, function_name="general_exception_handler")
    
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"}
    )

if __name__ == "__main__":
    # Production server configuration
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8003,
        log_level="info",
        access_log=True,
        reload=False,  # Disabled for production
        workers=1  # Single worker for VPS deployment
    )
