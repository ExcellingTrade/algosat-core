# core/data_management.py
"""
Data management, backup, and archival system for VPS deployment.
Handles database backups, log rotation, and data retention policies.
"""
import os
import shutil
import gzip
import sqlite3
import asyncio
import aiofiles
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, List
import json
import subprocess
from dataclasses import dataclass, asdict
from common.logger import get_logger

logger = get_logger("DataManagement")

@dataclass
class BackupInfo:
    """Information about a backup."""
    backup_type: str
    filename: str
    size_bytes: int
    created_at: datetime
    checksum: str

class DatabaseBackupManager:
    """Manages PostgreSQL database backups for VPS deployment."""
    
    def __init__(self, backup_dir: str = "/opt/algosat/algosat/Files/backups"):
        self.backup_dir = Path(backup_dir)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.max_backups = 30  # Keep 30 days of backups
        
    async def create_backup(self, backup_type: str = "daily") -> Optional[BackupInfo]:
        """Create a PostgreSQL database backup."""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_filename = f"algosat_backup_{backup_type}_{timestamp}.sql.gz"
            backup_path = self.backup_dir / backup_filename
            
            # Database connection details from environment
            db_host = os.getenv("DB_HOST", "localhost")
            db_port = os.getenv("DB_PORT", "5432")
            db_name = os.getenv("DB_NAME", "algosat_db")
            db_user = os.getenv("DB_USER", "algosat_user")
            db_password = os.getenv("DB_PASSWORD", "admin123")
            
            # Create backup using pg_dump
            env = os.environ.copy()
            env["PGPASSWORD"] = db_password
            
            dump_cmd = [
                "pg_dump",
                "-h", db_host,
                "-p", db_port,
                "-U", db_user,
                "-d", db_name,
                "--no-password",
                "--verbose",
                "--clean",
                "--if-exists"
            ]
            
            # Execute pg_dump and compress
            with gzip.open(backup_path, 'wt') as gz_file:
                process = await asyncio.create_subprocess_exec(
                    *dump_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env
                )
                
                stdout, stderr = await process.communicate()
                
                if process.returncode == 0:
                    gz_file.write(stdout.decode())
                    
                    # Calculate checksum
                    checksum = await self._calculate_checksum(backup_path)
                    
                    backup_info = BackupInfo(
                        backup_type=backup_type,
                        filename=backup_filename,
                        size_bytes=backup_path.stat().st_size,
                        created_at=datetime.now(),
                        checksum=checksum
                    )
                    
                    # Save backup metadata
                    await self._save_backup_metadata(backup_info)
                    
                    logger.info(f"Database backup created: {backup_filename}")
                    return backup_info
                else:
                    logger.error(f"pg_dump failed: {stderr.decode()}")
                    if backup_path.exists():
                        backup_path.unlink()
                    return None
                    
        except Exception as e:
            logger.error(f"Failed to create database backup: {e}")
            return None
    
    async def _calculate_checksum(self, file_path: Path) -> str:
        """Calculate SHA256 checksum of backup file."""
        import hashlib
        
        sha256_hash = hashlib.sha256()
        async with aiofiles.open(file_path, "rb") as f:
            async for chunk in self._read_chunks(f):
                sha256_hash.update(chunk)
        return sha256_hash.hexdigest()
    
    async def _read_chunks(self, file_handle, chunk_size: int = 8192):
        """Read file in chunks for checksum calculation."""
        while True:
            chunk = await file_handle.read(chunk_size)
            if not chunk:
                break
            yield chunk
    
    async def _save_backup_metadata(self, backup_info: BackupInfo):
        """Save backup metadata to JSON file."""
        metadata_file = self.backup_dir / "backup_metadata.json"
        
        # Load existing metadata
        metadata = []
        if metadata_file.exists():
            async with aiofiles.open(metadata_file, 'r') as f:
                content = await f.read()
                if content:
                    metadata = json.loads(content)
        
        # Add new backup info
        backup_dict = asdict(backup_info)
        backup_dict['created_at'] = backup_info.created_at.isoformat()
        metadata.append(backup_dict)
        
        # Save updated metadata
        async with aiofiles.open(metadata_file, 'w') as f:
            await f.write(json.dumps(metadata, indent=2))
    
    async def cleanup_old_backups(self):
        """Clean up old backup files."""
        try:
            cutoff_date = datetime.now() - timedelta(days=self.max_backups)
            
            # Load metadata
            metadata_file = self.backup_dir / "backup_metadata.json"
            if not metadata_file.exists():
                return
            
            async with aiofiles.open(metadata_file, 'r') as f:
                content = await f.read()
                if not content:
                    return
                metadata = json.loads(content)
            
            # Filter out old backups
            updated_metadata = []
            for backup_info in metadata:
                created_at = datetime.fromisoformat(backup_info['created_at'])
                if created_at >= cutoff_date:
                    updated_metadata.append(backup_info)
                else:
                    # Delete old backup file
                    backup_file = self.backup_dir / backup_info['filename']
                    if backup_file.exists():
                        backup_file.unlink()
                        logger.info(f"Deleted old backup: {backup_info['filename']}")
            
            # Save updated metadata
            async with aiofiles.open(metadata_file, 'w') as f:
                await f.write(json.dumps(updated_metadata, indent=2))
                
        except Exception as e:
            logger.error(f"Failed to cleanup old backups: {e}")
    
    async def list_backups(self) -> List[BackupInfo]:
        """List all available backups."""
        try:
            metadata_file = self.backup_dir / "backup_metadata.json"
            if not metadata_file.exists():
                return []
            
            async with aiofiles.open(metadata_file, 'r') as f:
                content = await f.read()
                if not content:
                    return []
                metadata = json.loads(content)
            
            backups = []
            for backup_info in metadata:
                backup_info['created_at'] = datetime.fromisoformat(backup_info['created_at'])
                backups.append(BackupInfo(**backup_info))
            
            return sorted(backups, key=lambda x: x.created_at, reverse=True)
            
        except Exception as e:
            logger.error(f"Failed to list backups: {e}")
            return []

class LogRotationManager:
    """Manages log file rotation and compression."""
    
    def __init__(self, log_dir: str = "/opt/algosat/algosat/Files/logs"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.max_log_age_days = 30
        self.compress_after_days = 7
    
    async def rotate_logs(self):
        """Rotate and compress log files."""
        try:
            cutoff_date = datetime.now() - timedelta(days=self.max_log_age_days)
            compress_date = datetime.now() - timedelta(days=self.compress_after_days)
            
            for log_file in self.log_dir.rglob("*.log"):
                try:
                    file_mtime = datetime.fromtimestamp(log_file.stat().st_mtime)
                    
                    # Delete very old logs
                    if file_mtime < cutoff_date:
                        log_file.unlink()
                        logger.info(f"Deleted old log file: {log_file}")
                        continue
                    
                    # Compress old logs
                    if file_mtime < compress_date and not str(log_file).endswith('.gz'):
                        await self._compress_log_file(log_file)
                        
                except Exception as e:
                    logger.error(f"Error processing log file {log_file}: {e}")
                    
        except Exception as e:
            logger.error(f"Failed to rotate logs: {e}")
    
    async def _compress_log_file(self, log_file: Path):
        """Compress a log file using gzip."""
        try:
            compressed_file = log_file.with_suffix(log_file.suffix + '.gz')
            
            async with aiofiles.open(log_file, 'rb') as f_in:
                with gzip.open(compressed_file, 'wb') as f_out:
                    async for chunk in self._read_chunks(f_in):
                        f_out.write(chunk)
            
            log_file.unlink()
            logger.info(f"Compressed log file: {log_file} -> {compressed_file}")
            
        except Exception as e:
            logger.error(f"Failed to compress log file {log_file}: {e}")
    
    async def _read_chunks(self, file_handle, chunk_size: int = 8192):
        """Read file in chunks for compression."""
        while True:
            chunk = await file_handle.read(chunk_size)
            if not chunk:
                break
            yield chunk

class DataRetentionManager:
    """Manages data retention policies for trading data."""
    
    def __init__(self, db_path: str = None):
        self.db_path = db_path or os.getenv("DATABASE_URL", "")
        self.retention_policies = {
            'trade_logs': 365,      # Keep trade logs for 1 year
            'orders': 180,          # Keep orders for 6 months
            'market_data': 90,      # Keep market data for 3 months
            'system_metrics': 30,   # Keep system metrics for 1 month
            'error_logs': 60        # Keep error logs for 2 months
        }
    
    async def apply_retention_policies(self):
        """Apply data retention policies to database tables."""
        try:
            from core.db import AsyncSessionLocal
            
            async with AsyncSessionLocal() as session:
                for table, days in self.retention_policies.items():
                    await self._cleanup_table_data(session, table, days)
                    
        except Exception as e:
            logger.error(f"Failed to apply retention policies: {e}")
    
    async def _cleanup_table_data(self, session, table_name: str, retention_days: int):
        """Clean up old data from a specific table."""
        try:
            cutoff_date = datetime.now() - timedelta(days=retention_days)
            
            # This would need to be customized based on your actual table schemas
            if table_name == 'trade_logs':
                from sqlalchemy import text
                result = await session.execute(
                    text("DELETE FROM trade_logs WHERE created_at < :cutoff_date"),
                    {"cutoff_date": cutoff_date}
                )
                await session.commit()
                logger.info(f"Cleaned up {result.rowcount} old records from {table_name}")
                
        except Exception as e:
            logger.error(f"Failed to cleanup {table_name}: {e}")

class VPSDataManager:
    """Main data management coordinator for VPS deployment."""
    
    def __init__(self):
        self.backup_manager = DatabaseBackupManager()
        self.log_manager = LogRotationManager()
        self.retention_manager = DataRetentionManager()
        self._maintenance_task = None
    
    async def start_maintenance_schedule(self):
        """Start automated maintenance tasks."""
        if not self._maintenance_task:
            self._maintenance_task = asyncio.create_task(self._maintenance_loop())
            logger.info("Data maintenance schedule started")
    
    async def stop_maintenance_schedule(self):
        """Stop automated maintenance tasks."""
        if self._maintenance_task:
            self._maintenance_task.cancel()
            self._maintenance_task = None
            logger.info("Data maintenance schedule stopped")
    
    async def _maintenance_loop(self):
        """Main maintenance loop."""
        while True:
            try:
                now = datetime.now()
                
                # Daily backup at 2 AM
                if now.hour == 2 and now.minute == 0:
                    await self.backup_manager.create_backup("daily")
                    await self.backup_manager.cleanup_old_backups()
                
                # Weekly backup on Sunday at 3 AM
                if now.weekday() == 6 and now.hour == 3 and now.minute == 0:
                    await self.backup_manager.create_backup("weekly")
                
                # Log rotation daily at 1 AM
                if now.hour == 1 and now.minute == 0:
                    await self.log_manager.rotate_logs()
                
                # Data retention cleanup weekly on Monday at 4 AM
                if now.weekday() == 0 and now.hour == 4 and now.minute == 0:
                    await self.retention_manager.apply_retention_policies()
                
                # Sleep for 1 minute
                await asyncio.sleep(60)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in maintenance loop: {e}")
                await asyncio.sleep(60)
    
    async def create_manual_backup(self) -> Optional[BackupInfo]:
        """Create a manual backup."""
        return await self.backup_manager.create_backup("manual")
    
    async def get_backup_status(self) -> Dict[str, Any]:
        """Get comprehensive backup and data management status."""
        backups = await self.backup_manager.list_backups()
        
        # Calculate disk usage
        backup_size = sum(backup.size_bytes for backup in backups)
        log_size = sum(
            f.stat().st_size for f in Path("/opt/algosat/algosat/Files/logs").rglob("*") 
            if f.is_file()
        )
        
        return {
            'backup_count': len(backups),
            'latest_backup': backups[0].created_at.isoformat() if backups else None,
            'total_backup_size_mb': backup_size / (1024 * 1024),
            'total_log_size_mb': log_size / (1024 * 1024),
            'maintenance_active': self._maintenance_task is not None,
            'retention_policies': self.retention_manager.retention_policies
        }

# Global data manager instance
vps_data_manager = VPSDataManager()

async def initialize_data_management():
    """Initialize data management systems."""
    await vps_data_manager.start_maintenance_schedule()

async def shutdown_data_management():
    """Shutdown data management systems."""
    await vps_data_manager.stop_maintenance_schedule()
