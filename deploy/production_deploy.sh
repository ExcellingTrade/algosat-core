#!/bin/bash
"""
Production deployment script for Algosat Trading System on VPS.
This script sets up the complete production environment with all enhancements.
"""

set -euo pipefail

# Configuration
ALGOSAT_USER="algosat"
ALGOSAT_HOME="/opt/algosat"
ALGOSAT_CONFIG_DIR="/etc/algosat"
ALGOSAT_LOG_DIR="/var/log/algosat"
ALGOSAT_DATA_DIR="/var/lib/algosat"
PYTHON_VERSION="3.11"
VENV_PATH="${ALGOSAT_HOME}/venv"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_debug() {
    echo -e "${BLUE}[DEBUG]${NC} $1"
}

# Check if script is run as root
check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "This script must be run as root"
        exit 1
    fi
}

# Create system user for algosat
create_system_user() {
    log_info "Creating system user: $ALGOSAT_USER"
    
    if ! id "$ALGOSAT_USER" &>/dev/null; then
        useradd --system --shell /bin/bash --home-dir "$ALGOSAT_HOME" \
                --create-home --comment "Algosat Trading System" "$ALGOSAT_USER"
        log_info "User $ALGOSAT_USER created successfully"
    else
        log_info "User $ALGOSAT_USER already exists"
    fi
}

# Create directory structure
create_directories() {
    log_info "Creating directory structure"
    
    directories=(
        "$ALGOSAT_HOME"
        "$ALGOSAT_CONFIG_DIR"
        "$ALGOSAT_LOG_DIR"
        "$ALGOSAT_DATA_DIR"
        "$ALGOSAT_DATA_DIR/backups"
        "$ALGOSAT_DATA_DIR/cache"
        "$ALGOSAT_DATA_DIR/database"
        "$ALGOSAT_DATA_DIR/security"
    )
    
    for dir in "${directories[@]}"; do
        mkdir -p "$dir"
        chown "$ALGOSAT_USER:$ALGOSAT_USER" "$dir"
        chmod 755 "$dir"
    done
    
    # Secure directories
    chmod 750 "$ALGOSAT_CONFIG_DIR"
    chmod 750 "$ALGOSAT_DATA_DIR/security"
    chmod 755 "$ALGOSAT_LOG_DIR"
}

# Install system dependencies
install_system_dependencies() {
    log_info "Installing system dependencies"
    
    # Update package list
    apt-get update
    
    # Install required packages
    apt-get install -y \
        python3.11 \
        python3.11-venv \
        python3.11-dev \
        python3-pip \
        build-essential \
        git \
        curl \
        wget \
        sqlite3 \
        nginx \
        supervisor \
        htop \
        iotop \
        nethogs \
        fail2ban \
        ufw \
        logrotate \
        cron \
        rsync \
        unzip \
        ca-certificates \
        gnupg \
        lsb-release
    
    log_info "System dependencies installed successfully"
}

# Setup Python virtual environment
setup_python_environment() {
    log_info "Setting up Python virtual environment"
    
    # Create virtual environment
    sudo -u "$ALGOSAT_USER" python3.11 -m venv "$VENV_PATH"
    
    # Upgrade pip
    sudo -u "$ALGOSAT_USER" "$VENV_PATH/bin/pip" install --upgrade pip
    
    # Install Python dependencies
    if [[ -f "$ALGOSAT_HOME/algosat/requirements.txt" ]]; then
        sudo -u "$ALGOSAT_USER" "$VENV_PATH/bin/pip" install -r "$ALGOSAT_HOME/algosat/requirements.txt"
    else
        log_warn "requirements.txt not found, installing base dependencies"
        sudo -u "$ALGOSAT_USER" "$VENV_PATH/bin/pip" install \
            fastapi \
            uvicorn \
            sqlalchemy \
            aiosqlite \
            structlog \
            prometheus-client \
            cryptography \
            PyYAML \
            python-multipart \
            python-jose \
            passlib \
            bcrypt
    fi
    
    log_info "Python environment setup completed"
}

# Setup configuration files
setup_configuration() {
    log_info "Setting up configuration files"
    
    # Create main configuration
    cat > "$ALGOSAT_CONFIG_DIR/algosat.yaml" << EOF
# Algosat Trading System Configuration
environment: production
debug: false

database:
  url: "sqlite:///$ALGOSAT_DATA_DIR/database/algosat.db"
  pool_size: 5
  max_overflow: 10

api:
  host: "0.0.0.0"
  port: 8080
  workers: 1
  reload: false

logging:
  level: INFO
  format: json
  file: "$ALGOSAT_LOG_DIR/algosat.log"
  max_size: 100MB
  backup_count: 10

security:
  secret_key: "$(openssl rand -hex 32)"
  algorithm: "HS256"
  access_token_expire_minutes: 30
  rate_limit_requests: 100
  rate_limit_window: 60

monitoring:
  metrics_enabled: true
  health_check_interval: 30
  performance_monitoring: true

vps:
  optimization_enabled: true
  memory_threshold: 80
  cpu_threshold: 80
  disk_threshold: 85
EOF

    # Create security configuration
    cat > "$ALGOSAT_CONFIG_DIR/security.yaml" << EOF
# Security Configuration
authentication:
  enabled: true
  session_timeout: 1800
  max_login_attempts: 5
  lockout_duration: 300

encryption:
  key_rotation_days: 30
  algorithm: "Fernet"

monitoring:
  log_failed_attempts: true
  alert_threshold: 10
  block_suspicious_ips: true

access_control:
  admin_only_endpoints:
    - "/config/update"
    - "/system/admin"
  public_endpoints:
    - "/health"
    - "/metrics"
    - "/"
EOF

    # Set proper permissions
    chown -R "$ALGOSAT_USER:$ALGOSAT_USER" "$ALGOSAT_CONFIG_DIR"
    chmod 640 "$ALGOSAT_CONFIG_DIR"/*.yaml
    
    log_info "Configuration files created"
}

# Setup systemd service
setup_systemd_service() {
    log_info "Setting up systemd service"
    
    cat > /etc/systemd/system/algosat.service << EOF
[Unit]
Description=Algosat Trading System
After=network.target
Wants=network.target

[Service]
Type=exec
User=$ALGOSAT_USER
Group=$ALGOSAT_USER
WorkingDirectory=$ALGOSAT_HOME/algosat
Environment=PATH=$VENV_PATH/bin
Environment=PYTHONPATH=$ALGOSAT_HOME/algosat
Environment=ALGOSAT_CONFIG_DIR=$ALGOSAT_CONFIG_DIR
Environment=ALGOSAT_LOG_DIR=$ALGOSAT_LOG_DIR
Environment=ALGOSAT_DATA_DIR=$ALGOSAT_DATA_DIR
ExecStart=$VENV_PATH/bin/python -m api.enhanced_app
ExecReload=/bin/kill -HUP \$MAINPID
KillMode=mixed
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

# Security settings
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=$ALGOSAT_DATA_DIR $ALGOSAT_LOG_DIR
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes

# Resource limits
LimitNOFILE=65535
MemoryMax=2G
CPUQuota=200%

[Install]
WantedBy=multi-user.target
EOF

    # Reload systemd and enable service
    systemctl daemon-reload
    systemctl enable algosat.service
    
    log_info "Systemd service configured"
}

# Setup log rotation
setup_log_rotation() {
    log_info "Setting up log rotation"
    
    cat > /etc/logrotate.d/algosat << EOF
$ALGOSAT_LOG_DIR/*.log {
    daily
    missingok
    rotate 30
    compress
    delaycompress
    notifempty
    copytruncate
    su $ALGOSAT_USER $ALGOSAT_USER
    postrotate
        systemctl reload algosat.service > /dev/null 2>&1 || true
    endscript
}
EOF

    log_info "Log rotation configured"
}

# Setup firewall
setup_firewall() {
    log_info "Setting up firewall (UFW)"
    
    # Reset UFW to defaults
    ufw --force reset
    
    # Default policies
    ufw default deny incoming
    ufw default allow outgoing
    
    # Allow SSH (be careful not to lock yourself out)
    ufw allow ssh
    
    # Allow Algosat API
    ufw allow 8080/tcp
    
    # Allow HTTP and HTTPS for nginx (if needed)
    ufw allow 80/tcp
    ufw allow 443/tcp
    
    # Enable UFW
    ufw --force enable
    
    log_info "Firewall configured"
}

# Setup fail2ban
setup_fail2ban() {
    log_info "Setting up fail2ban"
    
    cat > /etc/fail2ban/jail.local << EOF
[DEFAULT]
bantime = 1h
findtime = 10m
maxretry = 5

[sshd]
enabled = true
port = ssh
logpath = /var/log/auth.log
maxretry = 3

[algosat]
enabled = true
port = 8080
logpath = $ALGOSAT_LOG_DIR/algosat.log
filter = algosat
maxretry = 5
bantime = 1h
EOF

    cat > /etc/fail2ban/filter.d/algosat.conf << EOF
[Definition]
failregex = ^.*Authentication failed.*client_ip.*<HOST>.*$
            ^.*Rate limit exceeded.*<HOST>.*$
            ^.*Suspicious activity.*<HOST>.*$
ignoreregex =
EOF

    systemctl enable fail2ban
    systemctl restart fail2ban
    
    log_info "Fail2ban configured"
}

# Setup monitoring and health checks
setup_monitoring() {
    log_info "Setting up monitoring and health checks"
    
    # Create health check script
    cat > "$ALGOSAT_HOME/bin/health_check.sh" << 'EOF'
#!/bin/bash
# Health check script for Algosat

API_URL="http://localhost:8080/health"
TIMEOUT=10

# Check if API is responding
response=$(curl -s -w "%{http_code}" -o /dev/null --connect-timeout $TIMEOUT "$API_URL")

if [[ "$response" == "200" ]]; then
    echo "OK: Algosat API is healthy"
    exit 0
else
    echo "CRITICAL: Algosat API is not responding (HTTP $response)"
    exit 2
fi
EOF

    chmod +x "$ALGOSAT_HOME/bin/health_check.sh"
    chown "$ALGOSAT_USER:$ALGOSAT_USER" "$ALGOSAT_HOME/bin/health_check.sh"
    
    # Add cron job for health monitoring
    cat > /etc/cron.d/algosat-health << EOF
# Algosat health monitoring
*/5 * * * * $ALGOSAT_USER $ALGOSAT_HOME/bin/health_check.sh >> $ALGOSAT_LOG_DIR/health.log 2>&1
EOF

    log_info "Monitoring configured"
}

# Setup backup system
setup_backup() {
    log_info "Setting up backup system"
    
    # Create backup script
    cat > "$ALGOSAT_HOME/bin/backup.sh" << EOF
#!/bin/bash
# Backup script for Algosat

BACKUP_DIR="$ALGOSAT_DATA_DIR/backups"
TIMESTAMP=\$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="algosat_backup_\$TIMESTAMP.tar.gz"

# Create backup
tar -czf "\$BACKUP_DIR/\$BACKUP_FILE" \\
    -C "$ALGOSAT_DATA_DIR" database \\
    -C "$ALGOSAT_CONFIG_DIR" . \\
    -C "$ALGOSAT_LOG_DIR" . \\
    --exclude="*.tmp" \\
    --exclude="*.lock"

# Keep only last 7 days of backups
find "\$BACKUP_DIR" -name "algosat_backup_*.tar.gz" -mtime +7 -delete

echo "Backup completed: \$BACKUP_FILE"
EOF

    chmod +x "$ALGOSAT_HOME/bin/backup.sh"
    chown "$ALGOSAT_USER:$ALGOSAT_USER" "$ALGOSAT_HOME/bin/backup.sh"
    
    # Add daily backup cron job
    cat > /etc/cron.d/algosat-backup << EOF
# Daily backup for Algosat
0 2 * * * $ALGOSAT_USER $ALGOSAT_HOME/bin/backup.sh >> $ALGOSAT_LOG_DIR/backup.log 2>&1
EOF

    log_info "Backup system configured"
}

# Optimize system for trading
optimize_system() {
    log_info "Optimizing system for trading"
    
    # Kernel parameters for low latency
    cat >> /etc/sysctl.conf << EOF

# Algosat Trading System Optimizations
# Network optimizations
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_rmem = 4096 65536 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216
net.core.netdev_max_backlog = 5000

# File system optimizations
fs.file-max = 65535
vm.swappiness = 10
vm.dirty_ratio = 15
vm.dirty_background_ratio = 5
EOF

    # Apply sysctl changes
    sysctl -p
    
    # Increase file limits
    cat > /etc/security/limits.d/algosat.conf << EOF
$ALGOSAT_USER soft nofile 65535
$ALGOSAT_USER hard nofile 65535
$ALGOSAT_USER soft nproc 32768
$ALGOSAT_USER hard nproc 32768
EOF

    log_info "System optimization completed"
}

# Setup SSL/TLS (basic self-signed for development)
setup_ssl() {
    log_info "Setting up SSL certificates"
    
    SSL_DIR="$ALGOSAT_CONFIG_DIR/ssl"
    mkdir -p "$SSL_DIR"
    
    # Generate self-signed certificate (replace with proper SSL in production)
    openssl req -new -newkey rsa:4096 -days 365 -nodes -x509 \
        -subj "/C=IN/ST=State/L=City/O=Algosat/CN=localhost" \
        -keyout "$SSL_DIR/algosat.key" \
        -out "$SSL_DIR/algosat.crt"
    
    chmod 600 "$SSL_DIR/algosat.key"
    chmod 644 "$SSL_DIR/algosat.crt"
    chown -R "$ALGOSAT_USER:$ALGOSAT_USER" "$SSL_DIR"
    
    log_info "SSL certificates generated (self-signed)"
}

# Install and start the service
install_and_start() {
    log_info "Installing and starting Algosat service"
    
    # Install the application (copy current directory to algosat home)
    if [[ -d "./algosat" ]]; then
        rsync -av --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' \
              ./algosat/ "$ALGOSAT_HOME/algosat/"
        chown -R "$ALGOSAT_USER:$ALGOSAT_USER" "$ALGOSAT_HOME/algosat"
    else
        log_warn "Algosat source directory not found. Please copy manually."
    fi
    
    # Start the service
    systemctl start algosat.service
    
    # Check service status
    sleep 5
    if systemctl is-active --quiet algosat.service; then
        log_info "Algosat service started successfully"
    else
        log_error "Failed to start Algosat service"
        systemctl status algosat.service
        exit 1
    fi
}

# Post-installation checks
post_install_checks() {
    log_info "Running post-installation checks"
    
    # Check service status
    systemctl status algosat.service --no-pager
    
    # Check if API is responding
    sleep 10
    if curl -s http://localhost:8080/health > /dev/null; then
        log_info "✓ API health check passed"
    else
        log_warn "⚠ API health check failed"
    fi
    
    # Check logs
    if [[ -f "$ALGOSAT_LOG_DIR/algosat.log" ]]; then
        log_info "✓ Log file created"
    else
        log_warn "⚠ Log file not found"
    fi
    
    # Check database
    if [[ -f "$ALGOSAT_DATA_DIR/database/algosat.db" ]]; then
        log_info "✓ Database file exists"
    else
        log_warn "⚠ Database file not found"
    fi
    
    log_info "Installation completed successfully!"
    log_info "Service status: systemctl status algosat.service"
    log_info "Logs: journalctl -u algosat.service -f"
    log_info "API: http://localhost:8080"
}

# Main installation function
main() {
    log_info "Starting Algosat Trading System deployment"
    
    check_root
    create_system_user
    create_directories
    install_system_dependencies
    setup_python_environment
    setup_configuration
    setup_systemd_service
    setup_log_rotation
    setup_firewall
    setup_fail2ban
    setup_monitoring
    setup_backup
    optimize_system
    setup_ssl
    install_and_start
    post_install_checks
    
    log_info "Deployment completed successfully!"
}

# Run main function
main "$@"
