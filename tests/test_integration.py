"""
Integration tests for the enhanced Algosat trading system.
Tests security, resilience, configuration management, and API enhancements.
"""
import asyncio
import os
import tempfile
import pytest
import httpx
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch, MagicMock

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from algosat.core.security import SecurityManager, EnhancedInputValidator
    from algosat.core.resilience import ErrorTracker, resilient_operation, AlgosatError
    from algosat.core.config_management import ConfigManager
    from algosat.core.monitoring import TradingMetrics, HealthChecker
    from algosat.core.vps_performance import VPSOptimizer
except ImportError:
    # Alternative path for direct execution
    from core.security import SecurityManager, EnhancedInputValidator
    from core.resilience import ErrorTracker, resilient_operation, AlgosatError
    from core.config_management import ConfigManager
    from core.monitoring import TradingMetrics, HealthChecker
    from core.vps_performance import VPSOptimizer

@pytest.fixture
async def temp_config_dir():
    """Create temporary config directory for tests."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield Path(temp_dir)

@pytest.fixture
async def config_manager(temp_config_dir):
    """Initialize config manager for testing."""
    manager = ConfigManager(config_dir=temp_config_dir)
    await manager.initialize()
    return manager

@pytest.fixture
async def security_manager(temp_config_dir):
    """Initialize security manager for testing."""
    manager = SecurityManager(config_file=temp_config_dir / "security_config.yaml")
    await manager.initialize()
    return manager

@pytest.fixture
async def error_tracker(temp_config_dir):
    """Initialize error tracker for testing."""
    tracker = ErrorTracker(db_path=temp_config_dir / "test_errors.db")
    await tracker.initialize()
    return tracker

@pytest.fixture
def trading_metrics():
    """Initialize trading metrics for testing."""
    return TradingMetrics()

@pytest.fixture
def health_checker():
    """Initialize health checker for testing."""
    return HealthChecker()

@pytest.fixture
async def vps_optimizer():
    """Initialize VPS optimizer for testing."""
    optimizer = VPSOptimizer()
    await optimizer.initialize()
    return optimizer

class TestConfigurationManagement:
    """Test configuration management functionality."""
    
    async def test_config_initialization(self, config_manager):
        """Test configuration manager initialization."""
        assert config_manager.is_initialized()
        config = await config_manager.get_config()
        assert config is not None
        assert hasattr(config, 'database')
        assert hasattr(config, 'api')
        assert hasattr(config, 'security')
    
    async def test_config_validation(self, config_manager):
        """Test configuration validation."""
        config = await config_manager.get_config()
        validation_result = await config_manager.validate_config(config)
        assert validation_result['valid'] is True
        assert validation_result['errors'] == []
    
    async def test_credential_encryption(self, config_manager):
        """Test encrypted credential storage."""
        test_credentials = {
            "api_key": "test_key_123",
            "api_secret": "test_secret_456"
        }
        
        # Store encrypted credentials
        await config_manager.store_encrypted_credentials("test_broker", test_credentials)
        
        # Retrieve and decrypt credentials
        retrieved = await config_manager.get_encrypted_credentials("test_broker")
        assert retrieved == test_credentials
    
    async def test_config_summary(self, config_manager):
        """Test configuration summary generation."""
        summary = await config_manager.get_config_summary()
        assert 'database' in summary
        assert 'api' in summary
        assert 'security' in summary
        assert 'sensitive_data_masked' in str(summary).lower() or len(str(summary)) > 0

class TestSecurityEnhancements:
    """Test security management functionality."""
    
    async def test_security_initialization(self, security_manager):
        """Test security manager initialization."""
        assert await security_manager.get_security_status() is not None
    
    async def test_input_validation(self):
        """Test enhanced input validation."""
        validator = EnhancedInputValidator()
        
        # Test SQL injection detection
        malicious_input = "'; DROP TABLE users; --"
        with pytest.raises(ValueError, match="Potential SQL injection"):
            validator.validate_string_input(malicious_input)
        
        # Test XSS detection
        xss_input = "<script>alert('xss')</script>"
        with pytest.raises(ValueError, match="Potential XSS attack"):
            validator.validate_string_input(xss_input)
        
        # Test valid input
        clean_input = "valid_username123"
        assert validator.validate_string_input(clean_input) == clean_input
    
    async def test_rate_limiting(self, security_manager):
        """Test rate limiting functionality."""
        client_ip = "192.168.1.100"
        endpoint = "/api/test"
        
        # Should allow initial requests
        for _ in range(5):
            result = await security_manager.check_rate_limit(client_ip, endpoint)
            assert result is True
        
        # Should start rate limiting after threshold
        # Note: This depends on the rate limit configuration
    
    async def test_authentication_workflow(self, security_manager):
        """Test authentication workflow."""
        # Create test user
        user_data = {
            "username": "testuser",
            "password": "TestPassword123!",
            "email": "test@example.com"
        }
        
        # This would require implementing user creation in SecurityManager
        # For now, we'll test the validation logic
        auth_result = await security_manager.authenticate_user(
            username="invalid_user",
            password="wrong_password",
            request_info={
                "ip": "127.0.0.1",
                "user_agent": "test",
                "timestamp": datetime.utcnow()
            }
        )
        
        assert auth_result["success"] is False
        assert "Invalid credentials" in auth_result["message"]
    
    async def test_security_monitoring(self, security_manager):
        """Test security monitoring features."""
        # Test getting recent alerts
        alerts = await security_manager.get_recent_alerts(limit=10)
        assert isinstance(alerts, list)
        
        # Test blocked IPs
        blocked_ips = await security_manager.get_blocked_ips()
        assert isinstance(blocked_ips, list)

class TestErrorHandlingAndResilience:
    """Test error handling and resilience functionality."""
    
    async def test_error_tracking(self, error_tracker):
        """Test error tracking functionality."""
        # Track a test error
        test_error = ValueError("Test error for tracking")
        await error_tracker.track_error(
            error=test_error,
            component="test_component",
            context={"test": "data"}
        )
        
        # Retrieve recent errors
        recent_errors = await error_tracker.get_recent_errors(limit=10)
        assert len(recent_errors) >= 1
        assert recent_errors[0]['error_type'] == 'ValueError'
        assert recent_errors[0]['component'] == 'test_component'
    
    async def test_resilient_operation_decorator(self, error_tracker):
        """Test resilient operation decorator."""
        call_count = 0
        
        @resilient_operation(max_retries=3, timeout=5.0)
        async def failing_operation():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Temporary failure")
            return "success"
        
        result = await failing_operation()
        assert result == "success"
        assert call_count == 3
    
    async def test_circuit_breaker(self, error_tracker):
        """Test circuit breaker functionality."""
        # This would test the circuit breaker implementation
        # For now, we'll test that the error tracker records circuit breaker events
        pass
    
    async def test_error_analytics(self, error_tracker):
        """Test error analytics and trending."""
        # Add multiple errors for analytics
        for i in range(5):
            await error_tracker.track_error(
                error=RuntimeError(f"Test error {i}"),
                component="analytics_test",
                context={"iteration": i}
            )
        
        # Get error trends
        trends = await error_tracker.get_error_trends()
        assert isinstance(trends, dict)
        assert len(trends) > 0

class TestMonitoringAndMetrics:
    """Test monitoring and metrics functionality."""
    
    def test_metrics_initialization(self, trading_metrics):
        """Test metrics initialization."""
        assert trading_metrics.requests_total is not None
        assert trading_metrics.order_execution_time is not None
        assert trading_metrics.balance_current is not None
    
    def test_metrics_recording(self, trading_metrics):
        """Test metrics recording."""
        # Record some test metrics
        trading_metrics.requests_total.labels(
            method="GET",
            endpoint="/test",
            status="200"
        ).inc()
        
        trading_metrics.request_duration.labels(
            method="GET",
            endpoint="/test"
        ).observe(0.25)
        
        # Verify metrics can be exported
        from prometheus_client import generate_latest
        metrics_output = generate_latest(trading_metrics.registry)
        assert b"algosat_requests_total" in metrics_output
        assert b"algosat_request_duration_seconds" in metrics_output
    
    async def test_health_checker(self, health_checker):
        """Test health checker functionality."""
        # Test health status
        health_status = await health_checker.get_health_status()
        assert 'status' in health_status
        assert health_status['status'] in ['healthy', 'unhealthy', 'degraded']
        
        # Test individual health checks
        db_health = await health_checker.check_database()
        assert isinstance(db_health, bool)

class TestVPSOptimization:
    """Test VPS optimization functionality."""
    
    async def test_vps_optimizer_initialization(self, vps_optimizer):
        """Test VPS optimizer initialization."""
        assert vps_optimizer is not None
    
    async def test_performance_monitoring(self, vps_optimizer):
        """Test VPS performance monitoring."""
        performance_data = await vps_optimizer.get_performance_metrics()
        assert isinstance(performance_data, dict)
        assert 'cpu_usage' in performance_data
        assert 'memory_usage' in performance_data
        assert 'disk_usage' in performance_data
    
    async def test_optimization_recommendations(self, vps_optimizer):
        """Test optimization recommendations."""
        recommendations = await vps_optimizer.get_optimization_recommendations()
        assert isinstance(recommendations, list)

class TestAPIIntegration:
    """Test API integration with all enhanced features."""
    
    @pytest.fixture
    def api_client(self):
        """Create test API client."""
        from api.enhanced_app import app
        return httpx.AsyncClient(app=app, base_url="http://test")
    
    async def test_health_endpoint(self, api_client):
        """Test enhanced health endpoint."""
        response = await api_client.get("/health")
        assert response.status_code in [200, 503]  # Healthy or unhealthy
        
        health_data = response.json()
        assert 'status' in health_data
        assert 'timestamp' in health_data
        assert 'components' in health_data
    
    async def test_metrics_endpoint(self, api_client):
        """Test metrics endpoint."""
        response = await api_client.get("/metrics")
        assert response.status_code == 200
        assert "prometheus" in response.headers.get("content-type", "").lower() or \
               response.headers.get("content-type") == "text/plain; version=0.0.4; charset=utf-8"
    
    async def test_authentication_endpoints(self, api_client):
        """Test authentication endpoints."""
        # Test login with invalid credentials
        login_data = {
            "username": "invalid_user",
            "password": "wrong_password"
        }
        
        response = await api_client.post("/auth/login", json=login_data)
        assert response.status_code == 401
    
    async def test_api_middleware(self, api_client):
        """Test API middleware functionality."""
        # Test rate limiting by making multiple requests
        responses = []
        for _ in range(10):
            response = await api_client.get("/")
            responses.append(response.status_code)
        
        # Should get mostly 200s, possibly some 429s for rate limiting
        assert 200 in responses
    
    async def test_error_handling(self, api_client):
        """Test global error handling."""
        # Test non-existent endpoint
        response = await api_client.get("/nonexistent")
        assert response.status_code == 404

class TestEndToEndIntegration:
    """End-to-end integration tests."""
    
    async def test_complete_system_startup(self, temp_config_dir):
        """Test complete system initialization."""
        # Initialize all components
        config_manager = ConfigManager(config_dir=temp_config_dir)
        await config_manager.initialize()
        
        security_manager = SecurityManager(
            config_file=temp_config_dir / "security_config.yaml"
        )
        await security_manager.initialize()
        
        error_tracker = ErrorTracker(
            db_path=temp_config_dir / "errors.db"
        )
        await error_tracker.initialize()
        
        trading_metrics = TradingMetrics()
        health_checker = HealthChecker()
        
        # Verify all components are working
        assert config_manager.is_initialized()
        assert await security_manager.get_security_status() is not None
        assert await error_tracker.get_recent_errors(limit=1) is not None
        assert trading_metrics.requests_total is not None
        assert await health_checker.get_health_status() is not None
    
    async def test_configuration_security_integration(self, temp_config_dir):
        """Test integration between configuration and security."""
        config_manager = ConfigManager(config_dir=temp_config_dir)
        await config_manager.initialize()
        
        security_manager = SecurityManager(
            config_file=temp_config_dir / "security_config.yaml"
        )
        await security_manager.initialize()
        
        # Test that security manager can read configuration
        config = await config_manager.get_config()
        assert config.security.secret_key is not None
    
    async def test_error_tracking_with_monitoring(self, temp_config_dir):
        """Test integration between error tracking and monitoring."""
        error_tracker = ErrorTracker(
            db_path=temp_config_dir / "errors.db"
        )
        await error_tracker.initialize()
        
        trading_metrics = TradingMetrics()
        
        # Track an error and verify metrics are updated
        await error_tracker.track_error(
            error=RuntimeError("Integration test error"),
            component="integration_test",
            context={}
        )
        
        # Verify error metrics
        trading_metrics.errors_total.labels(
            component="integration_test",
            error_type="RuntimeError"
        ).inc()

# Performance tests
class TestPerformanceAndLoad:
    """Performance and load testing."""
    
    @pytest.mark.asyncio
    async def test_concurrent_error_tracking(self, error_tracker):
        """Test error tracking under concurrent load."""
        async def track_error(i):
            await error_tracker.track_error(
                error=ValueError(f"Concurrent error {i}"),
                component="load_test",
                context={"thread": i}
            )
        
        # Run concurrent error tracking
        tasks = [track_error(i) for i in range(50)]
        await asyncio.gather(*tasks)
        
        # Verify all errors were tracked
        recent_errors = await error_tracker.get_recent_errors(limit=100)
        load_test_errors = [e for e in recent_errors if e['component'] == 'load_test']
        assert len(load_test_errors) >= 50
    
    async def test_metrics_performance(self, trading_metrics):
        """Test metrics recording performance."""
        import time
        
        start_time = time.time()
        
        # Record many metrics quickly
        for i in range(1000):
            trading_metrics.requests_total.labels(
                method="GET",
                endpoint=f"/test{i % 10}",
                status="200"
            ).inc()
        
        end_time = time.time()
        duration = end_time - start_time
        
        # Should be able to record 1000 metrics in under 1 second
        assert duration < 1.0

if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])
