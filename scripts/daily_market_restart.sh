#!/bin/bash

# Daily Market Restart Script
# Restarts broker-monitor at 9:05 AM IST and algosat-main at 9:12 AM IST
# Usage: daily_market_restart.sh [broker|main]
# Created: 2025-09-10

LOG_FILE="/opt/algosat/logs/market_schedule.log"
DATE=$(date '+%Y-%m-%d %H:%M:%S')
DAY_OF_WEEK=$(date '+%u')  # 1=Monday, 7=Sunday
ACTION=$1

# Only run on weekdays (1-5 = Monday to Friday)
if [ "$DAY_OF_WEEK" -ge 1 ] && [ "$DAY_OF_WEEK" -le 5 ]; then
    echo "[$DATE] Daily market restart - $ACTION (weekday $DAY_OF_WEEK)..." >> "$LOG_FILE"
    
    # Check if PM2 is running
    if ! command -v pm2 &> /dev/null; then
        echo "[$DATE] ERROR: PM2 command not found" >> "$LOG_FILE"
        exit 1
    fi

    if [ "$ACTION" = "broker" ]; then
        echo "[$DATE] Restarting broker-monitor at 9:05 AM IST..." >> "$LOG_FILE"
        cd /opt/algosat
        
        # Restart broker-monitor
        pm2 restart broker-monitor >> "$LOG_FILE" 2>&1
        
        # Wait and check status
        sleep 3
        if pm2 list | grep -q "broker-monitor.*online"; then
            echo "[$DATE] ✅ broker-monitor restarted successfully" >> "$LOG_FILE"
        else
            echo "[$DATE] ❌ Failed to restart broker-monitor" >> "$LOG_FILE"
            pm2 list | grep broker-monitor >> "$LOG_FILE" 2>&1
        fi
        
    elif [ "$ACTION" = "main" ]; then
        echo "[$DATE] Restarting algosat-main at 9:12 AM IST..." >> "$LOG_FILE"
        cd /opt/algosat
        
        # Restart algosat-main
        pm2 restart algosat-main >> "$LOG_FILE" 2>&1
        
        # Wait and check status
        sleep 5
        if pm2 list | grep -q "algosat-main.*online"; then
            echo "[$DATE] ✅ algosat-main restarted successfully" >> "$LOG_FILE"
        else
            echo "[$DATE] ❌ Failed to restart algosat-main" >> "$LOG_FILE"
            pm2 list | grep algosat-main >> "$LOG_FILE" 2>&1
        fi
        
    else
        echo "[$DATE] ERROR: Invalid action '$ACTION'. Use 'broker' or 'main'" >> "$LOG_FILE"
        exit 1
    fi
    
    echo "[$DATE] Daily market restart - $ACTION completed" >> "$LOG_FILE"
    echo "----------------------------------------" >> "$LOG_FILE"
    
else
    echo "[$DATE] Weekend detected (day $DAY_OF_WEEK), skipping daily market restart $ACTION" >> "$LOG_FILE"
fi
