#!/bin/bash

# ==============================================================================
# AlgoSat Deployment Validation Script
# ==============================================================================
# This script validates that the AlgoSat deployment is working correctly
# ==============================================================================

# Note: Removed 'set -e' to allow script to continue on individual check failures

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging function
log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')] $1${NC}"
}

error() {
    echo -e "${RED}[ERROR] $1${NC}"
}

warn() {
    echo -e "${YELLOW}[WARNING] $1${NC}"
}

info() {
    echo -e "${BLUE}[INFO] $1${NC}"
}

success() {
    echo -e "${GREEN}[SUCCESS] $1${NC}"
}

# Counters for final report
CHECKS_PASSED=0
CHECKS_FAILED=0
CHECKS_WARNING=0

check_result() {
    local exit_code=$1
    local message="$2"
    local severity="${3:-error}"
    
    if [[ $exit_code -eq 0 ]]; then
        success "$message"
        ((CHECKS_PASSED++))
        return 0
    else
        if [[ $severity == "warning" ]]; then
            warn "$message"
            ((CHECKS_WARNING++))
        else
            error "$message"
            ((CHECKS_FAILED++))
        fi
        return 1
    fi
}

echo "
🔍 ═══════════════════════════════════════════════════════
   AlgoSat Deployment Validation
   $(date +'%Y-%m-%d %H:%M:%S')
═══════════════════════════════════════════════════════
"

# ==============================================================================
# 1. Directory Structure Validation
# ==============================================================================

log "📁 Validating directory structure..."

# Check if AlgoSat directory exists
if [[ -d "/opt/algosat" ]]; then
    check_result 0 "✅ AlgoSat directory exists (/opt/algosat)"
else
    check_result 1 "❌ AlgoSat directory not found (/opt/algosat)"
    error "Cannot continue without AlgoSat directory. Exiting..."
    exit 1
fi

# Check if core directory exists
if [[ -d "/opt/algosat/algosat" ]]; then
    check_result 0 "✅ AlgoSat core directory exists"
else
    check_result 1 "❌ AlgoSat core directory not found"
fi

# Check if virtual environment exists
if [[ -d "/opt/algosat/.venv" ]]; then
    check_result 0 "✅ Python virtual environment exists"
else
    check_result 1 "❌ Virtual environment not found"
fi

# Check if UI directory exists
if [[ -d "/opt/algosat/algosat-ui" ]]; then
    check_result 0 "✅ UI directory exists"
else
    check_result 1 "❌ UI directory not found"
fi

# Check log directories
if [[ -d "/opt/algosat/logs" ]]; then
    check_result 0 "✅ Log directory exists"
    LOG_COUNT=$(find /opt/algosat/logs -name "*.log" | wc -l)
    info "   📊 Found $LOG_COUNT log files"
else
    check_result 1 "❌ Log directory not found" "warning"
fi

# ==============================================================================
# 2. Configuration Files Validation
# ==============================================================================

log "⚙️  Validating configuration files..."

# Check .env file
if [[ -f "/opt/algosat/algosat/.env" ]]; then
    check_result 0 "✅ .env file exists"
    
    # Check critical environment variables
    source /opt/algosat/algosat/.env 2>/dev/null || true
    if [[ -n "$DB_USER" && -n "$DB_PASSWORD" && -n "$DB_NAME" ]]; then
        check_result 0 "✅ Database configuration present in .env"
    else
        check_result 1 "❌ Database configuration missing in .env"
    fi
    
    if [[ -n "$ALGOSAT_MASTER_KEY" && -n "$JWT_SECRET" ]]; then
        check_result 0 "✅ Security configuration present in .env"
    else
        check_result 1 "❌ Security configuration missing in .env" "warning"
    fi
else
    check_result 1 "❌ .env file not found"
fi

# Check PM2 ecosystem config
if [[ -f "/opt/algosat/algosat/ecosystem.config.js" ]]; then
    check_result 0 "✅ PM2 ecosystem config exists"
else
    check_result 1 "❌ PM2 ecosystem config not found"
fi

# ==============================================================================
# 3. Database Validation
# ==============================================================================

log "🗄️  Validating database..."

# Check PostgreSQL service
if systemctl is-active --quiet postgresql; then
    check_result 0 "✅ PostgreSQL service is running"
else
    check_result 1 "❌ PostgreSQL service is not running"
fi

# Test database connection
if sudo -u postgres psql -c "SELECT 1;" algosat_db > /dev/null 2>&1; then
    check_result 0 "✅ Database connection successful"
    
    # Check table count
    TABLE_COUNT=$(sudo -u postgres psql -d algosat_db -tAc "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public';" 2>/dev/null || echo "0")
    if [[ "$TABLE_COUNT" -gt 0 ]]; then
        check_result 0 "✅ Database contains $TABLE_COUNT tables"
    else
        check_result 1 "❌ Database appears to be empty" "warning"
    fi
else
    check_result 1 "❌ Database connection failed"
fi

# ==============================================================================
# 4. Python Environment Validation
# ==============================================================================

log "🐍 Validating Python environment..."

# Check Python version in virtual environment
if [[ -d "/opt/algosat/.venv" ]]; then
    source /opt/algosat/.venv/bin/activate
    PYTHON_VERSION=$(python --version 2>&1)
    if echo "$PYTHON_VERSION" | grep -q "3.12"; then
        check_result 0 "✅ Python 3.12 environment active ($PYTHON_VERSION)"
    else
        check_result 1 "❌ Python 3.12 not found (found: $PYTHON_VERSION)" "warning"
    fi
    
    # Check key packages - Test in the correct working directory  
    cd /opt/algosat
    export PYTHONPATH="/opt/algosat/algosat:$PYTHONPATH"
    if python -c "import algosat" 2>/dev/null; then
        check_result 0 "✅ AlgoSat package importable"
    else
        check_result 1 "❌ AlgoSat package import failed (PYTHONPATH may need adjustment)" "warning"
    fi
    
    if python -c "import fastapi, uvicorn, sqlalchemy" 2>/dev/null; then
        check_result 0 "✅ Core dependencies available"
    else
        check_result 1 "❌ Core dependencies missing"
    fi
    
    # Return to original directory
    cd - >/dev/null
    deactivate 2>/dev/null || true
fi

# ==============================================================================
# 5. PM2 Process Validation
# ==============================================================================

log "🔄 Validating PM2 processes..."

# Check if PM2 is installed
if command -v pm2 &> /dev/null; then
    check_result 0 "✅ PM2 is installed"
    
    PM2_VERSION=$(pm2 --version 2>/dev/null || echo "unknown")
    info "   📊 PM2 version: $PM2_VERSION"
else
    check_result 1 "❌ PM2 is not installed"
    exit 1
fi

# Get PM2 status
PM2_STATUS=$(pm2 jlist 2>/dev/null || echo "[]")

# Check individual processes
EXPECTED_PROCESSES=("algosat-main" "algosat-api" "algosat-ui" "broker-monitor")
RUNNING_PROCESSES=0

for process in "${EXPECTED_PROCESSES[@]}"; do
    if echo "$PM2_STATUS" | grep -q "\"name\":\"$process\""; then
        # Check if process is online
        if echo "$PM2_STATUS" | grep -A 10 "\"name\":\"$process\"" | grep -q "\"status\":\"online\""; then
            check_result 0 "✅ $process is running"
            ((RUNNING_PROCESSES++))
        else
            check_result 1 "❌ $process is not online" "warning"
        fi
    else
        check_result 1 "❌ $process not found" "warning"
    fi
done

info "   📊 $RUNNING_PROCESSES out of ${#EXPECTED_PROCESSES[@]} processes running"

# ==============================================================================
# 6. Network Services Validation
# ==============================================================================

log "🌐 Validating network services..."

# Check if ports are listening
if netstat -tlnp 2>/dev/null | grep -q ":8001.*LISTEN"; then
    check_result 0 "✅ API port 8001 is listening"
else
    check_result 1 "❌ API port 8001 is not listening"
fi

if netstat -tlnp 2>/dev/null | grep -q ":3000.*LISTEN"; then
    check_result 0 "✅ UI port 3000 is listening"
else
    check_result 1 "❌ UI port 3000 is not listening"
fi

# Test API endpoint
log "🧪 Testing API endpoints..."
sleep 2

if curl -f http://localhost:8001/health > /dev/null 2>&1; then
    check_result 0 "✅ API health endpoint responding"
    
    # Get API response details
    API_RESPONSE=$(curl -s http://localhost:8001/health 2>/dev/null || echo "{}")
    if echo "$API_RESPONSE" | grep -q "healthy"; then
        check_result 0 "✅ API reports healthy status"
    else
        check_result 1 "❌ API health check failed" "warning"
    fi
else
    check_result 1 "❌ API health endpoint not responding"
fi

# Test UI endpoint
if curl -f http://localhost:3000 > /dev/null 2>&1; then
    check_result 0 "✅ UI endpoint responding"
else
    check_result 1 "❌ UI endpoint not responding"
fi

# ==============================================================================
# 7. Firewall Validation
# ==============================================================================

log "🔥 Validating firewall configuration..."

if command -v ufw &> /dev/null; then
    check_result 0 "✅ UFW firewall is installed"
    
    if ufw status | grep -q "Status: active"; then
        check_result 0 "✅ Firewall is active"
        
        # Check required ports
        REQUIRED_PORTS=("22" "3000" "8001")
        for port in "${REQUIRED_PORTS[@]}"; do
            if ufw status | grep -q "$port"; then
                check_result 0 "✅ Port $port is configured in firewall"
            else
                check_result 1 "❌ Port $port is not configured in firewall" "warning"
            fi
        done
    else
        check_result 1 "❌ Firewall is not active" "warning"
    fi
else
    check_result 1 "❌ UFW firewall is not installed" "warning"
fi

# ==============================================================================
# 8. Cron Jobs Validation
# ==============================================================================

log "📅 Validating cron jobs..."

# Check if cron service is running
if systemctl is-active --quiet cron; then
    check_result 0 "✅ Cron service is running"
    
    # Check for AlgoSat cron jobs
    CRON_JOBS=$(crontab -l 2>/dev/null | grep -c "algosat" || echo "0")
    if [[ "$CRON_JOBS" -gt 0 ]]; then
        check_result 0 "✅ Found $CRON_JOBS AlgoSat cron jobs"
    else
        check_result 1 "❌ No AlgoSat cron jobs found" "warning"
    fi
else
    check_result 1 "❌ Cron service is not running" "warning"
fi

# ==============================================================================
# 9. System Resources Validation
# ==============================================================================

log "📊 Validating system resources..."

# Check disk space
DISK_USAGE=$(df /opt/algosat 2>/dev/null | tail -1 | awk '{print $(NF-1)}' | sed 's/%//')
if [[ "$DISK_USAGE" -lt 90 ]]; then
    check_result 0 "✅ Disk usage is healthy ($DISK_USAGE%)"
else
    check_result 1 "❌ Disk usage is high ($DISK_USAGE%)" "warning"
fi

# Check memory usage
MEMORY_USAGE=$(free | grep Mem | awk '{printf("%.0f", ($3/$2) * 100.0)}')
if [[ "$MEMORY_USAGE" -lt 90 ]]; then
    check_result 0 "✅ Memory usage is healthy ($MEMORY_USAGE%)"
else
    check_result 1 "❌ Memory usage is high ($MEMORY_USAGE%)" "warning"
fi

# ==============================================================================
# Final Report
# ==============================================================================

echo ""
echo "═══════════════════════════════════════════════════════"
echo "📊 VALIDATION SUMMARY"
echo "═══════════════════════════════════════════════════════"

echo -e "${GREEN}✅ Passed: $CHECKS_PASSED${NC}"
if [[ $CHECKS_WARNING -gt 0 ]]; then
    echo -e "${YELLOW}⚠️  Warnings: $CHECKS_WARNING${NC}"
fi
if [[ $CHECKS_FAILED -gt 0 ]]; then
    echo -e "${RED}❌ Failed: $CHECKS_FAILED${NC}"
fi

echo ""
echo "📋 Current Service Status:"
pm2 status 2>/dev/null || echo "PM2 status unavailable"

echo ""
log "🎯 Access URLs:"
EXTERNAL_IP=$(hostname -I | cut -d' ' -f1 2>/dev/null || echo "localhost")
log "   🖥️  UI: http://$EXTERNAL_IP:3000"
log "   🔌 API: http://$EXTERNAL_IP:8001"
log "   💓 Health: http://$EXTERNAL_IP:8001/health"

echo ""
log "📋 Quick Management Commands:"
log "   pm2 status           - Check service status"
log "   pm2 logs             - View all logs"
log "   pm2 restart all      - Restart all services"
log "   pm2 stop all         - Stop all services"
log "   crontab -l           - View scheduled tasks"

echo ""
if [[ $CHECKS_FAILED -eq 0 ]]; then
    if [[ $CHECKS_WARNING -eq 0 ]]; then
        success "🎉 AlgoSat deployment is fully functional!"
        echo "═══════════════════════════════════════════════════════"
        exit 0
    else
        warn "⚠️  AlgoSat deployment is mostly functional with $CHECKS_WARNING warnings"
        echo "═══════════════════════════════════════════════════════"
        exit 0
    fi
else
    error "❌ AlgoSat deployment has $CHECKS_FAILED critical issues"
    echo "═══════════════════════════════════════════════════════"
    exit 1
fi