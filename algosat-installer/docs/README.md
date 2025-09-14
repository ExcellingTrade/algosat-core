# 🚀 AlgoSat Installer

**One-command deployment for the AlgoSat algorithmic trading system**

## 📦 What is this?

This is a standalone installer package that completely deploys AlgoSat trading system on a fresh Ubuntu server. The installer handles everything:

- ✅ System dependencies installation
- ✅ Repository cloning and setup  
- ✅ Database configuration
- ✅ Python environment creation
- ✅ Service deployment with PM2
- ✅ Automated scheduling (cron jobs)
- ✅ Firewall configuration
- ✅ Health checks and validation

## 🔄 Migration from Existing Server

If you're migrating from an existing AlgoSat installation, follow these steps:

### Step 1: Backup Configuration from Source Server
```bash
# On your existing AlgoSat server, copy the environment configuration
sudo cp /opt/algosat/algosat/.env /tmp/algosat.env

# Optional: Copy to your home directory for easier access
sudo cp /opt/algosat/algosat/.env ~/algosat.env
sudo chown $(whoami):$(whoami) ~/algosat.env
```

### Step 2: Backup Database from Source Server
**Note**: The included backup (`database/algosat_db_backup.sql`) is from **September 14, 2025** and contains data only up to that date.

For latest data, create a fresh backup on your source server:

```bash
# Create fresh database backup on source server
sudo -u postgres pg_dump algosat_db > /tmp/algosat_db_fresh_backup.sql

# Or with custom settings (adjust DB_USER and DB_NAME as needed)
PGPASSWORD="admin123" pg_dump -U algosat_user -h localhost algosat_db > /tmp/algosat_db_fresh_backup.sql

# Verify backup was created
ls -lh /tmp/algosat_db_fresh_backup.sql
```

### Step 3: Transfer Files to New Server
```bash
# Copy environment configuration to new server
scp /tmp/algosat.env root@NEW_SERVER_IP:/tmp/

# Copy fresh database backup to new server (if you created one)
scp /tmp/algosat_db_fresh_backup.sql root@NEW_SERVER_IP:/tmp/

# Or copy from home directory
scp ~/algosat.env root@NEW_SERVER_IP:/tmp/
```

### Step 4: Run Installation
The installer will automatically detect and use these files:
- ✅ Environment config from `/tmp/algosat.env`
- ✅ Database backup from `/tmp/algosat_db_fresh_backup.sql` (if newer than included backup)

```bash
# On new server, run the installer
sudo ./install-algosat.sh
```

The installer will prompt you to choose between:
- **Included backup** (September 14, 2025): `database/algosat_db_backup.sql`
- **Fresh backup** (if available): `/tmp/algosat_db_fresh_backup.sql`

## 🎯 Quick Start (Fresh Installation)

### Option 1: Download Installer Only (Recommended)

```bash
# Download just the installer package (lightweight)
wget https://github.com/ExcellingTrade/algosat-core/archive/refs/heads/main.zip
unzip main.zip
cd algosat-core-main/algosat-installer/

# Run the installer (this will clone the full repositories)
sudo ./install-algosat.sh
```

### Option 2: Clone Full Repository

```bash
# Clone the full repository
git clone https://github.com/ExcellingTrade/algosat-core.git
cd algosat-core/algosat-installer/

# Run the installer
sudo ./install-algosat.sh
```

## 📁 Installer Contents

```
algosat-installer/
├── install-algosat.sh          # Main installation script
├── configs/
│   ├── .env                    # Environment configuration
│   └── ecosystem.config.js     # PM2 process configuration
├── scripts/
│   ├── install_cron.sh         # Cron job installer
│   ├── verify_cron_setup.sh    # Cron verification
│   └── algosat_crontab.txt     # Cron schedule definition
├── database/
│   └── algosat_db_backup.sql   # Database backup (optional restore)
└── docs/
    └── README.md               # This file
```

## ⚙️ System Requirements

- **OS**: Ubuntu 20.04+ (LTS recommended)
- **RAM**: Minimum 2GB, Recommended 4GB+
- **Storage**: Minimum 10GB free space
- **Network**: Internet connection for package downloads
- **Privileges**: Root access (sudo)

## 🔧 Pre-Installation Setup (Optional)

### Environment Variables
Set these before installation to avoid prompts:

```bash
export GITHUB_TOKEN="your_github_token_here"      # For private repos
export POSTGRES_PASSWORD="custom_postgres_pass"   # Custom postgres password
```

### Custom Database Restore
If you have a database backup, place it at `/tmp/algosat_db_backup.sql` before installation.

## 🚀 Installation Process

The installer performs these steps automatically:

1. **System Update** - Updates packages and installs dependencies
2. **Node.js & PM2** - Installs Node.js 18 LTS and PM2 process manager
3. **PostgreSQL** - Installs and configures database server
4. **Repository Cloning** - Downloads AlgoSat core and UI repositories
5. **Python Environment** - Creates virtual environment with all dependencies
6. **Database Setup** - Creates database user and optionally restores backup
7. **Configuration** - Sets up environment variables and PM2 config
8. **UI Build** - Installs dependencies and builds Next.js application
9. **Service Startup** - Starts all PM2 services
10. **Cron Jobs** - Sets up automated trading schedule
11. **Firewall** - Configures UFW firewall rules
12. **Health Checks** - Validates all services are running

## 🔄 Idempotent Design

The installer is **safe to re-run** multiple times:
- ✅ Existing repositories are updated, not re-cloned
- ✅ Database creation is skipped if already exists
- ✅ Virtual environment is reused if present
- ✅ UI build is skipped if up-to-date
- ✅ Services are restarted if already running
- ✅ Firewall rules are safely applied multiple times

## 📊 Post-Installation

### Service Management
```bash
pm2 status              # Check all services
pm2 restart all         # Restart all services
pm2 logs                # View all logs
pm2 logs algosat-api    # View specific service logs
```

### 🧪 Validation Script

**Always run validation after installation:**

```bash
cd /path/to/algosat-installer/
./validate_deployment.sh
```

**Comprehensive Validation Includes:**

1. **📁 Directory Structure**
   - AlgoSat core directory
   - Virtual environment
   - UI directory  
   - Log directories

2. **⚙️ Configuration Files**
   - Environment variables (.env)
   - PM2 ecosystem configuration
   - Security settings validation

3. **🗄️ Database Validation**
   - PostgreSQL service status
   - Database connectivity
   - Table structure verification

4. **🐍 Python Environment**
   - Python 3.12 version check
   - Package imports validation
   - Dependencies verification

5. **🔄 Process Management**
   - PM2 service status
   - All 4 processes running
   - Process health checks

6. **🌐 Network Services**
   - Port availability (3000, 8001)
   - API health endpoint
   - UI accessibility

7. **🔥 Firewall Configuration**
   - UFW status and rules
   - Required ports open
   - Security validation

8. **📅 Scheduled Tasks**
   - Cron service status
   - AlgoSat cron jobs
   - Schedule validation

9. **📊 System Resources**
   - Disk space usage
   - Memory utilization
   - Performance metrics

**Sample Validation Output:**
```bash
🔍 ═══════════════════════════════════════════════════════
   AlgoSat Deployment Validation
   2025-09-14 05:08:48
═══════════════════════════════════════════════════════

[2025-09-14 05:08:48] 📁 Validating directory structure...
[SUCCESS] ✅ AlgoSat directory exists (/opt/algosat)
[SUCCESS] ✅ AlgoSat core directory exists
[SUCCESS] ✅ Python virtual environment exists
[SUCCESS] ✅ UI directory exists

... (detailed checks) ...

═══════════════════════════════════════════════════════
📊 VALIDATION SUMMARY
═══════════════════════════════════════════════════════
✅ Passed: 33
⚠️  Warnings: 0  
❌ Failed: 0

🎉 AlgoSat deployment is fully functional!
```

### Access Points
- **UI**: `http://YOUR_SERVER_IP:3000`
- **API**: `http://YOUR_SERVER_IP:8001`
- **Health**: `http://YOUR_SERVER_IP:8001/health`

### Configuration Files
- **Environment**: `/opt/algosat/algosat/.env`
- **PM2 Config**: `/opt/algosat/algosat/ecosystem.config.js`
- **Logs**: `/opt/algosat/logs/`

### Automated Schedule
- **Market Hours**: 8:30 AM - 4:00 PM IST (Monday-Friday)
- **System Maintenance**: Midnight IST (Daily)
- **Weekend Mode**: Services stopped automatically

## 🔒 Security Configuration

### Required Updates
After installation, update these in `/opt/algosat/algosat/.env`:

```bash
# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN=your_actual_bot_token
TELEGRAM_CHAT_ID=your_actual_chat_id

# Security Keys (optional - defaults are provided)
ALGOSAT_MASTER_KEY=your_custom_master_key
JWT_SECRET=your_custom_jwt_secret
```

### Broker Credentials
Configure your broker credentials through the UI after installation.

## 🛠️ Best Practices

### Production Deployment
1. **Use a dedicated server** - Don't install on servers with other critical services
2. **Regular backups** - Set up database backup automation
3. **Monitor logs** - Check `/opt/algosat/logs/` regularly
4. **Update regularly** - Re-run installer periodically for updates
5. **Secure access** - Use SSH keys, disable password auth

### Development Setup
1. **Test on staging** - Always test installer on staging environment first
2. **Version control** - Track changes to `.env` and `ecosystem.config.js`
3. **Monitor resources** - Watch CPU/memory usage during market hours

### Troubleshooting
1. **Check logs first** - Most issues are logged in `/opt/algosat/logs/`
2. **Verify services** - Use `pm2 status` to check service health
3. **Database issues** - Check PostgreSQL status with `systemctl status postgresql`
4. **Network issues** - Verify firewall rules with `ufw status`

## 🆘 Common Issues

### Installation Fails
```bash
# Check if running as root
sudo ./install-algosat.sh

# Check disk space
df -h

# Check network connectivity
curl -I https://github.com
```

### Services Won't Start
```bash
# Check PM2 status
pm2 status

# Check logs for errors
pm2 logs

# Restart services
pm2 restart all
```

### API Not Accessible
```bash
# Check if port is open
ufw status

# Check if service is listening
netstat -tlnp | grep 8001

# Test locally
curl http://localhost:8001/health
```

## 📞 Support

For issues and support:
1. Check the logs first: `/opt/algosat/logs/`
2. Review PM2 status: `pm2 status`
3. Verify configuration: `/opt/algosat/algosat/.env`
4. Check firewall: `ufw status`

## 🔄 Updates

To update the system:
```bash
cd /path/to/algosat-installer/
./install-algosat.sh  # Safe to re-run
```

The installer will:
- Pull latest code from repositories
- Update dependencies
- Restart services
- Maintain existing configuration

---

**🚀 Happy Trading with AlgoSat!**