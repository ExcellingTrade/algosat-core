"""
Configuration Management for Algosat Trading System.
Centralized configuration management with environment-specific settings,
validation, and secure credential handling for VPS deployment.
"""
import os
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from dataclasses import dataclass, field
from enum import Enum
import yaml
from cryptography.fernet import Fernet
import base64
from common.broker_utils import get_broker_credentials, upsert_broker_credentials
from common.default_broker_configs import DEFAULT_BROKER_CONFIGS
import asyncio

logger = logging.getLogger(__name__)


class Environment(Enum):
    """Deployment environments."""
    DEVELOPMENT = "development"
    TESTING = "testing"
    STAGING = "staging"
    PRODUCTION = "production"


class LogLevel(Enum):
    """Logging levels."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass
class DatabaseConfig:
    """Database configuration."""
    host: str = "localhost"
    port: int = 5432
    database: str = "algosat"
    username: str = "algosat_user"
    password: str = ""
    ssl_mode: str = "prefer"
    max_connections: int = 20
    connection_timeout: int = 30
    command_timeout: int = 60
    pool_recycle: int = 3600


@dataclass
class SecurityConfig:
    """Security configuration."""
    master_key: Optional[str] = None
    jwt_secret: Optional[str] = None
    jwt_expiry_minutes: int = 60  # Added JWT expiry in minutes
    api_key_expiry_days: int = 365
    session_timeout_seconds: int = 3600
    max_failed_attempts: int = 5
    lockout_duration_minutes: int = 15
    enable_ip_whitelist: bool = False
    ip_whitelist: List[str] = field(default_factory=list)
    rate_limit_requests: int = 100
    rate_limit_window_seconds: int = 60
    enable_file_monitoring: bool = True
    enable_process_monitoring: bool = True
    security_log_retention_days: int = 30


@dataclass
class BrokerConfig:
    """Broker configuration."""
    name: str
    enabled: bool = True
    api_key: str = ""
    api_secret: str = ""
    api_token: str = ""
    base_url: str = ""
    timeout_seconds: int = 30
    max_retries: int = 3
    rate_limit_per_second: int = 10
    credentials_encrypted: bool = False
    test_mode: bool = False


@dataclass
class TradingConfig:
    """Trading configuration."""
    default_quantity: int = 1
    max_position_size: int = 1000
    max_daily_loss: float = 10000.0
    max_daily_trades: int = 100
    enable_paper_trading: bool = False
    order_timeout_seconds: int = 30
    position_check_interval: int = 60
    enable_stop_loss: bool = True
    default_stop_loss_percent: float = 2.0
    enable_take_profit: bool = True
    default_take_profit_percent: float = 5.0


@dataclass
class MonitoringConfig:
    """Monitoring and observability configuration."""
    enable_metrics: bool = True
    metrics_port: int = 9090
    enable_health_checks: bool = True
    health_check_interval: int = 60
    enable_alerting: bool = True
    alert_email: str = ""
    alert_webhook_url: str = ""
    log_level: LogLevel = LogLevel.INFO
    log_file_path: str = "/opt/algosat/logs/algosat.log"
    log_retention_days: int = 30
    performance_monitoring: bool = True
    error_tracking: bool = True


@dataclass
class PerformanceConfig:
    """Performance optimization configuration."""
    enable_caching: bool = True
    cache_ttl_seconds: int = 300
    max_cache_size: int = 1000
    enable_connection_pooling: bool = True
    worker_threads: int = 4
    max_concurrent_requests: int = 100
    request_timeout_seconds: int = 30
    enable_compression: bool = True
    batch_size: int = 100


@dataclass
class BackupConfig:
    """Backup configuration."""
    enable_auto_backup: bool = True
    backup_interval_hours: int = 6
    backup_retention_days: int = 30
    backup_directory: str = "/opt/algosat/backups"
    include_logs: bool = True
    compression_enabled: bool = True
    encryption_enabled: bool = True


class ConfigurationManager:
    """Centralized configuration management."""
    
    def __init__(self, config_dir: str = "/opt/algosat/config", 
                 environment: Environment = Environment.PRODUCTION):
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.environment = environment
        
        # Configuration files
        self.main_config_file = self.config_dir / "algosat.yaml"
        self.secrets_file = self.config_dir / ".secrets"
        
        # Encryption for sensitive data
        self._init_encryption()
        
        # Load configurations
        self.database = DatabaseConfig()
        self.security = SecurityConfig()
        self.trading = TradingConfig()
        self.monitoring = MonitoringConfig()
        self.performance = PerformanceConfig()
        self.backup = BackupConfig()
        self.brokers: Dict[str, BrokerConfig] = {}
        
        self.load_configuration()
    
    def _init_encryption(self):
        """Initialize encryption for sensitive configuration data."""
        key_file = self.config_dir / ".config_key"
        
        if key_file.exists():
            with open(key_file, 'rb') as f:
                key = f.read()
        else:
            key = Fernet.generate_key()
            with open(key_file, 'wb') as f:
                f.write(key)
            os.chmod(key_file, 0o600)  # Read-only for owner
        
        self.cipher = Fernet(key)
    
    def encrypt_value(self, value: str) -> str:
        """Encrypt a sensitive configuration value."""
        return base64.urlsafe_b64encode(
            self.cipher.encrypt(value.encode())
        ).decode()
    
    def decrypt_value(self, encrypted_value: str) -> str:
        """Decrypt a sensitive configuration value."""
        return self.cipher.decrypt(
            base64.urlsafe_b64decode(encrypted_value.encode())
        ).decode()
    
    def load_configuration(self):
        """Load all configuration from files, environment variables, and database."""
        try:
            # Load main configuration
            if self.main_config_file.exists():
                with open(self.main_config_file, 'r') as f:
                    config_data = yaml.safe_load(f)
                self._apply_config_data(config_data)

            # Load broker configurations from DB (async)
            self._load_brokers_from_db()

            # Override with environment variables
            self._load_from_environment()
            # Validate configuration
            self.validate_configuration()
            logger.info(f"Configuration loaded successfully for {self.environment.value} environment")
        except Exception as e:
            logger.error(f"Failed to load configuration: {e}")
            raise

    def _load_brokers_from_db(self):
        """Load broker configurations from the database, fallback to default configs if needed."""
        loop = asyncio.get_event_loop()
        brokers = {}
        for broker_name in DEFAULT_BROKER_CONFIGS.keys():
            config = loop.run_until_complete(get_broker_credentials(broker_name))
            if not config:
                # Fallback to default config and upsert
                config = DEFAULT_BROKER_CONFIGS[broker_name]
                loop.run_until_complete(upsert_broker_credentials(broker_name, config))
            # Map DB config to BrokerConfig dataclass (flatten credentials)
            broker_cfg = BrokerConfig(
                name=broker_name,
                enabled=config.get("is_enabled", True),
                api_key=config.get("credentials", {}).get("api_key", ""),
                api_secret=config.get("credentials", {}).get("api_secret", ""),
                api_token=config.get("credentials", {}).get("api_token", ""),
                base_url=config.get("global_settings", {}).get("base_url", ""),
                timeout_seconds=config.get("global_settings", {}).get("timeout_seconds", 30),
                max_retries=config.get("global_settings", {}).get("max_retries", 3),
                rate_limit_per_second=config.get("global_settings", {}).get("rate_limit_per_second", 10),
                credentials_encrypted=False,  # DB handles encryption
                test_mode=config.get("global_settings", {}).get("test_mode", False),
            )
            brokers[broker_name] = broker_cfg
        self.brokers = brokers

    def _apply_config_data(self, config_data: Dict[str, Any]):
        """Apply configuration data to dataclass instances."""
        if not config_data:
            return
        
        # Database configuration
        if 'database' in config_data:
            db_config = config_data['database']
            for key, value in db_config.items():
                if hasattr(self.database, key):
                    setattr(self.database, key, value)
        
        # Security configuration
        if 'security' in config_data:
            sec_config = config_data['security']
            for key, value in sec_config.items():
                if hasattr(self.security, key):
                    setattr(self.security, key, value)
        
        # Trading configuration
        if 'trading' in config_data:
            trade_config = config_data['trading']
            for key, value in trade_config.items():
                if hasattr(self.trading, key):
                    setattr(self.trading, key, value)
        
        # Monitoring configuration
        if 'monitoring' in config_data:
            mon_config = config_data['monitoring']
            for key, value in mon_config.items():
                if hasattr(self.monitoring, key):
                    if key == 'log_level' and isinstance(value, str):
                        setattr(self.monitoring, key, LogLevel(value.upper()))
                    else:
                        setattr(self.monitoring, key, value)
        
        # Performance configuration
        if 'performance' in config_data:
            perf_config = config_data['performance']
            for key, value in perf_config.items():
                if hasattr(self.performance, key):
                    setattr(self.performance, key, value)
        
        # Backup configuration
        if 'backup' in config_data:
            backup_config = config_data['backup']
            for key, value in backup_config.items():
                if hasattr(self.backup, key):
                    setattr(self.backup, key, value)
    
    def _load_from_environment(self):
        """Load configuration from environment variables."""
        # Database
        self.database.host = os.getenv('DB_HOST', self.database.host)
        self.database.port = int(os.getenv('DB_PORT', str(self.database.port)))
        self.database.database = os.getenv('DB_NAME', self.database.database)
        self.database.username = os.getenv('DB_USER', self.database.username)
        self.database.password = os.getenv('DB_PASSWORD', self.database.password)
        
        # Security
        self.security.master_key = os.getenv('ALGOSAT_MASTER_KEY', self.security.master_key)
        self.security.jwt_secret = os.getenv('JWT_SECRET', self.security.jwt_secret)
        self.security.jwt_expiry_minutes = int(os.getenv('JWT_EXPIRY_MINUTES', str(self.security.jwt_expiry_minutes))) # Added loading for JWT expiry
        self.security.enable_ip_whitelist = os.getenv('ENABLE_IP_WHITELIST', 'false').lower() == 'true'
        
        if os.getenv('IP_WHITELIST'):
            self.security.ip_whitelist = [ip.strip() for ip in os.getenv('IP_WHITELIST').split(',')]
        
        # Trading
        self.trading.enable_paper_trading = os.getenv('PAPER_TRADING', 'false').lower() == 'true'
        
        # Monitoring
        log_level = os.getenv('LOG_LEVEL', self.monitoring.log_level.value)
        try:
            self.monitoring.log_level = LogLevel(log_level.upper())
        except ValueError:
            logger.warning(f"Invalid log level: {log_level}")
        
        self.monitoring.alert_email = os.getenv('ALERT_EMAIL', self.monitoring.alert_email)
        self.monitoring.alert_webhook_url = os.getenv('ALERT_WEBHOOK_URL', self.monitoring.alert_webhook_url)
    
    def validate_configuration(self) -> List[str]:
        """Validate the current configuration and return any issues."""
        issues = []
        
        # Database validation
        if not self.database.password:
            issues.append("Database password not configured")
        
        if self.database.max_connections < 1:
            issues.append("Database max_connections must be at least 1")
        
        # Security validation
        if not self.security.master_key:
            issues.append("Master encryption key not configured")
        
        if not self.security.jwt_secret or len(self.security.jwt_secret) < 32:
            issues.append("JWT secret not configured or too short (minimum 32 characters)") # Updated message
        
        if self.security.jwt_expiry_minutes <= 0: # Added validation for expiry
            issues.append("JWT expiry minutes must be positive")

        if self.security.max_failed_attempts < 1:
            issues.append("max_failed_attempts must be at least 1")
        
        # Trading validation
        if self.trading.max_position_size <= 0:
            issues.append("max_position_size must be positive")
        
        if self.trading.max_daily_loss <= 0:
            issues.append("max_daily_loss must be positive")
        
        # Broker validation
        enabled_brokers = [name for name, config in self.brokers.items() if config.enabled]
        if not enabled_brokers:
            issues.append("No brokers are enabled")
        
        for broker_name, broker_config in self.brokers.items():
            if broker_config.enabled:
                if not broker_config.api_key:
                    issues.append(f"API key not configured for broker: {broker_name}")
                if not broker_config.base_url:
                    issues.append(f"Base URL not configured for broker: {broker_name}")
        
        # Performance validation
        if self.performance.worker_threads < 1:
            issues.append("worker_threads must be at least 1")
        
        if self.performance.max_concurrent_requests < 1:
            issues.append("max_concurrent_requests must be at least 1")
        
        if issues:
            logger.warning(f"Configuration validation found {len(issues)} issues: {issues}")
        
        return issues
    
    def save_configuration(self):
        """Save current configuration to files (excluding broker config, which is DB-managed)."""
        try:
            # Prepare main configuration data
            main_config = {
                'environment': self.environment.value,
                'database': {
                    'host': self.database.host,
                    'port': self.database.port,
                    'database': self.database.database,
                    'username': self.database.username,
                    'ssl_mode': self.database.ssl_mode,
                    'max_connections': self.database.max_connections,
                    'connection_timeout': self.database.connection_timeout,
                    'command_timeout': self.database.command_timeout,
                    'pool_recycle': self.database.pool_recycle
                },
                'security': {
                    'jwt_secret': 'YOUR_SECURE_JWT_SECRET_REPLACE_ME',
                    'jwt_expiry_minutes': self.security.jwt_expiry_minutes,
                    'api_key_expiry_days': self.security.api_key_expiry_days,
                    'session_timeout_seconds': self.security.session_timeout_seconds,
                    'max_failed_attempts': self.security.max_failed_attempts,
                    'lockout_duration_minutes': self.security.lockout_duration_minutes,
                    'enable_ip_whitelist': self.security.enable_ip_whitelist,
                    'ip_whitelist': self.security.ip_whitelist,
                    'rate_limit_requests': self.security.rate_limit_requests,
                    'rate_limit_window_seconds': self.security.rate_limit_window_seconds,
                    'enable_file_monitoring': self.security.enable_file_monitoring,
                    'enable_process_monitoring': self.security.enable_process_monitoring,
                    'security_log_retention_days': self.security.security_log_retention_days
                },
                'trading': {
                    'default_quantity': self.trading.default_quantity,
                    'max_position_size': self.trading.max_position_size,
                    'max_daily_loss': self.trading.max_daily_loss,
                    'max_daily_trades': self.trading.max_daily_trades,
                    'enable_paper_trading': self.trading.enable_paper_trading,
                    'order_timeout_seconds': self.trading.order_timeout_seconds,
                    'position_check_interval': self.trading.position_check_interval,
                    'enable_stop_loss': self.trading.enable_stop_loss,
                    'default_stop_loss_percent': self.trading.default_stop_loss_percent,
                    'enable_take_profit': self.trading.enable_take_profit,
                    'default_take_profit_percent': self.trading.default_take_profit_percent
                },
                'monitoring': {
                    'enable_metrics': self.monitoring.enable_metrics,
                    'metrics_port': self.monitoring.metrics_port,
                    'enable_health_checks': self.monitoring.enable_health_checks,
                    'health_check_interval': self.monitoring.health_check_interval,
                    'enable_alerting': self.monitoring.enable_alerting,
                    'log_level': self.monitoring.log_level.value,
                    'log_file_path': self.monitoring.log_file_path,
                    'log_retention_days': self.monitoring.log_retention_days,
                    'performance_monitoring': self.monitoring.performance_monitoring,
                    'error_tracking': self.monitoring.error_tracking
                },
                'performance': {
                    'enable_caching': self.performance.enable_caching,
                    'cache_ttl_seconds': self.performance.cache_ttl_seconds,
                    'max_cache_size': self.performance.max_cache_size,
                    'enable_connection_pooling': self.performance.enable_connection_pooling,
                    'worker_threads': self.performance.worker_threads,
                    'max_concurrent_requests': self.performance.max_concurrent_requests,
                    'request_timeout_seconds': self.performance.request_timeout_seconds,
                    'enable_compression': self.performance.enable_compression,
                    'batch_size': self.performance.batch_size
                },
                'backup': {
                    'enable_auto_backup': self.backup.enable_auto_backup,
                    'backup_interval_hours': self.backup.backup_interval_hours,
                    'backup_retention_days': self.backup.backup_retention_days,
                    'backup_directory': self.backup.backup_directory,
                    'include_logs': self.backup.include_logs,
                    'compression_enabled': self.backup.compression_enabled,
                    'encryption_enabled': self.backup.encryption_enabled
                }
            }
            
            # Save main configuration
            with open(self.main_config_file, 'w') as f:
                yaml.dump(main_config, f, default_flow_style=False, sort_keys=False)
            
            os.chmod(self.main_config_file, 0o644)
            logger.info("Configuration saved successfully (excluding broker config, which is DB-managed)")
        except Exception as e:
            logger.error(f"Failed to save configuration: {e}")
            raise
    
    def get_broker_config(self, broker_name: str) -> Optional[BrokerConfig]:
        """Get configuration for a specific broker."""
        return self.brokers.get(broker_name)
    
    def add_broker_config(self, broker_config: BrokerConfig):
        """Add or update a broker configuration."""
        self.brokers[broker_config.name] = broker_config
        logger.info(f"Added/updated broker configuration: {broker_config.name}")
    
    def remove_broker_config(self, broker_name: str):
        """Remove a broker configuration."""
        if broker_name in self.brokers:
            del self.brokers[broker_name]
            logger.info(f"Removed broker configuration: {broker_name}")
    
    def get_config_summary(self) -> Dict[str, Any]:
        """Get a summary of the current configuration."""
        return {
            'environment': self.environment.value,
            'database': {
                'host': self.database.host,
                'port': self.database.port,
                'database': self.database.database,
                'max_connections': self.database.max_connections
            },
            'security': {
                'enable_ip_whitelist': self.security.enable_ip_whitelist,
                'ip_whitelist_count': len(self.security.ip_whitelist),
                'rate_limit_requests': self.security.rate_limit_requests,
                'security_features_enabled': {
                    'file_monitoring': self.security.enable_file_monitoring,
                    'process_monitoring': self.security.enable_process_monitoring
                }
            },
            'trading': {
                'paper_trading': self.trading.enable_paper_trading,
                'max_position_size': self.trading.max_position_size,
                'max_daily_loss': self.trading.max_daily_loss,
                'risk_management': {
                    'stop_loss': self.trading.enable_stop_loss,
                    'take_profit': self.trading.enable_take_profit
                }
            },
            'brokers': {
                'total_count': len(self.brokers),
                'enabled_count': sum(1 for config in self.brokers.values() if config.enabled),
                'broker_names': list(self.brokers.keys())
            },
            'monitoring': {
                'log_level': self.monitoring.log_level.value,
                'metrics_enabled': self.monitoring.enable_metrics,
                'alerting_enabled': self.monitoring.enable_alerting,
                'performance_monitoring': self.monitoring.performance_monitoring
            },
            'performance': {
                'caching_enabled': self.performance.enable_caching,
                'connection_pooling': self.performance.enable_connection_pooling,
                'worker_threads': self.performance.worker_threads,
                'max_concurrent_requests': self.performance.max_concurrent_requests
            },
            'backup': {
                'auto_backup': self.backup.enable_auto_backup,
                'backup_interval_hours': self.backup.backup_interval_hours,
                'retention_days': self.backup.backup_retention_days,
                'encryption_enabled': self.backup.encryption_enabled
            }
        }


# Create default configuration templates
def create_default_configs(config_dir: str = "/opt/algosat/config"):
    """Create default configuration files if they don't exist."""
    config_path = Path(config_dir)
    config_path.mkdir(parents=True, exist_ok=True)
    
    # Create default main config
    main_config_file = config_path / "algosat.yaml"
    if not main_config_file.exists():
        default_config = {
            'environment': 'production',
            'database': {
                'host': 'localhost',
                'port': 5432,
                'database': 'algosat',
                'username': 'algosat_user',
                'ssl_mode': 'prefer',
                'max_connections': 20
            },
            'security': {
                'jwt_secret': '!!!REPLACE_WITH_A_STRONG_SECRET_KEY_MIN_32_CHARS!!!', # Added to default config
                'jwt_expiry_minutes': 60, # Added to default config
                'api_key_expiry_days': 365,
                'session_timeout_seconds': 3600,
                'max_failed_attempts': 5,
                'lockout_duration_minutes': 15,
                'rate_limit_requests': 100,
                'rate_limit_window_seconds': 60
            },
            'trading': {
                'default_quantity': 1,
                'max_position_size': 1000,
                'max_daily_loss': 10000.0,
                'enable_paper_trading': False,
                'enable_stop_loss': True,
                'default_stop_loss_percent': 2.0
            },
            'monitoring': {
                'enable_metrics': True,
                'log_level': 'INFO',
                'log_retention_days': 30,
                'performance_monitoring': True
            }
        }
        
        with open(main_config_file, 'w') as f:
            yaml.dump(default_config, f, default_flow_style=False)
    
    logger.info(f"Default configuration files created in {config_dir}")
