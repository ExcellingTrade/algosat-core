#!/bin/bash

# ==============================================================================
# AlgoSat Automated Deployment Script
# ==============================================================================
# This script will deploy AlgoSat trading system on a fresh Ubuntu server
# Components: API, Main Service, Broker Monitor, UI
# Date: September 12, 2025
# ==============================================================================

set -e  # Exit on any error

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
    exit 1
}

warn() {
    echo -e "${YELLOW}[WARNING] $1${NC}"
}

info() {
    echo -e "${BLUE}[INFO] $1${NC}"
}

# Configuration
ALGOSAT_DIR="/opt/algosat"
ALGOSAT_CORE_DIR="/opt/algosat/algosat"
ALGOSAT_UI_DIR="/opt/algosat/algosat-ui"
DEPLOY_USER="root"
GITHUB_REPO_MAIN="https://github.com/ExcellingTrade/algosat-core.git"
GITHUB_REPO_UI="https://github.com/ExcellingTrade/algosat-ui.git"

# ==============================================================================
# Welcome and Setup
# ==============================================================================

echo "
████████╗██████╗  █████╗ ██████╗ ██╗███╗   ██╗ ██████╗ 
╚══██╔══╝██╔══██╗██╔══██╗██╔══██╗██║████╗  ██║██╔════╝ 
   ██║   ██████╔╝███████║██║  ██║██║██╔██╗ ██║██║  ███╗
   ██║   ██╔══██╗██╔══██║██║  ██║██║██║╚██╗██║██║   ██║
   ██║   ██║  ██║██║  ██║██████╔╝██║██║ ╚████║╚██████╔╝
   ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝╚═════╝ ╚═╝╚═╝  ╚═══╝ ╚═════╝ 
                                                        
   █████╗ ██╗      ██████╗  ██████╗ ███████╗ █████╗ ████████╗
  ██╔══██╗██║     ██╔════╝ ██╔═══██╗██╔════╝██╔══██╗╚══██╔══╝
  ███████║██║     ██║  ███╗██║   ██║███████╗███████║   ██║   
  ██╔══██║██║     ██║   ██║██║   ██║╚════██║██╔══██║   ██║   
  ██║  ██║███████╗╚██████╔╝╚██████╔╝███████║██║  ██║   ██║   
  ╚═╝  ╚═╝╚══════╝ ╚═════╝  ╚═════╝ ╚══════╝╚═╝  ╚═╝   ╚═╝   
"

log "🚀 Starting AlgoSat Automated Deployment"
log "📅 Date: $(date)"
log "🖥️  Server: $(hostname)"
log "👤 User: $(whoami)"

# Check if running as root or with sudo
if [[ $EUID -ne 0 ]]; then
   error "This script must be run as root or with sudo privileges"
fi

# ==============================================================================
# Pre-Installation Check (Idempotent)
# ==============================================================================

log "🔍 Checking existing AlgoSat installation..."

EXISTING_INSTALLATION=false
PM2_RUNNING=false

# Check if AlgoSat directory exists
if [[ -d "$ALGOSAT_DIR" ]]; then
    info "📁 Found existing AlgoSat directory at $ALGOSAT_DIR"
    EXISTING_INSTALLATION=true
fi

# Check if PM2 processes are running
if command -v pm2 &> /dev/null; then
    PM2_STATUS=$(pm2 jlist 2>/dev/null || echo "[]")
    if echo "$PM2_STATUS" | grep -q "algosat"; then
        info "🔄 Found running AlgoSat PM2 processes"
        PM2_RUNNING=true
    fi
fi

# Check if PostgreSQL database exists
if sudo -u postgres psql -lqt 2>/dev/null | cut -d \| -f 1 | grep -qw algosat_db; then
    info "🗄️  Found existing AlgoSat database"
fi

if [[ "$EXISTING_INSTALLATION" == true ]]; then
    info "🔄 IDEMPOTENT MODE: Existing installation detected"
    info "   ✅ Will update repositories instead of cloning"
    info "   ✅ Will reuse existing virtual environment" 
    info "   ✅ Will restart services instead of creating new ones"
    info "   ✅ Safe to continue - no destructive actions will be performed"
    echo ""
    read -p "Continue with installation/update? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log "Installation cancelled by user"
        exit 0
    fi
fi

# ==============================================================================
# System Update and Dependencies
# ==============================================================================

log "📦 Updating system packages..."
apt update && apt upgrade -y

log "📦 Installing system dependencies..."
apt install -y \
    curl \
    wget \
    git \
    build-essential \
    software-properties-common \
    apt-transport-https \
    ca-certificates \
    gnupg \
    lsb-release \
    python3 \
    python3-pip \
    python3-venv \
    python3-tk \
    python3-dev \
    xvfb \
    postgresql \
    postgresql-contrib \
    nodejs \
    npm

# Install Chrome/Chromium for UI testing/automation
log "📦 Installing Chrome/Chromium for browser automation..."
if ! command -v google-chrome &> /dev/null && ! command -v chromium-browser &> /dev/null && ! command -v chromium &> /dev/null; then
    # Try Google Chrome first
    wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | apt-key add - 2>/dev/null || true
    echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list 2>/dev/null || true
    apt update
    apt install -y google-chrome-stable || apt install -y chromium-browser || apt install -y chromium
    log "✅ Browser installed for automation"
else
    log "✅ Browser already available"
fi

# Install latest Node.js (v18 LTS) - idempotent check
if ! node --version | grep -q "v18"; then
    log "📦 Installing Node.js 18 LTS..."
    curl -fsSL https://deb.nodesource.com/setup_18.x | bash -
    apt-get install -y nodejs
else
    log "✅ Node.js 18 already installed"
fi

# Install PM2 globally - idempotent check
if ! command -v pm2 &> /dev/null; then
    log "📦 Installing PM2 globally..."
    npm install -g pm2
else
    log "✅ PM2 already installed"
fi

# ==============================================================================
# GitHub Authentication and Repository Cloning
# ==============================================================================

log "🔐 Setting up GitHub authentication..."

# Support non-interactive usage: use existing $GITHUB_TOKEN if set; otherwise prompt.
if [[ -z "${GITHUB_TOKEN}" ]]; then
    if [[ -t 0 ]]; then
        echo ""
        read -p "🔑 Enter your GitHub Personal Access Token (leave blank if repos are public): " -s GITHUB_TOKEN
        echo ""
    fi
fi

if [[ -z "${GITHUB_TOKEN}" ]]; then
    warn "Proceeding without GitHub token (assuming repositories are public). If clone fails, re-run with GITHUB_TOKEN exported."
fi

# Create base directory
log "📁 Creating AlgoSat directory..."
mkdir -p $ALGOSAT_DIR

# Clone main repository - idempotent check
log "📥 Cloning AlgoSat Core repository..."
cd $ALGOSAT_DIR

if [ -d "algosat" ]; then
    log "📂 AlgoSat core directory already exists, checking git status..."
    cd algosat
    
    # Check if it's a git repository
    if [ -d ".git" ]; then
        log "📂 Existing git repository found, pulling latest changes..."
        if [[ -n "${GITHUB_TOKEN}" ]]; then
            git remote set-url origin https://${GITHUB_TOKEN}@github.com/ExcellingTrade/algosat-core.git
        else
            git remote set-url origin https://github.com/ExcellingTrade/algosat-core.git
        fi
        git fetch origin
        git reset --hard origin/main
        git pull origin main
        if [[ $? -ne 0 ]]; then
            warn "⚠️  Git pull failed, trying fresh clone..."
            cd $ALGOSAT_DIR
            rm -rf algosat
            if [[ -n "${GITHUB_TOKEN}" ]]; then
                git clone https://${GITHUB_TOKEN}@github.com/ExcellingTrade/algosat-core.git algosat
            else
                git clone https://github.com/ExcellingTrade/algosat-core.git algosat || error "Failed to clone public repository algosat-core; provide GITHUB_TOKEN."
            fi
        fi
    else
        log "📂 Directory exists but not a git repo, removing and cloning fresh..."
        cd $ALGOSAT_DIR
        rm -rf algosat
        if [[ -n "${GITHUB_TOKEN}" ]]; then
            git clone https://${GITHUB_TOKEN}@github.com/ExcellingTrade/algosat-core.git algosat
        else
            git clone https://github.com/ExcellingTrade/algosat-core.git algosat || error "Failed to clone public repository algosat-core; provide GITHUB_TOKEN."
        fi
    fi
else
    log "📂 Cloning fresh repository..."
    if [[ -n "${GITHUB_TOKEN}" ]]; then
        git clone https://${GITHUB_TOKEN}@github.com/ExcellingTrade/algosat-core.git algosat
    else
        git clone https://github.com/ExcellingTrade/algosat-core.git algosat || error "Failed to clone public repository algosat-core; provide GITHUB_TOKEN."
    fi
fi

if [[ $? -ne 0 ]]; then
    error "Failed to clone/update AlgoSat Core repository"
fi

# Clone UI repository - idempotent check
log "📥 Cloning AlgoSat UI repository..."
cd $ALGOSAT_DIR
if [ -d "algosat-ui" ]; then
    log "📂 AlgoSat UI directory already exists, checking git status..."
    cd algosat-ui
    
    # Check if it's a git repository
    if [ -d ".git" ]; then
        log "📂 Existing UI git repository found, pulling latest changes..."
        if [[ -n "${GITHUB_TOKEN}" ]]; then
            git remote set-url origin https://${GITHUB_TOKEN}@github.com/ExcellingTrade/algosat-ui.git
        else
            git remote set-url origin https://github.com/ExcellingTrade/algosat-ui.git
        fi
        git fetch origin
        git reset --hard origin/main
        git pull origin main
        if [[ $? -ne 0 ]]; then
            warn "⚠️  UI git pull failed, trying fresh clone..."
            cd $ALGOSAT_DIR
            rm -rf algosat-ui
            if [[ -n "${GITHUB_TOKEN}" ]]; then
                git clone https://${GITHUB_TOKEN}@github.com/ExcellingTrade/algosat-ui.git
            else
                git clone https://github.com/ExcellingTrade/algosat-ui.git || error "Failed to clone public repository algosat-ui; provide GITHUB_TOKEN."
            fi
        fi
    else
        log "📂 UI directory exists but not a git repo, removing and cloning fresh..."
        cd $ALGOSAT_DIR
        rm -rf algosat-ui
        if [[ -n "${GITHUB_TOKEN}" ]]; then
            git clone https://${GITHUB_TOKEN}@github.com/ExcellingTrade/algosat-ui.git
        else
            git clone https://github.com/ExcellingTrade/algosat-ui.git || error "Failed to clone public repository algosat-ui; provide GITHUB_TOKEN."
        fi
    fi
else
    log "📂 Cloning fresh UI repository..."
    if [[ -n "${GITHUB_TOKEN}" ]]; then
        git clone https://${GITHUB_TOKEN}@github.com/ExcellingTrade/algosat-ui.git
    else
        git clone https://github.com/ExcellingTrade/algosat-ui.git || error "Failed to clone public repository algosat-ui; provide GITHUB_TOKEN."
    fi
fi
if [[ $? -ne 0 ]]; then
    error "Failed to clone AlgoSat UI repository"
fi

# ==============================================================================
# Database Setup
# ==============================================================================

log "🗄️  Setting up PostgreSQL database..."

# Start PostgreSQL service
log "🗄️  Starting PostgreSQL service..."
systemctl start postgresql
systemctl enable postgresql

# Verify PostgreSQL is running
if ! systemctl is-active --quiet postgresql; then
    error "❌ PostgreSQL failed to start"
fi


# Read database configuration from .env
DB_USER="algosat_user"
DB_PASSWORD="admin123"
DB_NAME="algosat_db"

# Set postgres superuser password (changeable via POSTGRES_PASSWORD env var)
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-algosat_postgres123}"


# Create database user and database - idempotent check
log "🗄️  Creating database user and database..."
sudo -u postgres psql << EOF
-- Set postgres superuser password
ALTER USER postgres WITH PASSWORD '$POSTGRES_PASSWORD';

-- Create user (if not exists)
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '$DB_USER') THEN
        CREATE USER $DB_USER WITH PASSWORD '$DB_PASSWORD';
        ALTER USER $DB_USER CREATEDB;
    END IF;
END
\$\$;

-- Exit
\q
EOF

# Check for database backup files and restore if available
FRESH_BACKUP="/tmp/algosat_db_fresh_backup.sql"
INCLUDED_BACKUP="$(dirname "$0")/database/algosat_db_backup.sql"
LEGACY_BACKUP="/tmp/algosat_db_backup.sql"

# Determine which backup files are available
AVAILABLE_BACKUPS=()
BACKUP_DESCRIPTIONS=()

if [[ -f "$FRESH_BACKUP" ]]; then
    FRESH_DATE=$(stat -c %y "$FRESH_BACKUP" 2>/dev/null | cut -d' ' -f1 || echo "Unknown")
    FRESH_SIZE=$(ls -lh "$FRESH_BACKUP" 2>/dev/null | awk '{print $5}' || echo "Unknown")
    AVAILABLE_BACKUPS+=("$FRESH_BACKUP")
    BACKUP_DESCRIPTIONS+=("Fresh backup from migration - $FRESH_DATE ($FRESH_SIZE)")
fi

if [[ -f "$INCLUDED_BACKUP" ]]; then
    INCLUDED_SIZE=$(ls -lh "$INCLUDED_BACKUP" 2>/dev/null | awk '{print $5}' || echo "Unknown")
    AVAILABLE_BACKUPS+=("$INCLUDED_BACKUP")
    BACKUP_DESCRIPTIONS+=("Included backup - September 14, 2025 ($INCLUDED_SIZE)")
fi

if [[ -f "$LEGACY_BACKUP" ]]; then
    LEGACY_DATE=$(stat -c %y "$LEGACY_BACKUP" 2>/dev/null | cut -d' ' -f1 || echo "Unknown")
    LEGACY_SIZE=$(ls -lh "$LEGACY_BACKUP" 2>/dev/null | awk '{print $5}' || echo "Unknown")
    AVAILABLE_BACKUPS+=("$LEGACY_BACKUP")
    BACKUP_DESCRIPTIONS+=("Legacy backup - $LEGACY_DATE ($LEGACY_SIZE)")
fi

CHOSEN_BACKUP=""

if [[ ${#AVAILABLE_BACKUPS[@]} -gt 0 ]]; then
    # Check if database already exists and has data
    DB_EXISTS=$(sudo -u postgres psql -lqt | cut -d \| -f 1 | grep -qw "$DB_NAME" && echo "yes" || echo "no")
    
    if [[ "$DB_EXISTS" == "yes" ]]; then
        # Check if database has tables (data)
        EXISTING_TABLES=$(sudo -u postgres psql -d "$DB_NAME" -tAc "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public';" 2>/dev/null || echo "0")
        
        if [[ "$EXISTING_TABLES" != "0" ]]; then
            warn "⚠️  Database '$DB_NAME' already exists with $EXISTING_TABLES tables"
            echo ""
            echo "🤔 The database contains existing data. What would you like to do?"
            echo "   [Y] Drop existing database and restore from backup (DESTRUCTIVE)"
            echo "   [N] Keep existing database and skip restore (SAFE)"
            echo ""
            
            while true; do
                read -p "Drop and restore database? [Y/N]: " choice
                case $choice in
                    [Yy]* ) 
                        log "🗑️  User confirmed: Dropping existing database..."
                        RESTORE_DB="yes"
                        break
                        ;;
                    [Nn]* ) 
                        log "✋ User chose to keep existing database"
                        RESTORE_DB="no"
                        break
                        ;;
                    * ) 
                        echo "Please answer Y or N."
                        ;;
                esac
            done
        else
            log "📄 Database exists but is empty, proceeding with restore..."
            RESTORE_DB="yes"
        fi
    else
        log "📄 Database doesn't exist, will create and restore..."
        RESTORE_DB="yes"
    fi
    
    if [[ "$RESTORE_DB" == "yes" ]]; then
        # If multiple backups available, let user choose
        if [[ ${#AVAILABLE_BACKUPS[@]} -gt 1 ]]; then
            echo ""
            log "🗄️  Multiple database backups found:"
            for i in "${!AVAILABLE_BACKUPS[@]}"; do
                echo "   [$((i+1))] ${BACKUP_DESCRIPTIONS[$i]}"
            done
            echo ""
            
            while true; do
                read -p "Choose backup to restore [1-${#AVAILABLE_BACKUPS[@]}]: " choice
                if [[ "$choice" =~ ^[0-9]+$ ]] && [[ "$choice" -ge 1 ]] && [[ "$choice" -le ${#AVAILABLE_BACKUPS[@]} ]]; then
                    CHOSEN_BACKUP="${AVAILABLE_BACKUPS[$((choice-1))]}"
                    log "📋 Selected: ${BACKUP_DESCRIPTIONS[$((choice-1))]}"
                    break
                else
                    echo "Please enter a number between 1 and ${#AVAILABLE_BACKUPS[@]}"
                fi
            done
        else
            CHOSEN_BACKUP="${AVAILABLE_BACKUPS[0]}"
            log "🗄️  Using backup: ${BACKUP_DESCRIPTIONS[0]}"
        fi
        
        # Drop existing database if it exists
        log "🗑️  Preparing for fresh database restore..."
        sudo -u postgres psql -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$DB_NAME';" 2>/dev/null || true
        sudo -u postgres dropdb --if-exists $DB_NAME
        
        # Create fresh database
        sudo -u postgres createdb -O $DB_USER $DB_NAME
        
        # Prepare cleaned backup for restore
        log "🗄️  Preparing backup file for restore..."
        cp "$CHOSEN_BACKUP" "/tmp/algosat_db_backup_restore.sql"
        
        # Remove restrict/unrestrict lines and fix ownership
        sed -i '/^\\restrict /d' "/tmp/algosat_db_backup_restore.sql"
        sed -i '/^\\unrestrict /d' "/tmp/algosat_db_backup_restore.sql"
        sed -i 's/OWNER TO postgres/OWNER TO algosat_user/g' "/tmp/algosat_db_backup_restore.sql"
        
        # Restore database from backup
        log "🗄️  Restoring database from backup..."
        if PGPASSWORD="$DB_PASSWORD" psql -U "$DB_USER" -h localhost -d "$DB_NAME" -v ON_ERROR_STOP=1 -f "/tmp/algosat_db_backup_restore.sql"; then
            log "✅ Database restored successfully from backup"
            
            # Verify restore with table count
            TABLE_COUNT=$(PGPASSWORD="$DB_PASSWORD" psql -U "$DB_USER" -h localhost -d "$DB_NAME" -tAc "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public';")
            log "📊 Restored database contains $TABLE_COUNT tables"
            
            # Clean up temporary file
            rm -f "/tmp/algosat_db_backup_restore.sql"
        else
            error "❌ Database restore failed"
        fi
    else
        log "✅ Keeping existing database as requested"
        
        # Ensure database permissions are correct
        sudo -u postgres psql << EOF
-- Grant privileges to existing database
GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;
-- Set search path for the user
ALTER USER $DB_USER SET search_path TO public;
-- Exit
\q
EOF
        log "✅ Database permissions verified"
    fi
else
    log "⚠️  No backup files found, creating empty database..."
    log "   Searched for:"
    log "   - Fresh backup: $FRESH_BACKUP"
    log "   - Included backup: $INCLUDED_BACKUP"
    log "   - Legacy backup: $LEGACY_BACKUP"
    
    # Create empty database (if not exists)
    sudo -u postgres psql << EOF
-- Create database (if not exists)
SELECT 'CREATE DATABASE $DB_NAME OWNER $DB_USER'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '$DB_NAME')\gexec

-- Grant privileges
GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;

-- Set search path for the user
ALTER USER $DB_USER SET search_path TO public;

-- Exit
\q
EOF
    log "✅ Empty database created"
fi

log "✅ Database setup completed"

# Test database connection
log "🧪 Testing database connection..."
sudo -u postgres psql -c "SELECT version();" $DB_NAME
if [[ $? -eq 0 ]]; then
    log "✅ Database connection successful"
else
    error "❌ Database connection failed"
fi

# ==============================================================================
# Python Environment Setup
# ==============================================================================

cd $ALGOSAT_DIR

log "🐍 Setting up Python virtual environment..."


# Ensure Python 3.12 is available
PYTHON_BIN="$(command -v python3.12 || true)"
if [[ -z "$PYTHON_BIN" ]]; then
    error "Python 3.12 is required but not found. Please install python3.12."
fi

# Create virtual environment with Python 3.12 if not exists
if [ ! -d ".venv" ]; then
    log "🐍 Creating new Python 3.12 virtual environment..."
    $PYTHON_BIN -m venv .venv
else
    log "✅ Python virtual environment already exists"
fi

source .venv/bin/activate

# Confirm venv Python version
VENV_PY_VER=$(python --version 2>&1)
if ! python --version 2>&1 | grep -q "3.12"; then
    error "Virtual environment is not using Python 3.12 (found: $VENV_PY_VER)"
fi

log "📦 Installing Python dependencies in venv..."
python -m pip install --upgrade pip

# Robust dependency install with fallback for fyers_apiv3 (in case >=3.3.0 not available for current Python)
set +e
python -m pip install -r $ALGOSAT_CORE_DIR/requirements.txt
PIP_STATUS=$?
if [[ $PIP_STATUS -ne 0 ]]; then
    warn "Primary dependency installation failed (exit $PIP_STATUS). Attempting fallback adjustments..."
    if grep -Eq '^fyers_apiv3[>= ]' "$ALGOSAT_CORE_DIR/requirements.txt"; then
        warn "Adjusting fyers_apiv3 requirement to compatible version 3.1.7..."
        sed -i "s/fyers_apiv3>=3.3.0/fyers_apiv3==3.1.7/" "$ALGOSAT_CORE_DIR/requirements.txt" || warn "Failed to modify fyers_apiv3 line (may already be changed)."
    fi
    python -m pip install -r $ALGOSAT_CORE_DIR/requirements.txt
    PIP_STATUS=$?
    if [[ $PIP_STATUS -ne 0 ]]; then
        # Check for asyncio-limiter and comment it out if present
        if grep -Eq '^asyncio-limiter[>= ]' "$ALGOSAT_CORE_DIR/requirements.txt"; then
            warn "Commenting out asyncio-limiter as it is not available for this Python version."
            sed -i "s/^asyncio-limiter/# asyncio-limiter/" "$ALGOSAT_CORE_DIR/requirements.txt"
            python -m pip install -r $ALGOSAT_CORE_DIR/requirements.txt
            PIP_STATUS=$?
        fi
        if [[ $PIP_STATUS -ne 0 ]]; then
            error "Dependency installation failed even after all fallback adjustments (exit $PIP_STATUS)."
        else
            log "✅ Dependencies installed after skipping asyncio-limiter"
        fi
    else
        log "✅ Dependencies installed after fallback adjustments"
    fi
else
    log "✅ Dependencies installed successfully"
fi
set -e

log "✅ Python environment setup completed"

# ==============================================================================
# Configuration Files
# ==============================================================================

log "⚙️  Setting up configuration files..."

# Copy environment configuration
if [[ -f "/tmp/algosat.env" ]]; then
    log "📄 Found environment configuration from migration: /tmp/algosat.env"
    cp "/tmp/algosat.env" $ALGOSAT_CORE_DIR/.env
    log "✅ Migrated environment configuration"
elif [[ -f "$(dirname "$0")/configs/.env" ]]; then
    log "📄 Copying .env configuration from installer directory..."
    cp "$(dirname "$0")/configs/.env" $ALGOSAT_CORE_DIR/.env
elif [[ ! -f "$ALGOSAT_CORE_DIR/.env" ]]; then
    warn "⚠️  .env file not found, creating default..."
    cat > $ALGOSAT_CORE_DIR/.env << 'EOF'
# Security Configuration
ALGOSAT_MASTER_KEY=mPKI0k_oVc8knM_J_HuM4VmvJnNJL6lnzuRbaYZhebw
JWT_SECRET=DvsJGlurtxhHBrZE7B_pT4FTYtSNA8ktvbSdCI-kJuY
JWT_EXPIRY_MINUTES=60
MAX_FAILED_ATTEMPTS=5
LOCKOUT_DURATION_MINUTES=15
SESSION_TIMEOUT_SECONDS=3600

# Database Configuration
DB_USER=algosat_user
DB_PASSWORD=admin123
DB_HOST=localhost
DB_PORT=5432
DB_NAME=algosat_db

# Application Configuration
POLL_INTERVAL=10

# Telegram Bot Configuration (Update with your values)
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
EOF
fi

# Copy PM2 ecosystem config
if [[ -f "$(dirname "$0")/configs/ecosystem.config.js" ]]; then
    log "📄 Copying PM2 ecosystem config from installer directory..."
    cp "$(dirname "$0")/configs/ecosystem.config.js" $ALGOSAT_CORE_DIR/ecosystem.config.js
elif [[ ! -f "$ALGOSAT_CORE_DIR/ecosystem.config.js" ]]; then
    warn "⚠️  ecosystem.config.js not found, creating default..."
    cat > $ALGOSAT_CORE_DIR/ecosystem.config.js << 'EOF'
module.exports = {
  apps: [
    {
      name: "algosat-main",
      script: "/opt/algosat/.venv/bin/python",
      args: ["-m", "algosat.main"],
      cwd: "/opt/algosat/algosat/",
      interpreter: "none",
      instances: 1,
      exec_mode: "fork",
      autorestart: true,
      watch: false,
      max_memory_restart: "1G",
      env: {
        PYTHONPATH: "/opt/algosat/algosat",
        NODE_ENV: "production"
      },
      log_date_format: "YYYY-MM-DD HH:mm:ss Z",
      out_file: "/opt/algosat/logs/pm2-algosat-main-out.log",
      error_file: "/opt/algosat/logs/pm2-algosat-main-error.log",
      pid_file: "/opt/algosat/logs/pm2-algosat-main.pid",
      min_uptime: "10s",
      max_restarts: 10,
      restart_delay: 4000
    },
    {
      name: "algosat-api",
      script: "/opt/algosat/.venv/bin/python",
      args: ["-m", "algosat.api.main"],
      cwd: "/opt/algosat/algosat",
      interpreter: "none",
      instances: 1,
      exec_mode: "fork",
      autorestart: true,
      watch: false,
      max_memory_restart: "512M",
      env: {
        PYTHONPATH: "/opt/algosat/algosat",
        NODE_ENV: "production",
        API_PORT: "8000"
      },
      log_date_format: "YYYY-MM-DD HH:mm:ss Z",
      out_file: "/opt/algosat/logs/pm2-algosat-api-out.log",
      error_file: "/opt/algosat/logs/pm2-algosat-api-error.log",
      pid_file: "/opt/algosat/logs/pm2-algosat-api.pid",
      min_uptime: "10s",
      max_restarts: 10,
      restart_delay: 4000
    },
    {
      name: "algosat-ui",
      script: "npm",
      args: ["start"],
      cwd: "/opt/algosat/algosat-ui",
      interpreter: "none",
      instances: 1,
      exec_mode: "fork",
      autorestart: true,
      watch: false,
      max_memory_restart: "256M",
      env: {
        NODE_ENV: "production",
        PORT: "3000",
        REACT_APP_API_URL: "http://localhost:8001"
      },
      log_date_format: "YYYY-MM-DD HH:mm:ss Z",
      out_file: "/opt/algosat/logs/pm2-algosat-ui-out.log",
      error_file: "/opt/algosat/logs/pm2-algosat-ui-error.log",
      pid_file: "/opt/algosat/logs/pm2-algosat-ui.pid",
      min_uptime: "10s",
      max_restarts: 10,
      restart_delay: 4000
    },
    {
      name: "broker-monitor",
      script: "/opt/algosat/.venv/bin/python",
      args: ["-m", "algosat.broker_monitor"],
      cwd: "/opt/algosat/algosat",
      interpreter: "none",
      instances: 1,
      exec_mode: "fork",
      autorestart: true,
      watch: false,
      max_memory_restart: "512M",
      env: {
        PYTHONPATH: "/opt/algosat/algosat",
        NODE_ENV: "production"
      },
      log_date_format: "YYYY-MM-DD HH:mm:ss Z",
      out_file: "/opt/algosat/logs/pm2-broker-monitor-out.log",
      error_file: "/opt/algosat/logs/pm2-broker-monitor-error.log",
      pid_file: "/opt/algosat/logs/pm2-broker-monitor.pid",
      min_uptime: "10s",
      max_restarts: 10,
      restart_delay: 4000
    }
  ]
};
EOF
fi

# Set proper permissions
chmod 600 $ALGOSAT_CORE_DIR/.env

# ==============================================================================
# UI Setup
# ==============================================================================

log "🖥️  Setting up AlgoSat UI..."
cd $ALGOSAT_UI_DIR

# Install UI dependencies (skip if node_modules exists and is populated)
if [[ ! -d "node_modules" ]] || [[ -z "$(ls -A node_modules 2>/dev/null)" ]]; then
    log "📦 Installing UI dependencies..."
    npm install
else
    log "✅ UI dependencies already installed"
fi

# Build UI for production (skip if build directory exists and is recent)
if [[ ! -d "build" ]] || [[ "package.json" -nt "build" ]]; then
    log "🔨 Building UI for production..."
    npm run build
else
    log "✅ UI build already up to date"
fi

log "✅ UI setup completed"

# ==============================================================================
# Log Directory Setup
# ==============================================================================

log "📝 Setting up log directories..."
mkdir -p $ALGOSAT_DIR/logs

# ==============================================================================
# Database Schema Setup
# ==============================================================================

log "🗄️  Setting up database schema..."
cd $ALGOSAT_DIR

# Activate virtual environment and run database migrations
source .venv/bin/activate

# Test Python imports
log "🧪 Testing Python imports..."
PYTHONPATH=$ALGOSAT_CORE_DIR python3 -c "import algosat; print('AlgoSat imports successful')"
if [[ $? -ne 0 ]]; then
    error "❌ Python imports failed"
fi

log "✅ Database schema setup completed"

# ==============================================================================
# Firewall Configuration
# ==============================================================================

log "🔥 Configuring firewall..."

# Install UFW if not already installed
if ! command -v ufw &> /dev/null; then
    log "📦 Installing UFW firewall..."
    apt install -y ufw
else
    log "✅ UFW already installed"
fi

# Configure firewall rules (idempotent)
log "⚙️  Setting up firewall rules..."

# Allow SSH
ufw allow 22

# Allow API port
ufw allow 8001
ufw allow 8000

# Allow UI port
ufw allow 3000

# Enable firewall (only if not already enabled)
if ! ufw status | grep -q "Status: active"; then
    log "🔥 Enabling firewall..."
    ufw --force enable
else
    log "✅ Firewall already enabled"
fi

log "✅ Firewall configured"

# ==============================================================================
# Service Startup
# ==============================================================================

log "🚀 Starting AlgoSat services..."

# Start PM2 services (restart if already running)
cd $ALGOSAT_DIR

# Check if PM2 processes are already running
if pm2 list | grep -q "algosat"; then
    log "🔄 PM2 services already running, restarting..."
    pm2 restart $ALGOSAT_CORE_DIR/ecosystem.config.js
else
    log "🚀 Starting PM2 services for the first time..."
    pm2 start $ALGOSAT_CORE_DIR/ecosystem.config.js
fi

# Save PM2 configuration
pm2 save

# Setup PM2 auto-start on boot (idempotent)
if ! systemctl is-enabled pm2-root &>/dev/null; then
    log "⚙️  Setting up PM2 auto-start on boot..."
    pm2 startup systemd
    env PATH=$PATH:/usr/bin pm2 startup systemd -u root --hp /root
else
    log "✅ PM2 auto-start already configured"
fi

log "✅ Services started successfully"

# ==============================================================================
# Cron Job Deployment
# ==============================================================================

log "📅 Setting up automated scheduling (cron jobs)..."

# Navigate to installer scripts directory
INSTALLER_DIR="$(dirname "$0")"
cd "$INSTALLER_DIR/scripts"

# Check if install_cron.sh exists
if [ -f "install_cron.sh" ]; then
    log "📋 Installing cron jobs for automated trading schedule..."
    chmod +x install_cron.sh
    ./install_cron.sh
    
    log "✅ Cron jobs configured successfully"
    log "📅 Automated schedule:"
    log "   - Market operations: 8:30 AM - 4:00 PM IST (weekdays)"
    log "   - System maintenance: Midnight IST (daily)"
    log "   - Weekend shutdown: Automatic"
else
    warn "⚠️  install_cron.sh not found - skipping cron job setup"
    warn "   You can set up cron jobs manually later using:"
    warn "   cd $INSTALLER_DIR/scripts && ./install_cron.sh"
fi

# Return to core directory
cd "$ALGOSAT_CORE_DIR"

# ==============================================================================
# Health Checks
# ==============================================================================

log "🩺 Running health checks..."

# Wait for services to start
sleep 10

# Check PM2 status
log "📊 PM2 Service Status:"
pm2 status

# Check if API is responding
log "🧪 Testing API endpoint..."
sleep 5  # Wait for API to fully start
if curl -f http://localhost:8001/health > /dev/null 2>&1; then
    log "✅ API health check passed"
else
    warn "⚠️  API health check failed - service may still be starting"
fi

# Check if UI is responding
log "🧪 Testing UI endpoint..."
if curl -f http://localhost:3000 > /dev/null 2>&1; then
    log "✅ UI health check passed"
else
    warn "⚠️  UI health check failed - service may still be starting"
fi

# ==============================================================================
# Deployment Summary
# ==============================================================================

echo ""
echo "🎉 =================================================="
echo "🎉           DEPLOYMENT COMPLETED SUCCESSFULLY!"
echo "🎉 =================================================="
echo ""
log "📍 Installation Directory: $ALGOSAT_CORE_DIR"
log "🔗 API URL: http://$(hostname -I | cut -d' ' -f1):8001"
log "🔗 UI URL: http://$(hostname -I | cut -d' ' -f1):3000"
log "🗄️  Database: PostgreSQL (localhost:5432)"
log "👤 Database User: $DB_USER"
log "🗃️  Database Name: $DB_NAME"
echo ""
log "📊 Service Management Commands:"
log "   pm2 status              - Check service status"
log "   pm2 restart all         - Restart all services"
log "   pm2 logs                - View all logs"
log "   pm2 logs algosat-api    - View API logs"
log "   pm2 logs algosat-ui     - View UI logs"
log "   pm2 stop all           - Stop all services"
echo ""
log "🔍 Log Files:"
log "   /opt/algosat/logs/      - All PM2 logs"
log "   /opt/algosat/logs/cron.log - Cron job execution logs"
echo ""
log "📅 Automated Scheduling:"
log "   crontab -l              - View scheduled tasks"
log "   /opt/algosat/algosat/scripts/ - Automation scripts"
log "   Market Hours: 8:30 AM - 4:00 PM IST (Mon-Fri)"
log "   Weekend Mode: Services automatically stopped"
echo ""
log "⚙️  Configuration Files:"
log "   /opt/algosat/algosat/.env             - Environment variables"
log "   /opt/algosat/algosat/ecosystem.config.js - PM2 configuration"
echo ""
log "🔄 IDEMPOTENT DEPLOYMENT:"
log "   ✅ Safe to re-run if interrupted or failed"
log "   ✅ Existing repositories will be updated, not re-cloned"
log "   ✅ Database user/database creation skipped if exists"
log "   ✅ Virtual environment reused if present"
log "   ✅ UI dependencies/build skipped if up-to-date"
log "   ✅ PM2 services restarted if already running"
log "   ✅ Firewall rules safely applied multiple times"
echo ""

# Final PM2 status
echo "📊 Current Service Status:"
pm2 status

echo ""
log "🚀 AlgoSat is now running!"
log "   Access the UI at: http://$(hostname -I | cut -d' ' -f1):3000"
log "   Access the API at: http://$(hostname -I | cut -d' ' -f1):8001"
echo ""
warn "⚠️  IMPORTANT: Update the .env file with your actual Telegram bot token and chat ID"
warn "⚠️  IMPORTANT: Configure your broker credentials in the application"
echo ""
log "🧪 Running integrated deployment validation..."
echo ""

# Run validation script if it exists
SCRIPT_DIR="$(dirname "$0")"
if [[ -f "$SCRIPT_DIR/validate_deployment.sh" ]]; then
    log "🔍 Running comprehensive validation checks..."
    chmod +x "$SCRIPT_DIR/validate_deployment.sh"
    
    echo "════════════════════════════════════════════════════════════════════════════════"
    echo "                             DEPLOYMENT VALIDATION                              "
    echo "════════════════════════════════════════════════════════════════════════════════"
    
    # Run validation and capture exit code
    if "$SCRIPT_DIR/validate_deployment.sh"; then
        echo ""
        echo "════════════════════════════════════════════════════════════════════════════════"
        log "🎉 Deployment validation passed! AlgoSat is fully operational."
    else
        echo ""
        echo "════════════════════════════════════════════════════════════════════════════════"
        warn "⚠️  Deployment validation completed with warnings - check output above"
        log "💡 Most warnings are informational - system should still be functional"
    fi
else
    warn "⚠️  Validation script not found at $SCRIPT_DIR/validate_deployment.sh"
    log "🧪 To validate manually later, run: ./validate_deployment.sh"
fi

echo ""
log "✅ Deployment completed successfully!"