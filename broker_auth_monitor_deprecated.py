# DEPRECATED: This file has been moved and enhanced
# Please use: algosat.broker_monitor instead
# 
# This file provides comprehensive broker monitoring including:
# - Daily 6am IST authentication checks
# - Periodic balance monitoring  
# - Balance summary updates (moved from balance_summary_monitor.py)
# - Profile health checks
#
# PM2 Command: pm2 start algosat.broker_monitor --name "broker-monitor"

import sys
import warnings

warnings.warn(
    "broker_auth_monitor.py is deprecated. Use algosat.broker_monitor instead.",
    DeprecationWarning,
    stacklevel=2
)

print("⚠️  DEPRECATED: broker_auth_monitor.py has been replaced by broker_monitor.py")
print("🔄 Please update your PM2 configuration:")
print("   pm2 delete broker-auth-monitor  # if running")
print("   pm2 start algosat.broker_monitor --name 'broker-monitor'")
print()

# Import and run the new monitor for backward compatibility
try:
    from algosat.broker_monitor import main
    import asyncio
    
    if __name__ == "__main__":
        print("🔄 Running new broker_monitor for backward compatibility...")
        asyncio.run(main())
except ImportError as e:
    print(f"❌ Failed to import new broker_monitor: {e}")
    sys.exit(1)
