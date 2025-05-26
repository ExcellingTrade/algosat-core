#!/usr/bin/env python3
"""
Simple validation script to test core components
"""
import sys
from pathlib import Path

print("=== ALGOSAT COMPONENT VALIDATION ===")

# Test basic imports
print("\n1. Testing core imports...")
try:
    from core.security import SecurityManager
    print("✓ SecurityManager imported")
except Exception as e:
    print(f"✗ SecurityManager failed: {e}")

try:
    from core.config_management import ConfigurationManager  
    print("✓ ConfigurationManager imported")
except Exception as e:
    print(f"✗ ConfigurationManager failed: {e}")

try:
    from core.resilience import ErrorTracker
    print("✓ ErrorTracker imported")
except Exception as e:
    print(f"✗ ErrorTracker failed: {e}")

try:
    from core.monitoring import TradingMetrics
    print("✓ TradingMetrics imported")
except Exception as e:
    print(f"✗ TradingMetrics failed: {e}")

# Test basic instantiation
print("\n2. Testing basic instantiation...")
try:
    import tempfile
    with tempfile.TemporaryDirectory() as temp_dir:
        config_manager = ConfigurationManager(config_dir=temp_dir)
        print("✓ ConfigurationManager instantiated")
except Exception as e:
    print(f"✗ ConfigurationManager instantiation failed: {e}")

try:
    metrics = TradingMetrics()
    print("✓ TradingMetrics instantiated")
except Exception as e:
    print(f"✗ TradingMetrics instantiation failed: {e}")

# Test deployment files
print("\n3. Testing deployment files...")
files_to_check = [
    "deploy/production_deploy.sh",
    "deploy/algosat.service", 
    "deploy/nginx_algosat.conf",
    "requirements.txt"
]

for file_path in files_to_check:
    if Path(file_path).exists():
        print(f"✓ {file_path} exists")
    else:
        print(f"✗ {file_path} missing")

print("\n=== VALIDATION COMPLETE ===")
