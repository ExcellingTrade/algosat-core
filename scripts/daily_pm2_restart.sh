#!/bin/bash

# Daily PM2 Management Script
# - Weekdays: Restarts all PM2 processes at midnight (for log rotation), then stops algosat-main (market closed)
# - Weekends: Stops all PM2 processes to save resources
# - Market scheduler handles algosat-main during market hours (8:30 AM - 4:00 PM IST)
# Created: 2025-07-24, Updated: 2025-09-11

LOG_FILE="/opt/algosat/logs/pm2_restart.log"
DATE=$(date '+%Y-%m-%d %H:%M:%S')
DAY_OF_WEEK=$(date '+%u')  # 1=Monday, 7=Sunday

echo "[$DATE] Starting daily PM2 restart (day $DAY_OF_WEEK)..." >> "$LOG_FILE"

# Check if PM2 is running
if ! command -v pm2 &> /dev/null; then
    echo "[$DATE] ERROR: PM2 command not found" >> "$LOG_FILE"
    exit 1
fi

# Get current PM2 status before restart
echo "[$DATE] PM2 status before restart:" >> "$LOG_FILE"
pm2 list >> "$LOG_FILE" 2>&1

# Check if it's weekend - different behavior for weekends vs weekdays
if [ "$DAY_OF_WEEK" -eq 6 ] || [ "$DAY_OF_WEEK" -eq 7 ]; then
    echo "[$DATE] Weekend detected (day $DAY_OF_WEEK), stopping all PM2 processes..." >> "$LOG_FILE"
    pm2 stop all >> "$LOG_FILE" 2>&1
    echo "[$DATE] All PM2 processes stopped for weekend" >> "$LOG_FILE"
else
    echo "[$DATE] Weekday detected (day $DAY_OF_WEEK), restarting all PM2 processes..." >> "$LOG_FILE"
    # Restart all PM2 processes on weekdays (for log rotation)
    pm2 restart all >> "$LOG_FILE" 2>&1
    
    # Wait a moment for processes to stabilize
    sleep 5
    
    # Get PM2 status after restart
    echo "[$DATE] PM2 status after restart:" >> "$LOG_FILE"
    pm2 list >> "$LOG_FILE" 2>&1
    
    # Stop algosat-main after restart (market is closed at midnight)
    echo "[$DATE] Stopping algosat-main after midnight restart (market is closed)..." >> "$LOG_FILE"
    if pm2 list | grep -q "algosat-main.*online"; then
        pm2 stop algosat-main >> "$LOG_FILE" 2>&1
        sleep 2
        
        # Verify algosat-main is stopped
        if pm2 list | grep -q "algosat-main.*stopped"; then
            echo "[$DATE] ✅ algosat-main stopped successfully after midnight restart" >> "$LOG_FILE"
        else
            echo "[$DATE] ❌ Failed to stop algosat-main after midnight restart" >> "$LOG_FILE"
            pm2 list >> "$LOG_FILE" 2>&1
        fi
    else
        echo "[$DATE] algosat-main was already stopped after restart" >> "$LOG_FILE"
    fi
fi

echo "[$DATE] Daily PM2 restart completed successfully" >> "$LOG_FILE"
echo "----------------------------------------" >> "$LOG_FILE"
