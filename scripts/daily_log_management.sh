#!/bin/bash

# Daily Log Management Script
# - Archives logs older than 7 days
# - Compresses old log files to save space
# - Rotates PM2 logs to prevent them from growing too large
# Created: 2025-09-14

LOG_FILE="/opt/algosat/logs/log_management.log"
DATE=$(date '+%Y-%m-%d %H:%M:%S')
WORKSPACE_ROOT="/opt/algosat"
LOG_DIR="$WORKSPACE_ROOT/logs"

echo "[$DATE] Starting daily log management..." >> "$LOG_FILE"

# Create log directory if it doesn't exist
mkdir -p "$LOG_DIR"

# Function to log with timestamp
log_msg() {
    echo "[$DATE] $1" >> "$LOG_FILE"
}

# 1. Archive old daily log directories (older than 7 days)
log_msg "Archiving old daily log directories..."
find "$LOG_DIR" -maxdepth 1 -type d -name "20*" -mtime +7 -exec rm -rf {} \; 2>/dev/null
if [ $? -eq 0 ]; then
    log_msg "Successfully archived old daily directories"
else
    log_msg "Error archiving old directories"
fi

# 2. Compress large log files (larger than 10MB)
log_msg "Compressing large log files..."
find "$LOG_DIR" -name "*.log" -size +10M ! -name "*.gz" -exec gzip {} \; 2>/dev/null
if [ $? -eq 0 ]; then
    log_msg "Successfully compressed large log files"
else
    log_msg "No large log files to compress or error occurred"
fi

# 3. Remove compressed logs older than 30 days
log_msg "Removing old compressed logs..."
find "$LOG_DIR" -name "*.gz" -mtime +30 -delete 2>/dev/null
if [ $? -eq 0 ]; then
    log_msg "Successfully removed old compressed logs"
else
    log_msg "No old compressed logs to remove or error occurred"
fi

# 4. Rotate PM2 logs if they are large (>50MB)
log_msg "Checking PM2 log sizes..."
for log_file in "$LOG_DIR"/pm2-*.log; do
    if [ -f "$log_file" ] && [ $(stat -f%z "$log_file" 2>/dev/null || stat -c%s "$log_file" 2>/dev/null) -gt 52428800 ]; then
        log_msg "Rotating large PM2 log: $(basename "$log_file")"
        mv "$log_file" "${log_file}.$(date +%Y%m%d)"
        touch "$log_file"
        # Send signal to PM2 to reopen log files
        pm2 reloadLogs 2>/dev/null
    fi
done

# 5. Check disk space and warn if low
DISK_USAGE=$(df "$WORKSPACE_ROOT" | awk 'NR==2 {print $5}' | sed 's/%//')
if [ "$DISK_USAGE" -gt 80 ]; then
    log_msg "WARNING: Disk usage is high ($DISK_USAGE%). Consider manual cleanup."
else
    log_msg "Disk usage is acceptable ($DISK_USAGE%)"
fi

# 6. Summary
LOG_COUNT=$(find "$LOG_DIR" -name "*.log" | wc -l)
COMPRESSED_COUNT=$(find "$LOG_DIR" -name "*.gz" | wc -l)
log_msg "Log management completed. Active logs: $LOG_COUNT, Compressed: $COMPRESSED_COUNT"

echo "[$DATE] Daily log management completed successfully" >> "$LOG_FILE"
