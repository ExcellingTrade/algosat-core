# AlgoSat Core - Production Deployment Guide

## Quick Start Overview

This guide provides step-by-step instructions to deploy AlgoSat Core trading system in           env: {
        NODE_ENV: 'production',
        PYTHONPATH: '/opt/algosat',
      },
      log_file: '/opt/algosat/logs/algosat_api/combined.log', {
        NODE_ENV: 'production',
        PYTHONPATH: '/opt/algosat',
      },
      log_file: '/opt/algosat/logs/algosat_main/combined.log',tion using PM2 process manager. The system consists of three main services:

- **Database Service**: PostgreSQL database
- **API Service**: FastAPI REST API server  
- **Core Service**: Main trading engine and strategy executor

## Prerequisites

- Ubuntu 20.04+ server with root access
- Minimum 4GB RAM, 50GB disk space
- Internet connection for package downloads

## Step 1: System Setup

### Update System
```bash
sudo apt update && sudo apt upgrade -y
```

### Install Required Packages
```bash
sudo apt install -y python3.11 python3.11-venv python3.11-dev \
    postgresql postgresql-contrib nginx git curl wget \
    build-essential supervisor htop
```

### Install Node.js and PM2
```bash
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt install -y nodejs
sudo npm install -g pm2
```

## Step 2: Database Setup

### Install and Configure PostgreSQL
```bash
# Start PostgreSQL service
sudo systemctl start postgresql
sudo systemctl enable postgresql

# Create database user and database
sudo -u postgres psql << EOF
CREATE USER algosat WITH PASSWORD 'your_secure_password_here';
CREATE DATABASE algosat_db OWNER algosat;
GRANT ALL PRIVILEGES ON DATABASE algosat_db TO algosat;
\q
EOF
```

### Configure PostgreSQL for Remote Access
```bash
# Edit postgresql.conf
sudo sed -i "s/#listen_addresses = 'localhost'/listen_addresses = '*'/" /etc/postgresql/*/main/postgresql.conf

# Edit pg_hba.conf for local access
echo "local   algosat_db      algosat                                 md5" | sudo tee -a /etc/postgresql/*/main/pg_hba.conf

# Restart PostgreSQL
sudo systemctl restart postgresql
```

## Step 3: Application Deployment

### Create Application User
```bash
sudo useradd --system --shell /bin/bash --home-dir /opt/algosat \
    --create-home algosat
```

### Clone Repository
```bash
sudo mkdir -p /opt/algosat
cd /opt/algosat
sudo git clone https://github.com/your-org/algosat-core.git .
sudo chown -R algosat:algosat /opt/algosat
```

### Setup Python Environment
```bash
# Switch to algosat user
sudo -u algosat bash << 'EOF'
cd /opt/algosat

# Create virtual environment
python3.11 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt
EOF
```

### Create Required Directories
```bash
sudo -u algosat mkdir -p /opt/algosat/{logs,data,config}
sudo -u algosat mkdir -p /opt/algosat/logs/{api,core,broker_monitor}
```

## Step 4: Configuration

### Create Environment Configuration
```bash
# Create main environment file
sudo -u algosat tee /opt/algosat/.env << EOF
# Database Configuration
DB_USER=algosat
DB_PASSWORD=your_secure_password_here
DB_HOST=localhost
DB_PORT=5432
DB_NAME=algosat_db

# API Configuration
API_PORT=8000

# Application Configuration
POLL_INTERVAL=10

# Security (generate secure keys in production)
ALGOSAT_MASTER_KEY=$(openssl rand -base64 32)
JWT_SECRET=$(openssl rand -base64 64)

# Telegram Notifications (optional)
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
EOF

# Set secure permissions
sudo chmod 600 /opt/algosat/.env
```

### Initialize Database Schema
```bash
sudo -u algosat bash << 'EOF'
cd /opt/algosat
source .venv/bin/activate
python -m algosat.database.init_db
EOF
```

## Step 5: PM2 Process Configuration

### Create PM2 Ecosystem File
```bash
sudo -u algosat tee /opt/algosat/ecosystem.config.js << 'EOF'
module.exports = {
  apps: [
    {
      name: 'algosat-api',
      script: '/opt/algosat/.venv/bin/python',
      args: '-m algosat.api.main',
      cwd: '/opt/algosat',
      interpreter: 'none',
      env: {
        NODE_ENV: 'production',
        PYTHONPATH: '/opt/algosat',
      },
      env_file: '/opt/algosat/config/app.env',
      log_file: '/opt/algosat/logs/api/combined.log',
      out_file: '/opt/algosat/logs/api/out.log',
      error_file: '/opt/algosat/logs/api/error.log',
      max_memory_restart: '500M',
      restart_delay: 5000,
      max_restarts: 10,
      min_uptime: '10s'
    },
    {
      name: 'algosat-main',
      script: '/opt/algosat/.venv/bin/python',
      args: '-m algosat.main',
      cwd: '/opt/algosat',
      interpreter: 'none',
      env: {
        NODE_ENV: 'production',
        PYTHONPATH: '/opt/algosat',
      },
      env_file: '/opt/algosat/config/app.env',
      log_file: '/opt/algosat/logs/core/combined.log',
      out_file: '/opt/algosat/logs/core/out.log',
      error_file: '/opt/algosat/logs/core/error.log',
      max_memory_restart: '1G',
      restart_delay: 5000,
      max_restarts: 10,
      min_uptime: '10s'
    },
    {
      name: 'broker-monitor',
      script: '/opt/algosat/.venv/bin/python',
      args: '-m algosat.brokers.monitor',
      cwd: '/opt/algosat',
      interpreter: 'none',
      env: {
        NODE_ENV: 'production',
        PYTHONPATH: '/opt/algosat',
      },
      log_file: '/opt/algosat/logs/broker_monitor/combined.log',
      out_file: '/opt/algosat/logs/broker_monitor/out.log',
      error_file: '/opt/algosat/logs/broker_monitor/error.log',
      max_memory_restart: '500M',
      restart_delay: 5000,
      max_restarts: 10,
      min_uptime: '10s'
    }
  ]
};
EOF
```

## Step 6: Start Services

### Start All Services with PM2
```bash
# Switch to algosat user and start services
sudo -u algosat bash << 'EOF'
cd /opt/algosat

# Start PM2 ecosystem
pm2 start ecosystem.config.js

# Save PM2 configuration
pm2 save

# Setup PM2 to start on boot
pm2 startup
EOF
```

### Setup PM2 Auto-start (as root)
```bash
# Run the command output by previous pm2 startup command
# It will look something like this (adjust as needed):
sudo env PATH=$PATH:/usr/bin pm2 startup systemd -u algosat --hp /opt/algosat
```

## Step 7: Verification

### Check Service Status
```bash
# Check PM2 status
sudo -u algosat pm2 status

# Check logs
sudo -u algosat pm2 logs

# Check individual service logs
sudo -u algosat pm2 logs algosat-api
sudo -u algosat pm2 logs algosat-main
sudo -u algosat pm2 logs broker-monitor
```

### Test API Endpoint
```bash
curl http://localhost:8000/health
```

### Check Database Connection
```bash
sudo -u algosat bash << 'EOF'
cd /opt/algosat
source .venv/bin/activate
python -c "from algosat.database import test_connection; test_connection()"
EOF
```

## Daily Operations

### View Service Status
```bash
sudo -u algosat pm2 status
```

### Restart Services
```bash
# Restart all services
sudo -u algosat pm2 restart all

# Restart specific service
sudo -u algosat pm2 restart algosat-api
sudo -u algosat pm2 restart algosat-main
sudo -u algosat pm2 restart broker-monitor
```

### View Logs
```bash
# Real-time logs for all services
sudo -u algosat pm2 logs

# Logs for specific service
sudo -u algosat pm2 logs algosat-api --lines 100
```

### Stop Services
```bash
# Stop all services
sudo -u algosat pm2 stop all

# Stop specific service
sudo -u algosat pm2 stop algosat-main
```

## Backup and Maintenance

### Database Backup
```bash
# Create backup script
sudo -u algosat tee /opt/algosat/scripts/backup_db.sh << 'EOF'
#!/bin/bash
BACKUP_DIR="/opt/algosat/data/backups"
DATE=$(date +%Y%m%d_%H%M%S)
mkdir -p $BACKUP_DIR
pg_dump -h localhost -U algosat algosat_db > "$BACKUP_DIR/algosat_db_$DATE.sql"
find $BACKUP_DIR -name "*.sql" -mtime +7 -delete
EOF

chmod +x /opt/algosat/scripts/backup_db.sh
```

### Setup Automated Backups
```bash
# Add to crontab
echo "0 2 * * * /opt/algosat/scripts/backup_db.sh" | sudo -u algosat crontab -
```

## Troubleshooting

### Common Issues

1. **Service won't start**: Check logs with `pm2 logs`
2. **Database connection errors**: Verify database credentials and connectivity
3. **Permission issues**: Ensure algosat user owns all files in `/opt/algosat`
4. **Memory issues**: Monitor with `pm2 monit` and adjust memory limits

### Log Locations
- PM2 logs: `/opt/algosat/logs/`
- Application logs: Check each service's log configuration
- System logs: `/var/log/syslog`

### Performance Monitoring
```bash
# Monitor system resources
sudo -u algosat pm2 monit

# Check disk usage
df -h

# Check memory usage
free -h
```

## Security Notes

- Change default passwords before production use
- Configure firewall to allow only necessary ports
- Keep system and dependencies updated
- Monitor logs for suspicious activity
- Use SSL/TLS for external connections

---

**Support**: For issues, check logs first and verify all configuration files are correct.
