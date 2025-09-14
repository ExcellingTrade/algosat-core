# 🚀 AlgoSat Installer

**One-command deployment for AlgoSat algorithmic trading system**

## 🔄 Idempotent & Safe

The installer is **fully idempotent** - safe to run multiple times:

✅ **Detects existing installations** and updates instead of recreating  
✅ **Preserves data** - asks before any destructive operations  
✅ **Updates repositories** with latest code changes  
✅ **Reuses virtual environment** and database if present  
✅ **Includes comprehensive validation** after installation  

```bash
# Safe to run on existing installations
sudo ./install-algosat.sh
```

## 🔄 Migrating from Existing Server?

**Quick Migration Steps:**
```bash
# 1. On OLD server - backup config and database
sudo cp /opt/algosat/algosat/.env /tmp/algosat.env
sudo -u postgres pg_dump algosat_db > /tmp/algosat_db_fresh_backup.sql

# 2. Transfer to NEW server
scp /tmp/algosat.env root@NEW_SERVER_IP:/tmp/
scp /tmp/algosat_db_fresh_backup.sql root@NEW_SERVER_IP:/tmp/

# 3. On NEW server - run installer (auto-detects backups)
sudo ./install-algosat.sh
```

## 🎯 Fresh Installation

### Option 1: Download Installer Only (Recommended)

```bash
# Download just the installer package (lightweight)
wget https://github.com/ExcellingTrade/algosat-core/archive/refs/heads/main.zip
unzip main.zip
cd algosat-core-main/algosat-installer/

# Run the installer (this will clone the full repositories)
sudo ./install-algosat.sh
```

## What it does

✅ Complete system setup  
✅ Repository cloning & updates  
✅ Database configuration (preserves existing)  
✅ Service deployment with PM2  
✅ Automated scheduling via cron  
✅ Firewall setup  
✅ **Comprehensive validation** (34+ checks)  

## 🧪 Integrated Validation

The installer **automatically runs validation** at the end:
- ✅ **34+ comprehensive checks** including services, database, network, security
- ✅ **No separate command needed** - validation is built-in
- ✅ **Colored output** with detailed status reporting
- ✅ **Management guidance** and quick access URLs

```bash
# Validation runs automatically, but you can also run manually:
./validate_deployment.sh
```

## Post-installation

- **UI**: `http://YOUR_SERVER_IP:3000`
- **API**: `http://YOUR_SERVER_IP:8001`
- **Logs**: `/opt/algosat/logs/`

## 🧪 Test Idempotent Behavior

After installation, run the validation script to ensure everything is working:

```bash
# Run comprehensive validation
./validate_deployment.sh
```

**What it checks:**
- ✅ Directory structure & files
- ✅ Configuration files
- ✅ Database connectivity  
- ✅ Python environment
- ✅ PM2 processes
- ✅ Network services (API/UI)
- ✅ Firewall configuration
- ✅ Cron jobs
- ✅ System resources

## 📊 Service Management

```bash
pm2 status              # Check services
pm2 restart all         # Restart all
pm2 logs                # View logs
```

## Requirements

- Ubuntu 20.04+ 
- 2GB+ RAM
- Root access
- Internet connection

📖 **[Full Documentation](docs/README.md)**

---
*Safe to re-run • Idempotent • Production-ready*