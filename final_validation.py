#!/usr/bin/env python3
"""
Final production readiness validation for Algosat trading system.
This script performs comprehensive checks to ensure the system is ready for deployment.
"""
import os
import sys
import subprocess
import asyncio
import tempfile
from pathlib import Path
from datetime import datetime

def print_header(title):
    """Print a formatted header."""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")

def print_section(title):
    """Print a formatted section header."""
    print(f"\n{'─' * 50}")
    print(f"  {title}")
    print(f"{'─' * 50}")

def check_dependencies():
    """Check if all required dependencies are installed."""
    print_section("DEPENDENCY CHECK")
    
    required_packages = [
        'fastapi', 'uvicorn', 'sqlalchemy', 'pydantic', 'pandas',
        'numpy', 'cryptography', 'bcrypt', 'PyJWT', 'python-dotenv',
        'PyYAML', 'requests', 'httpx', 'prometheus_client', 'structlog',
        'psutil', 'aiofiles', 'pytest'
    ]
    
    missing_packages = []
    
    for package in required_packages:
        try:
            __import__(package.replace('-', '_'))
            print(f"✓ {package}")
        except ImportError:
            print(f"✗ {package} - MISSING")
            missing_packages.append(package)
    
    if missing_packages:
        print(f"\n❌ Missing packages: {', '.join(missing_packages)}")
        return False
    else:
        print(f"\n✅ All {len(required_packages)} required packages are installed")
        return True

def check_system_requirements():
    """Check system requirements for VPS deployment."""
    print_section("SYSTEM REQUIREMENTS CHECK")
    
    try:
        import psutil
        
        # Check memory
        memory = psutil.virtual_memory()
        memory_gb = memory.total / (1024**3)
        print(f"RAM: {memory_gb:.1f} GB {'✓' if memory_gb >= 1 else '✗ (minimum 1GB required)'}")
        
        # Check disk space
        disk = psutil.disk_usage('/')
        disk_gb = disk.free / (1024**3)
        print(f"Free disk space: {disk_gb:.1f} GB {'✓' if disk_gb >= 5 else '✗ (minimum 5GB required)'}")
        
        # Check CPU
        cpu_count = psutil.cpu_count()
        print(f"CPU cores: {cpu_count} {'✓' if cpu_count >= 1 else '✗ (minimum 1 core required)'}")
        
        return memory_gb >= 1 and disk_gb >= 5 and cpu_count >= 1
        
    except Exception as e:
        print(f"✗ System check failed: {e}")
        return False

def check_file_structure():
    """Check that all required files and directories exist."""
    print_section("FILE STRUCTURE CHECK")
    
    required_files = [
        "main.py",
        "requirements.txt",
        "deploy/production_deploy.sh",
        "deploy/algosat.service",
        "deploy/nginx_algosat.conf",
        "core/security.py",
        "core/config_management.py",
        "core/resilience.py",
        "core/monitoring.py",
        "core/vps_performance.py",
        "core/data_management.py",
        "api/enhanced_app.py",
        "dashboard/monitoring_dashboard.py",
        "PRODUCTION_DEPLOYMENT_GUIDE.md"
    ]
    
    required_dirs = [
        "core",
        "api", 
        "deploy",
        "dashboard",
        "Files/backups",
        "Files/logs",
        "Files/cache"
    ]
    
    missing_files = []
    missing_dirs = []
    
    for file_path in required_files:
        if Path(file_path).exists():
            print(f"✓ {file_path}")
        else:
            print(f"✗ {file_path} - MISSING")
            missing_files.append(file_path)
    
    for dir_path in required_dirs:
        if Path(dir_path).exists() and Path(dir_path).is_dir():
            print(f"✓ {dir_path}/")
        else:
            print(f"✗ {dir_path}/ - MISSING")
            missing_dirs.append(dir_path)
    
    success = len(missing_files) == 0 and len(missing_dirs) == 0
    if success:
        print(f"\n✅ All required files and directories present")
    else:
        print(f"\n❌ Missing files: {missing_files}")
        print(f"❌ Missing directories: {missing_dirs}")
    
    return success

def check_configuration():
    """Check if production configuration is properly set up."""
    print_section("CONFIGURATION CHECK")
    
    config_files = [
        "/opt/algosat/config/.env"
    ]
    
    all_present = True
    for config_file in config_files:
        if Path(config_file).exists():
            print(f"✓ {config_file}")
        else:
            print(f"✗ {config_file} - Run setup_production_config.sh first")
            all_present = False
    
    # Check environment variables
    required_env_vars = [
        "ALGOSAT_MASTER_KEY",
        "JWT_SECRET",
        "DB_PASSWORD"
    ]
    
    env_file = Path("/opt/algosat/config/.env")
    if env_file.exists():
        with open(env_file) as f:
            env_content = f.read()
            
        for var in required_env_vars:
            if var in env_content and f"{var}=" in env_content:
                print(f"✓ {var} configured")
            else:
                print(f"✗ {var} not configured")
                all_present = False
    
    if all_present:
        print(f"\n✅ Configuration setup complete")
    else:
        print(f"\n❌ Configuration incomplete - run setup_production_config.sh")
    
    return all_present

async def check_core_components():
    """Test core component functionality."""
    print_section("CORE COMPONENTS CHECK")
    
    components_status = {}
    
    # Test SecurityManager
    try:
        from core.security import SecurityManager
        with tempfile.TemporaryDirectory() as temp_dir:
            security_manager = SecurityManager(data_dir=temp_dir)
            await security_manager.initialize()
        print("✓ SecurityManager - functional")
        components_status['security'] = True
    except Exception as e:
        print(f"✗ SecurityManager - {e}")
        components_status['security'] = False
    
    # Test ConfigurationManager
    try:
        from core.config_management import ConfigurationManager
        with tempfile.TemporaryDirectory() as temp_dir:
            config_manager = ConfigurationManager(config_dir=temp_dir)
        print("✓ ConfigurationManager - functional")
        components_status['config'] = True
    except Exception as e:
        print(f"✗ ConfigurationManager - {e}")
        components_status['config'] = False
    
    # Test ErrorTracker
    try:
        from core.resilience import ErrorTracker
        with tempfile.TemporaryDirectory() as temp_dir:
            error_tracker = ErrorTracker(data_dir=temp_dir)
        print("✓ ErrorTracker - functional")
        components_status['resilience'] = True
    except Exception as e:
        print(f"✗ ErrorTracker - {e}")
        components_status['resilience'] = False
    
    # Test TradingMetrics
    try:
        from core.monitoring import TradingMetrics
        metrics = TradingMetrics()
        print("✓ TradingMetrics - functional")
        components_status['monitoring'] = True
    except Exception as e:
        print(f"✗ TradingMetrics - {e}")
        components_status['monitoring'] = False
    
    # Test VPSOptimizer
    try:
        from core.vps_performance import VPSOptimizer
        optimizer = VPSOptimizer()
        print("✓ VPSOptimizer - functional")
        components_status['vps'] = True
    except Exception as e:
        print(f"✗ VPSOptimizer - {e}")
        components_status['vps'] = False
    
    # Test API
    try:
        from api.enhanced_app import app
        assert app.title == "Algosat Trading API"
        print("✓ Enhanced API - functional")
        components_status['api'] = True
    except Exception as e:
        print(f"✗ Enhanced API - {e}")
        components_status['api'] = False
    
    working_components = sum(components_status.values())
    total_components = len(components_status)
    
    if working_components == total_components:
        print(f"\n✅ All {total_components} core components functional")
        return True
    else:
        print(f"\n❌ {working_components}/{total_components} components working")
        return False

def check_deployment_readiness():
    """Check if deployment scripts are ready."""
    print_section("DEPLOYMENT READINESS CHECK")
    
    # Check if deployment script is executable
    deploy_script = Path("deploy/production_deploy.sh")
    if deploy_script.exists() and os.access(deploy_script, os.X_OK):
        print("✓ Deployment script executable")
    else:
        print("✗ Deployment script not executable")
        return False
    
    # Check systemd service file
    service_file = Path("deploy/algosat.service")
    if service_file.exists():
        print("✓ Systemd service file present")
    else:
        print("✗ Systemd service file missing")
        return False
    
    # Check nginx configuration
    nginx_config = Path("deploy/nginx_algosat.conf")
    if nginx_config.exists():
        print("✓ Nginx configuration present")
    else:
        print("✗ Nginx configuration missing")
        return False
    
    print("\n✅ Deployment files ready")
    return True

def generate_deployment_summary():
    """Generate deployment summary and next steps."""
    print_header("DEPLOYMENT SUMMARY")
    
    print("""
🚀 ALGOSAT TRADING SYSTEM - PRODUCTION DEPLOYMENT
================================================

Your Algosat trading system has been successfully enhanced with:

✅ SECURITY ENHANCEMENTS:
   • Advanced input validation and sanitization
   • JWT-based authentication with configurable expiry
   • Rate limiting and IP blocking capabilities
   • Comprehensive security monitoring and alerting
   • File integrity checking and process monitoring

✅ RESILIENCE & ERROR HANDLING:
   • Structured error tracking with SQLite database
   • Circuit breakers for fault tolerance
   • Automatic retry mechanisms with exponential backoff
   • Error pattern recognition and analytics
   • Recovery action tracking and success rate monitoring

✅ CONFIGURATION MANAGEMENT:
   • Centralized configuration with environment support
   • Encrypted credential storage for sensitive data
   • YAML-based configuration files with validation
   • Hot configuration reloading capabilities

✅ ENHANCED MONITORING:
   • Prometheus metrics integration
   • Real-time health checks and system monitoring
   • Performance metrics and alerting
   • Web-based monitoring dashboard
   • Structured logging with context

✅ VPS OPTIMIZATION:
   • Memory and CPU usage optimization
   • Automated backup systems
   • Log rotation and cleanup
   • Resource monitoring and alerting

✅ PRODUCTION-GRADE API:
   • FastAPI with comprehensive middleware
   • Security validation and rate limiting
   • Error tracking and metrics collection
   • Structured request/response logging

✅ DEPLOYMENT AUTOMATION:
   • Complete deployment script for VPS
   • Systemd service configuration
   • Nginx reverse proxy with security headers
   • SSL/TLS setup automation
   • Database migration support

NEXT STEPS FOR PRODUCTION DEPLOYMENT:
====================================

1. CONFIGURATION SETUP:
   ./setup_production_config.sh

2. UPDATE BROKER CREDENTIALS:
   Edit /opt/algosat/config/brokers.yaml

3. RUN DEPLOYMENT:
   sudo ./deploy/production_deploy.sh

4. VERIFY SERVICES:
   sudo systemctl status algosat
   sudo systemctl status nginx

5. ACCESS MONITORING:
   https://your-domain.com/dashboard/

6. CHECK LOGS:
   sudo journalctl -u algosat -f

SECURITY RECOMMENDATIONS:
========================
• Change default passwords and API keys
• Configure SSL certificates for production
• Set up regular automated backups
• Monitor system logs and alerts
• Implement IP whitelisting if needed
• Regular security updates and patches

📧 For support and documentation, refer to:
   PRODUCTION_DEPLOYMENT_GUIDE.md
""")

async def main():
    """Run all validation checks."""
    print_header("ALGOSAT PRODUCTION READINESS VALIDATION")
    print(f"Validation started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    results = {}
    
    # Run all checks
    results['dependencies'] = check_dependencies()
    results['system'] = check_system_requirements()
    results['files'] = check_file_structure()
    results['config'] = check_configuration()
    results['components'] = await check_core_components()
    results['deployment'] = check_deployment_readiness()
    
    # Calculate overall status
    passed_checks = sum(results.values())
    total_checks = len(results)
    
    print_header("VALIDATION RESULTS")
    
    for check_name, passed in results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{check_name.upper():20} {status}")
    
    print(f"\nOVERALL RESULT: {passed_checks}/{total_checks} checks passed")
    
    if passed_checks == total_checks:
        print("\n🎉 SYSTEM IS READY FOR PRODUCTION DEPLOYMENT! 🎉")
        generate_deployment_summary()
        return True
    else:
        print(f"\n⚠️  SYSTEM NOT READY - {total_checks - passed_checks} issues need to be resolved")
        print("\nPlease fix the failed checks before deploying to production.")
        return False

if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
