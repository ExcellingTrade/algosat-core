#!/bin/bash
# AlgoSat Cron Installation Script

set -e

echo "Installing AlgoSat cron jobs..."

# Verify scripts directory exists
if [ ! -d "/opt/algosat/algosat/scripts" ]; then
    echo "❌ Error: Scripts directory not found at /opt/algosat/algosat/scripts"
    echo "Please ensure AlgoSat is properly deployed first."
    exit 1
fi

# Make scripts executable
echo "Setting execute permissions on scripts..."
chmod +x /opt/algosat/algosat/scripts/*.sh

# Verify crontab file exists
if [ ! -f "algosat_crontab.txt" ]; then
    echo "❌ Error: algosat_crontab.txt not found in current directory"
    echo "Please run this script from the algosat-installer/scripts directory"
    exit 1
fi

# Install crontab for root user
echo "Installing crontab for root..."
crontab algosat_crontab.txt

# Install crontab for current user as well (if different from root)
if [ -n "$SUDO_USER" ] && [ "$SUDO_USER" != "root" ]; then
    sudo -u $SUDO_USER crontab algosat_crontab.txt 2>/dev/null || echo "Could not install user crontab for $SUDO_USER"
fi

echo "✅ Cron jobs installed successfully!"
echo ""
echo "Installed cron jobs:"
crontab -l | grep -v "^#" | grep -v "^$"
echo ""
echo "📋 Cron schedule summary:"
echo "  - Daily log management: Midnight (00:00)"
echo "  - PM2 process restart: 18:30 UTC (Midnight IST)"
echo "  - Market start: 03:00 UTC (8:30 AM IST) weekdays"
echo "  - Broker monitor restart: 03:35 UTC (9:05 AM IST) weekdays"
echo "  - Main service restart: 03:42 UTC (9:12 AM IST) weekdays"
echo "  - Market stop: 10:30 UTC (4:00 PM IST) weekdays"
echo ""
echo "📁 Script locations: /opt/algosat/algosat/scripts/"
echo "📄 Log file: /opt/algosat/logs/cron.log"

