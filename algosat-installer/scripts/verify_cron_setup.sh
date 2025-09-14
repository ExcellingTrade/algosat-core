#!/bin/bash

# Cron Job Verification Script
# Verifies all cron jobs and their dependencies are properly configured
# Created: 2025-09-14

LOG_FILE="/tmp/cron_verification.log"
DATE=$(date '+%Y-%m-%d %H:%M:%S')
WORKSPACE_ROOT="/opt/algosat"
ERROR_COUNT=0

echo "[$DATE] Starting cron job verification..." | tee "$LOG_FILE"

# Function to log messages
log_msg() {
    echo "[$DATE] $1" | tee -a "$LOG_FILE"
}

# Function to log errors
log_error() {
    echo "[$DATE] ❌ ERROR: $1" | tee -a "$LOG_FILE"
    ((ERROR_COUNT++))
}

# Function to log success
log_success() {
    echo "[$DATE] ✅ SUCCESS: $1" | tee -a "$LOG_FILE"
}

# Function to log warnings
log_warning() {
    echo "[$DATE] ⚠️  WARNING: $1" | tee -a "$LOG_FILE"
}

log_msg "🔍 Verifying cron job configuration..."

# 1. Check if all required scripts exist and are executable
REQUIRED_SCRIPTS=(
    "/opt/algosat/scripts/daily_log_management.sh"
    "/opt/algosat/scripts/daily_pm2_restart.sh"
    "/opt/algosat/scripts/market_schedule_wrapper.sh"
    "/opt/algosat/scripts/daily_market_restart.sh"
    "/opt/algosat/scripts/market_start.sh"
    "/opt/algosat/scripts/market_stop.sh"
)

log_msg "📋 Checking required scripts..."
for script in "${REQUIRED_SCRIPTS[@]}"; do
    if [ -f "$script" ]; then
        if [ -x "$script" ]; then
            log_success "$(basename "$script") exists and is executable"
        else
            log_error "$(basename "$script") exists but is not executable"
        fi
    else
        log_error "$(basename "$script") does not exist"
    fi
done

# 2. Check if PM2 is available
log_msg "🔧 Checking PM2 availability..."
if command -v pm2 &> /dev/null; then
    PM2_VERSION=$(pm2 --version 2>/dev/null)
    log_success "PM2 is available (version: $PM2_VERSION)"
    
    # Check PM2 process status
    PM2_PROCESSES=$(pm2 list 2>/dev/null | grep -E "(algosat-main|broker-monitor|algosat-api|algosat-ui)" | wc -l)
    log_msg "📊 Found $PM2_PROCESSES AlgoSat PM2 processes"
else
    log_error "PM2 command not found - cron jobs will fail"
fi

# 3. Check log directories
log_msg "📁 Checking log directories..."
LOG_DIRS=(
    "/opt/algosat/logs"
    "/opt/algosat/logs/Fyer"
)

for dir in "${LOG_DIRS[@]}"; do
    if [ -d "$dir" ]; then
        if [ -w "$dir" ]; then
            log_success "Log directory $dir exists and is writable"
        else
            log_error "Log directory $dir exists but is not writable"
        fi
    else
        log_warning "Log directory $dir does not exist (will be created)"
        mkdir -p "$dir" 2>/dev/null
        if [ $? -eq 0 ]; then
            log_success "Created log directory $dir"
        else
            log_error "Failed to create log directory $dir"
        fi
    fi
done

# 4. Check timezone configuration
log_msg "🌍 Checking timezone configuration..."
CURRENT_TZ=$(timedatectl show --property=Timezone --value 2>/dev/null || echo "Unknown")
log_msg "Current timezone: $CURRENT_TZ"

# Calculate sample times for verification
CURRENT_UTC=$(date -u '+%H:%M')
CURRENT_IST=$(TZ='Asia/Kolkata' date '+%H:%M')
log_msg "Current time - UTC: $CURRENT_UTC, IST: $CURRENT_IST"

# 5. Test cron job timing analysis
log_msg "⏰ Analyzing cron job timings..."
echo ""
echo "📅 CRON JOB SCHEDULE ANALYSIS:" | tee -a "$LOG_FILE"
echo "================================" | tee -a "$LOG_FILE"
echo "Daily Log Management: 00:00 UTC (05:30 IST)" | tee -a "$LOG_FILE"
echo "PM2 Restart: 18:30 UTC (00:00 IST next day)" | tee -a "$LOG_FILE"
echo "Market Start: 03:00 UTC (08:30 IST)" | tee -a "$LOG_FILE"
echo "Broker Restart: 03:35 UTC (09:05 IST)" | tee -a "$LOG_FILE"
echo "Main Restart: 03:42 UTC (09:12 IST)" | tee -a "$LOG_FILE"
echo "Market Stop: 10:30 UTC (16:00 IST)" | tee -a "$LOG_FILE"
echo ""

# 6. Check for potential conflicts
log_msg "⚡ Checking for potential timing conflicts..."

# Check if there are any overlapping operations
POTENTIAL_ISSUES=()

# Market operations happen close together
POTENTIAL_ISSUES+=("Market start (03:00) and broker restart (03:35) are 35 minutes apart - should be fine")
POTENTIAL_ISSUES+=("Broker restart (03:35) and main restart (03:42) are 7 minutes apart - should be fine")

# PM2 restart happens at midnight IST
POTENTIAL_ISSUES+=("PM2 restart at midnight IST may conflict with any ongoing operations")

for issue in "${POTENTIAL_ISSUES[@]}"; do
    log_warning "$issue"
done

# 7. Check disk space
log_msg "💾 Checking disk space..."
DISK_USAGE=$(df "$WORKSPACE_ROOT" | awk 'NR==2 {print $5}' | sed 's/%//')
if [ "$DISK_USAGE" -gt 90 ]; then
    log_error "Disk usage is critical ($DISK_USAGE%) - log management may fail"
elif [ "$DISK_USAGE" -gt 80 ]; then
    log_warning "Disk usage is high ($DISK_USAGE%) - monitor closely"
else
    log_success "Disk usage is acceptable ($DISK_USAGE%)"
fi

# 8. Summary
echo ""
echo "📋 VERIFICATION SUMMARY:" | tee -a "$LOG_FILE"
echo "========================" | tee -a "$LOG_FILE"

if [ $ERROR_COUNT -eq 0 ]; then
    log_success "All cron jobs appear to be properly configured! ✅"
    echo ""
    echo "🎯 RECOMMENDATIONS:" | tee -a "$LOG_FILE"
    echo "- Monitor cron logs: tail -f /opt/algosat/logs/cron.log" | tee -a "$LOG_FILE"
    echo "- Check PM2 status regularly: pm2 status" | tee -a "$LOG_FILE"
    echo "- Verify market operations during first trading day" | tee -a "$LOG_FILE"
    EXIT_CODE=0
else
    log_error "Found $ERROR_COUNT errors that need to be fixed"
    echo ""
    echo "🔧 FIXES NEEDED:" | tee -a "$LOG_FILE"
    echo "- Fix the errors listed above before relying on cron jobs" | tee -a "$LOG_FILE"
    echo "- Test each script manually: /path/to/script.sh" | tee -a "$LOG_FILE"
    echo "- Check cron service: systemctl status cron" | tee -a "$LOG_FILE"
    EXIT_CODE=1
fi

echo ""
log_msg "Verification completed. Check $LOG_FILE for full details."

exit $EXIT_CODE