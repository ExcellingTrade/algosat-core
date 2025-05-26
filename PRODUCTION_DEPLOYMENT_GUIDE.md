# Algosat Trading System - Production Deployment Guide

## Overview

This guide covers the complete production deployment of the enhanced Algosat Trading System with comprehensive security, monitoring, error handling, and VPS optimization features.

## Architecture Overview

### Enhanced Components

1. **Security Hardening** (`core/security.py`)
   - Advanced input validation and sanitization
   - Rate limiting and IP blocking
   - Authentication and session management
   - Security monitoring and alerting
   - Audit trail and access logging

2. **Error Handling & Resilience** (`core/resilience.py`)
   - Structured error classification and tracking
   - Circuit breakers and retry mechanisms
   - Error analytics and pattern recognition
   - Recovery action tracking

3. **Configuration Management** (`core/config_management.py`)
   - Centralized configuration with environment support
   - Encrypted credential storage
   - Configuration validation and templates
   - Hot-reload capabilities

4. **Enhanced Monitoring** (`core/monitoring.py`)
   - Prometheus metrics integration
   - Health checks and system monitoring
   - Performance tracking and alerting
   - Structured logging with correlation IDs

5. **VPS Performance Optimization** (`core/vps_performance.py`)
   - Resource monitoring and optimization
   - Process and memory management
   - Disk and network optimization
   - Performance recommendations

6. **Enhanced API** (`api/enhanced_app.py`)
   - Production-grade FastAPI application
   - Integrated security middleware
   - Comprehensive error handling
   - Performance monitoring

## Installation Guide

### Prerequisites

- Ubuntu 20.04 LTS or newer
- Python 3.11+
- 2GB+ RAM (4GB recommended)
- 20GB+ disk space
- Root access for initial setup

### Quick Installation

```bash
# Clone the repository
git clone <repository-url>
cd algosat

# Run the production deployment script
sudo ./deploy/production_deploy.sh
```

### Manual Installation

If you prefer manual installation, follow these steps:

#### 1. System Preparation

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install system dependencies
sudo apt install -y python3.11 python3.11-venv python3.11-dev \
    build-essential git curl wget sqlite3 nginx supervisor \
    htop iotop nethogs fail2ban ufw logrotate cron rsync

# Create system user
sudo useradd --system --shell /bin/bash --home-dir /opt/algosat \
    --create-home --comment "Algosat Trading System" algosat
```

#### 2. Directory Structure

```bash
# Create directories
sudo mkdir -p /opt/algosat/{algosat,venv,bin}
sudo mkdir -p /etc/algosat
sudo mkdir -p /var/log/algosat
sudo mkdir -p /var/lib/algosat/{database,backups,cache,security}

# Set permissions
sudo chown -R algosat:algosat /opt/algosat /var/log/algosat /var/lib/algosat
sudo chmod 750 /etc/algosat /var/lib/algosat/security
```

#### 3. Python Environment

```bash
# Create virtual environment
sudo -u algosat python3.11 -m venv /opt/algosat/venv

# Install dependencies
sudo -u algosat /opt/algosat/venv/bin/pip install -r requirements.txt
```

#### 4. Configuration

Copy the configuration templates:

```bash
# Main configuration
sudo cp deploy/config/algosat.yaml /etc/algosat/
sudo cp deploy/config/security.yaml /etc/algosat/

# Set permissions
sudo chown algosat:algosat /etc/algosat/*.yaml
sudo chmod 640 /etc/algosat/*.yaml
```

#### 5. Service Setup

```bash
# Copy systemd service
sudo cp deploy/algosat.service /etc/systemd/system/

# Enable and start service
sudo systemctl daemon-reload
sudo systemctl enable algosat.service
sudo systemctl start algosat.service
```

#### 6. Nginx Configuration (Optional)

```bash
# Copy nginx configuration
sudo cp deploy/nginx_algosat.conf /etc/nginx/sites-available/algosat
sudo ln -s /etc/nginx/sites-available/algosat /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

## Configuration Guide

### Main Configuration (`/etc/algosat/algosat.yaml`)

```yaml
# Environment: development, testing, staging, production
environment: production
debug: false

database:
  url: "sqlite:///var/lib/algosat/database/algosat.db"
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
  file: "/var/log/algosat/algosat.log"
  max_size: 100MB
  backup_count: 10

security:
  secret_key: "your-secret-key-here"
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
```

### Security Configuration (`/etc/algosat/security.yaml`)

```yaml
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
```

### Broker Configuration

Store encrypted broker credentials:

```python
# Using the configuration manager
from core.config_management import ConfigManager

config_manager = ConfigManager()
await config_manager.initialize()

# Store broker credentials (encrypted)
await config_manager.store_encrypted_credentials("fyers", {
    "client_id": "your_client_id",
    "client_secret": "your_client_secret",
    "redirect_uri": "your_redirect_uri"
})
```

## API Documentation

### Enhanced Endpoints

#### Authentication

```bash
# Login
POST /auth/login
{
    "username": "your_username",
    "password": "your_password"
}

# Response
{
    "access_token": "jwt_token",
    "token_type": "bearer",
    "expires_in": 1800,
    "user_info": {...}
}

# Logout
POST /auth/logout
Authorization: Bearer <token>
```

#### System Monitoring

```bash
# Health check
GET /health

# Response
{
    "status": "healthy",
    "timestamp": "2025-05-25T10:00:00Z",
    "components": {
        "database": true,
        "security": true,
        "config": true,
        "vps": true
    },
    "details": {...}
}

# Metrics (Prometheus format)
GET /metrics

# System status (authenticated)
GET /system/status
Authorization: Bearer <token>
```

#### Configuration Management

```bash
# Get configuration summary (authenticated)
GET /config/summary
Authorization: Bearer <token>

# Update configuration (admin only)
PUT /config/update
Authorization: Bearer <token>
{
    "section": "api",
    "updates": {
        "port": 8081
    }
}
```

## Security Features

### Input Validation

All inputs are validated against:
- SQL injection patterns
- XSS attacks
- Path traversal attempts
- Command injection
- Size and format constraints

### Rate Limiting

- API endpoints: 100 requests/minute per IP
- Authentication: 5 attempts/minute per IP
- Configurable per endpoint

### Access Control

- JWT-based authentication
- Role-based access control
- IP whitelisting for admin endpoints
- Session management with timeouts

### Security Monitoring

- Failed authentication tracking
- Suspicious activity detection
- IP blocking for repeated violations
- Security event audit trail

## Monitoring and Alerting

### Metrics

Available Prometheus metrics:
- `algosat_requests_total` - Total API requests
- `algosat_request_duration_seconds` - Request duration
- `algosat_orders_total` - Trading orders
- `algosat_positions_current` - Open positions
- `algosat_errors_total` - System errors
- `algosat_security_events_total` - Security events

### Health Checks

- Database connectivity
- API responsiveness
- Security system status
- VPS performance metrics
- External broker connections

### Logging

Structured JSON logging with:
- Request correlation IDs
- Performance metrics
- Security events
- Error tracking
- Audit trails

## VPS Optimization

### Resource Monitoring

- CPU usage tracking
- Memory utilization
- Disk space monitoring
- Network performance
- Process monitoring

### Optimization Features

- Memory leak detection
- CPU optimization recommendations
- Disk cleanup automation
- Network connection optimization
- Process priority management

### Performance Tuning

Kernel parameters optimized for trading:
```bash
# Network optimizations
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_rmem = 4096 65536 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216

# File system optimizations
fs.file-max = 65535
vm.swappiness = 10
```

## Error Handling and Resilience

### Error Classification

Errors are classified by:
- Severity: LOW, MEDIUM, HIGH, CRITICAL
- Category: NETWORK, DATABASE, AUTHENTICATION, TRADING, SYSTEM
- Component: API, BROKER, STRATEGY, etc.

### Resilience Features

- Circuit breakers for external services
- Retry mechanisms with exponential backoff
- Timeout handling
- Graceful degradation
- Error recovery actions

### Error Analytics

- Error trend analysis
- Pattern recognition
- Performance impact assessment
- Recovery success rates

## Backup and Recovery

### Automated Backups

Daily backups include:
- Database files
- Configuration files
- Log files (last 7 days)
- Security audit trails

### Backup Script

```bash
# Manual backup
sudo -u algosat /opt/algosat/bin/backup.sh

# Restore from backup
sudo -u algosat /opt/algosat/bin/restore.sh backup_file.tar.gz
```

## Troubleshooting

### Common Issues

#### Service Won't Start

```bash
# Check service status
sudo systemctl status algosat.service

# Check logs
sudo journalctl -u algosat.service -f

# Check configuration
sudo -u algosat /opt/algosat/venv/bin/python -c "
from core.config_management import ConfigManager
import asyncio
async def test():
    cm = ConfigManager()
    await cm.initialize()
    config = await cm.get_config()
    print('Config loaded successfully')
asyncio.run(test())
"
```

#### High Memory Usage

```bash
# Check VPS optimizer recommendations
curl -H "Authorization: Bearer <token>" http://localhost:8080/system/status

# Manual memory cleanup
sudo systemctl restart algosat.service
```

#### Authentication Issues

```bash
# Check security logs
sudo tail -f /var/log/algosat/algosat.log | grep -i auth

# Reset security database
sudo -u algosat rm /var/lib/algosat/security/security_events.db
sudo systemctl restart algosat.service
```

### Log Analysis

```bash
# Real-time logs
sudo journalctl -u algosat.service -f

# Error logs only
sudo grep -i error /var/log/algosat/algosat.log

# Security events
sudo grep -i security /var/log/algosat/algosat.log

# Performance metrics
curl http://localhost:8080/metrics | grep algosat_
```

## Maintenance

### Regular Tasks

1. **Daily**
   - Check system health: `curl http://localhost:8080/health`
   - Review error logs
   - Monitor resource usage

2. **Weekly**
   - Update system packages
   - Review backup integrity
   - Check security alerts

3. **Monthly**
   - Rotate security keys
   - Review and update configurations
   - Performance optimization review

### Updates

```bash
# Update application code
cd /opt/algosat/algosat
sudo -u algosat git pull
sudo -u algosat /opt/algosat/venv/bin/pip install -r requirements.txt
sudo systemctl restart algosat.service

# Update system packages
sudo apt update && sudo apt upgrade -y
sudo reboot  # if kernel updated
```

## Support and Contact

For technical support:
1. Check the troubleshooting section
2. Review system logs
3. Check GitHub issues
4. Contact system administrator

## Security Considerations

### Production Checklist

- [ ] Change default passwords and secrets
- [ ] Configure proper SSL certificates
- [ ] Set up firewall rules
- [ ] Enable fail2ban
- [ ] Configure log rotation
- [ ] Set up monitoring alerts
- [ ] Test backup and recovery
- [ ] Review security configurations
- [ ] Enable VPS optimizations
- [ ] Set up health monitoring

### Security Best Practices

1. Regular security updates
2. Strong password policies
3. Network segmentation
4. Regular security audits
5. Encrypted communications
6. Access logging and monitoring
7. Incident response procedures
