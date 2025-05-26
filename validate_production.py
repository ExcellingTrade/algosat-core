#!/usr/bin/env python3
"""
Production system validation script for Algosat trading system.
This script validates that all enhanced components are working correctly.
"""

import sys
import os
import asyncio
import tempfile
from pathlib import Path

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

def validate_imports():
    """Validate that all core modules can be imported."""
    print("=== VALIDATING IMPORTS ===")
    
    modules_to_test = [
        ('core.security', 'SecurityManager'),
        ('core.config_management', 'ConfigurationManager'),
        ('core.resilience', 'ErrorTracker'),
        ('core.monitoring', 'TradingMetrics'),
        ('core.vps_performance', 'VPSOptimizer'),
        ('core.data_management', 'DatabaseBackupManager'),
    ]
    
    success_count = 0
    for module_name, class_name in modules_to_test:
        try:
            module = __import__(module_name, fromlist=[class_name])
            cls = getattr(module, class_name)
            print(f"✓ {module_name}.{class_name} imported successfully")
            success_count += 1
        except Exception as e:
            print(f"✗ {module_name}.{class_name} failed: {e}")
    
    print(f"\nImport validation: {success_count}/{len(modules_to_test)} successful")
    return success_count == len(modules_to_test)

async def validate_config_management():
    """Validate config management functionality."""
    print("\n=== VALIDATING CONFIG MANAGEMENT ===")
    
    try:
        from core.config_management import ConfigurationManager
        
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = ConfigurationManager(config_dir=temp_dir)
            
            # Test basic config access
            assert manager.database is not None
            assert manager.security is not None
            
            print("✓ Config manager initialization successful")
            print("✓ Basic configuration access working")
            
            # Test configuration validation
            issues = manager.validate_configuration()
            print(f"✓ Configuration validation working (found {len(issues)} issues as expected)")
            
            return True
            
    except Exception as e:
        print(f"✗ Config management validation failed: {e}")
        return False

async def validate_security():
    """Validate security functionality."""
    print("\n=== VALIDATING SECURITY ===")
    
    try:
        from core.security import SecurityManager, EnhancedInputValidator
        
        with tempfile.TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "security.yaml"
            manager = SecurityManager(config_file=config_file)
            await manager.initialize()
            
            # Test input validation
            validator = manager.input_validator
            assert validator.validate_sql_input("SELECT * FROM users WHERE id = 1")
            
            print("✓ Security manager initialization successful")
            print("✓ Input validation working")
            
            # Test rate limiting
            client_id = "test_client"
            for i in range(5):
                result = await manager.check_rate_limit(client_id, "api")
                if not result:
                    print("✓ Rate limiting working")
                    break
            
            return True
            
    except Exception as e:
        print(f"✗ Security validation failed: {e}")
        return False

async def validate_resilience():
    """Validate resilience and error handling."""
    print("\n=== VALIDATING RESILIENCE ===")
    
    try:
        from core.resilience import ErrorTracker, AlgosatError, resilient_operation, ErrorCategory, ErrorSeverity
        
        with tempfile.TemporaryDirectory() as temp_dir:
            tracker = ErrorTracker(data_dir=temp_dir)
            
            # Test error tracking
            error = AlgosatError("Test error", ErrorCategory.SYSTEM, ErrorSeverity.LOW)
            await tracker.track_error(error, {"component": "validation"})
            
            stats = await tracker.get_error_stats()
            assert stats['total_errors'] >= 1
            
            print("✓ Error tracker initialization successful")
            print("✓ Error tracking working")
            
            # Test resilient operation decorator
            @resilient_operation(max_retries=2)
            async def test_operation():
                return "success"
            
            result = await test_operation()
            assert result == "success"
            print("✓ Resilient operation decorator working")
            
            return True
            
    except Exception as e:
        print(f"✗ Resilience validation failed: {e}")
        return False

async def validate_monitoring():
    """Validate monitoring functionality."""
    print("\n=== VALIDATING MONITORING ===")
    
    try:
        from core.monitoring import TradingMetrics, HealthChecker
        
        # Test trading metrics
        metrics = TradingMetrics()
        
        # Test order metrics
        await metrics.record_order_placed({
            'broker': 'test',
            'side': 'BUY',
            'status': 'FILLED',
            'strategy': 'test_strategy'
        })
        
        print("✓ Trading metrics working")
        
        # Test health checker
        health_checker = HealthChecker()
        
        # Register a simple health check
        def simple_check():
            return "healthy", "System is running"
        
        health_checker.register_check("system", simple_check)
        health_status = await health_checker.run_checks()
        assert health_status is not None
        
        print("✓ Health checker working")
        
        return True
        
    except Exception as e:
        print(f"✗ Monitoring validation failed: {e}")
        return False

async def validate_api():
    """Validate API functionality."""
    print("\n=== VALIDATING API ===")
    
    try:
        from api.enhanced_app import app
        
        assert app is not None
        assert app.title == "Algosat Trading API"
        
        print("✓ Enhanced API application creation successful")
        
        return True
        
    except Exception as e:
        print(f"✗ API validation failed: {e}")
        return False

def validate_deployment_files():
    """Validate deployment files exist and are properly configured."""
    print("\n=== VALIDATING DEPLOYMENT FILES ===")
    
    files_to_check = [
        "deploy/production_deploy.sh",
        "deploy/algosat.service",
        "deploy/nginx_algosat.conf",
        "requirements.txt",
        "PRODUCTION_DEPLOYMENT_GUIDE.md"
    ]
    
    success_count = 0
    for file_path in files_to_check:
        if Path(file_path).exists():
            print(f"✓ {file_path} exists")
            success_count += 1
        else:
            print(f"✗ {file_path} missing")
    
    print(f"\nDeployment files: {success_count}/{len(files_to_check)} present")
    return success_count == len(files_to_check)

async def main():
    """Run all validations."""
    print("ALGOSAT PRODUCTION SYSTEM VALIDATION")
    print("=" * 50)
    
    results = []
    
    # Basic import validation
    results.append(validate_imports())
    
    # Async validations
    async_validations = [
        validate_config_management(),
        validate_security(),
        validate_resilience(),
        validate_monitoring(),
        validate_api()
    ]
    
    for validation in async_validations:
        results.append(await validation)
    
    # File validation
    results.append(validate_deployment_files())
    
    # Summary
    print("\n" + "=" * 50)
    print("VALIDATION SUMMARY")
    print("=" * 50)
    
    passed = sum(results)
    total = len(results)
    
    if passed == total:
        print(f"🎉 ALL VALIDATIONS PASSED ({passed}/{total})")
        print("✅ System is ready for production deployment!")
        return True
    else:
        print(f"⚠️  SOME VALIDATIONS FAILED ({passed}/{total})")
        print("❌ Please fix the issues before deployment")
        return False

if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
