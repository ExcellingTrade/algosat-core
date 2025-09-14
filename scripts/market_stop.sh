#!/bin/bash

# Market Stop Script
# Stops algosat-main at 4:00 PM IST (after market closes)
# Created: 2025-07-25

LOG_FILE="/opt/algosat/logs/market_schedule.log"
DATE=$(date '+%Y-%m-%d %H:%M:%S')

echo "[$DATE] Market stop script triggered..." >> "$LOG_FILE"

# Check if PM2 is running
if ! command -v pm2 &> /dev/null; then
    echo "[$DATE] ERROR: PM2 command not found" >> "$LOG_FILE"
    exit 1
fi

# Check if algosat-main is running
if pm2 list | grep -q "algosat-main.*online"; then
    # Stop algosat-main
    echo "[$DATE] Stopping algosat-main after market session..." >> "$LOG_FILE"
    pm2 stop algosat-main >> "$LOG_FILE" 2>&1
    
    # Wait a moment and check status
    sleep 3
    if pm2 list | grep -q "algosat-main.*stopped"; then
        echo "[$DATE] ✅ algosat-main stopped successfully" >> "$LOG_FILE"
    else
        echo "[$DATE] ❌ Failed to stop algosat-main cleanly" >> "$LOG_FILE"
        pm2 list >> "$LOG_FILE" 2>&1
    fi
else
    echo "[$DATE] algosat-main is already stopped" >> "$LOG_FILE"
fi

echo "[$DATE] Market stop script completed" >> "$LOG_FILE"
echo "----------------------------------------" >> "$LOG_FILE"
