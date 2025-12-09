#!/bin/bash

# Market Schedule Wrapper
# Only runs market start/stop on weekdays (Monday-Friday)
# Usage: market_schedule_wrapper.sh [start|stop]
# Created: 2025-07-25

LOG_FILE="/opt/algosat/logs/market_schedule.log"
DATE=$(date '+%Y-%m-%d %H:%M:%S')
DAY_OF_WEEK=$(date '+%u')  # 1=Monday, 7=Sunday
ACTION=$1

# Check if it's a weekday (1-5 = Monday to Friday)
if [ "$DAY_OF_WEEK" -ge 1 ] && [ "$DAY_OF_WEEK" -le 5 ]; then
    echo "[$DATE] Weekday detected (day $DAY_OF_WEEK), proceeding with $ACTION..." >> "$LOG_FILE"
    
    if [ "$ACTION" = "start" ]; then
        /opt/algosat/algosat/scripts/market_start.sh
    elif [ "$ACTION" = "stop" ]; then
        /opt/algosat/algosat/scripts/market_stop.sh
    else
        echo "[$DATE] ERROR: Invalid action '$ACTION'. Use 'start' or 'stop'" >> "$LOG_FILE"
        exit 1
    fi
else
    echo "[$DATE] Weekend detected (day $DAY_OF_WEEK), skipping market $ACTION" >> "$LOG_FILE"
fi
