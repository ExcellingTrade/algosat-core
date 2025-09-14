#!/bin/bash

# Market Hours Schedule Verification
# Shows when the next market start/stop will occur

echo "=== Market Hours Schedule Verification ==="
echo "Current system time: $(date)"
echo "System timezone: UTC"
echo ""

echo "=== Cron Schedule ==="
echo "Market START: 3:00 AM UTC (8:30 AM IST) on weekdays"
echo "Market STOP:  10:30 AM UTC (4:00 PM IST) on weekdays"
echo ""

echo "=== Next Execution Times ==="
# Calculate next market start
TODAY=$(date +%u)  # 1=Monday, 7=Sunday
CURRENT_UTC_HOUR=$(date +%H)
CURRENT_UTC_MINUTE=$(date +%M)
CURRENT_UTC_TIME=$((CURRENT_UTC_HOUR * 60 + CURRENT_UTC_MINUTE))
MARKET_START_UTC_TIME=$((3 * 60))  # 3:00 AM UTC = 180 minutes
MARKET_STOP_UTC_TIME=$((10 * 60 + 30))  # 10:30 AM UTC = 630 minutes

# Check if today is a weekday (1-5 = Mon-Fri)
if [ "$TODAY" -ge 1 ] && [ "$TODAY" -le 5 ]; then
    # It's a weekday - check if market hasn't started yet today
    if [ "$CURRENT_UTC_TIME" -lt "$MARKET_START_UTC_TIME" ]; then
        # Market hasn't started today yet
        TODAY_DATE=$(date +%Y-%m-%d)
        TODAY_NAME=$(date +%A)
        echo "🚀 Market starts TODAY: $TODAY_NAME $TODAY_DATE 03:00:00 UTC (08:30:00 IST)"
        echo "🛑 Market stops TODAY: $TODAY_NAME $TODAY_DATE 10:30:00 UTC (16:00:00 IST)"
    elif [ "$CURRENT_UTC_TIME" -lt "$MARKET_STOP_UTC_TIME" ]; then
        # Market is currently running
        TODAY_DATE=$(date +%Y-%m-%d)
        TODAY_NAME=$(date +%A)
        echo "📈 Market is CURRENTLY RUNNING (started at 08:30 IST)"
        echo "🛑 Market stops TODAY: $TODAY_NAME $TODAY_DATE 10:30:00 UTC (16:00:00 IST)"
    else
        # Market has closed today, next is tomorrow (if weekday) or Monday
        if [ "$TODAY" -eq 5 ]; then
            # Friday -> next Monday
            NEXT_DATE=$(date -d "+3 days" +%Y-%m-%d)
            NEXT_NAME=$(date -d "+3 days" +%A)
        else
            # Other weekday -> tomorrow
            NEXT_DATE=$(date -d "+1 day" +%Y-%m-%d)
            NEXT_NAME=$(date -d "+1 day" +%A)
        fi
        echo "✅ Next Market START: $NEXT_NAME $NEXT_DATE 03:00:00 UTC (08:30:00 IST)"
        echo "✅ Next Market STOP: $NEXT_NAME $NEXT_DATE 10:30:00 UTC (16:00:00 IST)"
    fi
else
    # Weekend - find next Monday
    if [ "$TODAY" -eq 6 ]; then
        DAYS_TO_MONDAY=2  # Saturday -> Monday
    else
        DAYS_TO_MONDAY=1  # Sunday -> Monday
    fi
    NEXT_DATE=$(date -d "+$DAYS_TO_MONDAY days" +%Y-%m-%d)
    echo "⏭️ Weekend - Next Market START: Monday $NEXT_DATE 03:00:00 UTC (08:30:00 IST)"
fi

echo ""
echo "=== Current Status ==="
pm2 list | grep algosat-main | awk '{print "algosat-main status: " $10}'

echo ""
echo "=== Log Files ==="
echo "Market schedule logs: /opt/algosat/logs/market_schedule.log"
echo "Cron logs: /opt/algosat/logs/cron.log"
