"""
Basic integration tests for the enhanced Algosat trading system.
"""
import pytest
import asyncio
import tempfile
from pathlib import Path
import sys
import os

# Add the parent directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent))

def test_basic_imports():
    """Test that basic modules can be imported."""
    try:
        from core.security import SecurityManager
        assert SecurityManager is not None
        print("✓ SecurityManager imported successfully")
    except ImportError as e:
        pytest.fail(f"Failed to import SecurityManager: {e}")

def test_config_management_import():
    """Test config management import."""
    try:
        from core.config_management import ConfigManager
        assert ConfigManager is not None
        print("✓ ConfigManager imported successfully")
    except ImportError as e:
        pytest.fail(f"Failed to import ConfigManager: {e}")

def test_resilience_import():
    """Test resilience module import."""
    try:
        from core.resilience import ErrorTracker
        assert ErrorTracker is not None
        print("✓ ErrorTracker imported successfully")
    except ImportError as e:
        pytest.fail(f"Failed to import ErrorTracker: {e}")

@pytest.mark.asyncio
async def test_config_manager_basic():
    """Test basic config manager functionality."""
    try:
        from core.config_management import ConfigManager
        
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = ConfigManager(config_dir=Path(temp_dir))
            await manager.initialize()
            
            # Test config creation
            assert manager.config is not None
            print("✓ ConfigManager basic functionality works")
            
    except Exception as e:
        pytest.fail(f"ConfigManager basic test failed: {e}")

@pytest.mark.asyncio
async def test_security_manager_basic():
    """Test basic security manager functionality."""
    try:
        from core.security import SecurityManager
        
        with tempfile.TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "security.yaml"
            manager = SecurityManager(config_file=config_file)
            await manager.initialize()
            
            # Test basic validation
            validator = manager.input_validator
            assert validator is not None
            print("✓ SecurityManager basic functionality works")
            
    except Exception as e:
        pytest.fail(f"SecurityManager basic test failed: {e}")

@pytest.mark.asyncio
async def test_error_tracker_basic():
    """Test basic error tracker functionality."""
    try:
        from core.resilience import ErrorTracker, AlgosatError
        
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "errors.db"
            tracker = ErrorTracker(db_path=db_path)
            await tracker.initialize()
            
            # Test error tracking
            error = AlgosatError("Test error", "TEST_CODE")
            await tracker.track_error(error, {"component": "test"})
            
            stats = await tracker.get_error_stats()
            assert stats is not None
            print("✓ ErrorTracker basic functionality works")
            
    except Exception as e:
        pytest.fail(f"ErrorTracker basic test failed: {e}")

def test_monitoring_import():
    """Test monitoring module import."""
    try:
        from core.monitoring import TradingMetrics
        assert TradingMetrics is not None
        print("✓ TradingMetrics imported successfully")
    except ImportError as e:
        pytest.fail(f"Failed to import TradingMetrics: {e}")

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
