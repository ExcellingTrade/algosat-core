#!/bin/bash

# Market Start Script
# Starts algosat-main at 8:30 AM IST (30 minutes before market opens)
# Created: 2025-07-25

LOG_FILE="/opt/algosat/logs/market_schedule.log"
DATE=$(date '+%Y-%m-%d %H:%M:%S')

echo "[$DATE] Market start script triggered..." >> "$LOG_FILE"

# Check if PM2 is running
if ! command -v pm2 &> /dev/null; then
    echo "[$DATE] ERROR: PM2 command not found" >> "$LOG_FILE"
    exit 1
fi

# Check if algosat-main is already running
if pm2 list | grep -q "algosat-main.*online"; then
    echo "[$DATE] algosat-main is already running" >> "$LOG_FILE"
else
    # Start algosat-main
    echo "[$DATE] Starting algosat-main for market session..." >> "$LOG_FILE"
    cd /opt/algosat/algosat
    pm2 start ecosystem.config.js --only algosat-main >> "$LOG_FILE" 2>&1
    
    # Wait a moment and check status
    sleep 3
    if pm2 list | grep -q "algosat-main.*online"; then
        echo "[$DATE] ✅ algosat-main started successfully" >> "$LOG_FILE"
    else
        echo "[$DATE] ❌ Failed to start algosat-main" >> "$LOG_FILE"
        pm2 list >> "$LOG_FILE" 2>&1
    fi
fi

echo "[$DATE] Market start script completed" >> "$LOG_FILE"
echo "----------------------------------------" >> "$LOG_FILE"
