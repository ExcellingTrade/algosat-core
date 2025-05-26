"""
Centralized configuration management for Algosat trading system.
Handles environment-specific settings, secrets, and dynamic configuration.
"""
import os
import json
import logging
from typing import Any, Dict, Optional, List, Union
from pathlib import Path
from dataclasses import dataclass, asdict, field
from enum import Enum

from pydantic import BaseSettings, Field, validator
from pydantic_settings import SettingsConfigDict

logger = logging.getLogger(__name__)


class Environment(str, Enum):
    """Application environments."""
    DEVELOPMENT = "development"
    TESTING = "testing"
    STAGING = "staging"
    PRODUCTION = "production"


@dataclass
class DatabaseConfig:
    """Database configuration."""
    host: str = "localhost"
    port: int = 5432
    database: str = "algosat"
    username: str = "algosat_user"
    password: str = ""
    pool_size: int = 10
    max_overflow: int = 20
    pool_timeout: int = 30
    ssl_mode: str = "prefer"
    
    @property
    def url(self) -> str:
        """Get database URL."""
        return f"postgresql+asyncpg://{self.username}:{self.password}@{self.host}:{self.port}/{self.database}"


@dataclass
class RedisConfig:
    """Redis configuration."""
    host: str = "localhost"
    port: int = 6379
    database: int = 0
    password: Optional[str] = None
    ssl: bool = False
    pool_size: int = 10
    
    @property
    def url(self) -> str:
        """Get Redis URL."""
        protocol = "rediss" if self.ssl else "redis"
        auth = f":{self.password}@" if self.password else ""
        return f"{protocol}://{auth}{self.host}:{self.port}/{self.database}"


@dataclass
class SecurityConfig:
    """Security configuration."""
    master_key: str = ""
    jwt_secret: str = ""
    jwt_expiry_hours: int = 24
    api_key_expiry_days: int = 365
    bcrypt_rounds: int = 12
    rate_limit_requests: int = 100
    rate_limit_window: int = 60
    cors_origins: List[str] = field(default_factory=lambda: ["*"])
    trusted_proxies: List[str] = field(default_factory=list)


@dataclass
class MonitoringConfig:
    """Monitoring and observability configuration."""
    enable_metrics: bool = True
    metrics_port: int = 8080
    metrics_path: str = "/metrics"
    enable_health_checks: bool = True
    health_check_interval: int = 30
    log_level: str = "INFO"
    structured_logging: bool = True
    sentry_dsn: Optional[str] = None
    prometheus_enabled: bool = True


@dataclass
class TradingConfig:
    """Trading system configuration."""
    max_concurrent_orders: int = 10
    order_timeout_seconds: int = 30
    position_size_limit: float = 100000.0
    daily_loss_limit: float = 10000.0
    circuit_breaker_threshold: int = 5
    circuit_breaker_timeout: int = 300
    retry_max_attempts: int = 3
    retry_base_delay: float = 1.0
    enable_paper_trading: bool = False
    risk_management_enabled: bool = True


@dataclass
class BrokerConfig:
    """Individual broker configuration."""
    name: str
    enabled: bool = True
    paper_trading: bool = False
    max_positions: int = 10
    position_size_limit: float = 50000.0
    api_rate_limit: int = 100
    connection_timeout: int = 30
    credentials: Dict[str, Any] = field(default_factory=dict)
    settings: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StrategyConfig:
    """Strategy configuration."""
    name: str
    enabled: bool = True
    risk_per_trade: float = 0.01
    max_positions: int = 5
    stop_loss_percent: float = 0.02
    take_profit_percent: float = 0.04
    parameters: Dict[str, Any] = field(default_factory=dict)


class AlgosatSettings(BaseSettings):
    """Main application settings using Pydantic."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        env_prefix="ALGOSAT_"
    )
    
    # Environment
    environment: Environment = Field(default=Environment.DEVELOPMENT)
    debug: bool = Field(default=False)
    
    # Application
    app_name: str = Field(default="Algosat Trading System")
    app_version: str = Field(default="1.0.0")
    api_host: str = Field(default="127.0.0.1")
    api_port: int = Field(default=8000)
    
    # Database
    db_host: str = Field(default="localhost")
    db_port: int = Field(default=5432)
    db_name: str = Field(default="algosat")
    db_user: str = Field(default="algosat_user")
    db_password: str = Field(default="")
    db_pool_size: int = Field(default=10)
    
    # Redis
    redis_host: str = Field(default="localhost")
    redis_port: int = Field(default=6379)
    redis_db: int = Field(default=0)
    redis_password: Optional[str] = Field(default=None)
    
    # Security
    master_key: str = Field(default="")
    jwt_secret: str = Field(default="")
    jwt_expiry_hours: int = Field(default=24)
    
    # Monitoring
    enable_metrics: bool = Field(default=True)
    metrics_port: int = Field(default=8080)
    log_level: str = Field(default="INFO")
    sentry_dsn: Optional[str] = Field(default=None)
    
    # Trading
    max_concurrent_orders: int = Field(default=10)
    order_timeout: int = Field(default=30)
    enable_paper_trading: bool = Field(default=False)
    
    @validator('environment')
    def validate_environment(cls, v):
        """Validate environment setting."""
        if isinstance(v, str):
            return Environment(v.lower())
        return v
    
    @validator('log_level')
    def validate_log_level(cls, v):
        """Validate log level."""
        valid_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
        if v.upper() not in valid_levels:
            raise ValueError(f"Log level must be one of: {valid_levels}")
        return v.upper()
    
    @property
    def is_production(self) -> bool:
        """Check if running in production."""
        return self.environment == Environment.PRODUCTION
    
    @property
    def is_development(self) -> bool:
        """Check if running in development."""
        return self.environment == Environment.DEVELOPMENT


class ConfigManager:
    """Centralized configuration manager."""
    
    def __init__(self, config_dir: Optional[Path] = None):
        self.config_dir = config_dir or Path(__file__).parent.parent / "config"
        self.config_dir.mkdir(exist_ok=True)
        
        # Load base settings
        self.settings = AlgosatSettings()
        
        # Load additional configurations
        self.database = self._load_database_config()
        self.redis = self._load_redis_config()
        self.security = self._load_security_config()
        self.monitoring = self._load_monitoring_config()
        self.trading = self._load_trading_config()
        self.brokers = self._load_broker_configs()
        self.strategies = self._load_strategy_configs()
        
    def _load_database_config(self) -> DatabaseConfig:
        """Load database configuration."""
        return DatabaseConfig(
            host=self.settings.db_host,
            port=self.settings.db_port,
            database=self.settings.db_name,
            username=self.settings.db_user,
            password=self.settings.db_password,
            pool_size=self.settings.db_pool_size
        )
    
    def _load_redis_config(self) -> RedisConfig:
        """Load Redis configuration."""
        return RedisConfig(
            host=self.settings.redis_host,
            port=self.settings.redis_port,
            database=self.settings.redis_db,
            password=self.settings.redis_password
        )
    
    def _load_security_config(self) -> SecurityConfig:
        """Load security configuration."""
        return SecurityConfig(
            master_key=self.settings.master_key,
            jwt_secret=self.settings.jwt_secret,
            jwt_expiry_hours=self.settings.jwt_expiry_hours
        )
    
    def _load_monitoring_config(self) -> MonitoringConfig:
        """Load monitoring configuration."""
        return MonitoringConfig(
            enable_metrics=self.settings.enable_metrics,
            metrics_port=self.settings.metrics_port,
            log_level=self.settings.log_level,
            sentry_dsn=self.settings.sentry_dsn
        )
    
    def _load_trading_config(self) -> TradingConfig:
        """Load trading configuration."""
        return TradingConfig(
            max_concurrent_orders=self.settings.max_concurrent_orders,
            order_timeout_seconds=self.settings.order_timeout,
            enable_paper_trading=self.settings.enable_paper_trading
        )
    
    def _load_broker_configs(self) -> Dict[str, BrokerConfig]:
        """Load broker configurations."""
        brokers = {}
        broker_config_file = self.config_dir / "brokers.json"
        
        if broker_config_file.exists():
            try:
                with open(broker_config_file) as f:
                    data = json.load(f)
                    for name, config in data.items():
                        brokers[name] = BrokerConfig(name=name, **config)
            except Exception as e:
                logger.error(f"Failed to load broker configs: {e}")
        
        # Ensure default brokers exist
        default_brokers = ["zerodha", "fyers", "angel"]
        for broker_name in default_brokers:
            if broker_name not in brokers:
                brokers[broker_name] = BrokerConfig(name=broker_name)
        
        return brokers
    
    def _load_strategy_configs(self) -> Dict[str, StrategyConfig]:
        """Load strategy configurations."""
        strategies = {}
        strategy_config_file = self.config_dir / "strategies.json"
        
        if strategy_config_file.exists():
            try:
                with open(strategy_config_file) as f:
                    data = json.load(f)
                    for name, config in data.items():
                        strategies[name] = StrategyConfig(name=name, **config)
            except Exception as e:
                logger.error(f"Failed to load strategy configs: {e}")
        
        return strategies
    
    def save_broker_config(self, broker_name: str, config: BrokerConfig):
        """Save broker configuration."""
        self.brokers[broker_name] = config
        self._save_broker_configs()
    
    def save_strategy_config(self, strategy_name: str, config: StrategyConfig):
        """Save strategy configuration."""
        self.strategies[strategy_name] = config
        self._save_strategy_configs()
    
    def _save_broker_configs(self):
        """Save all broker configurations to file."""
        broker_config_file = self.config_dir / "brokers.json"
        try:
            data = {name: asdict(config) for name, config in self.brokers.items()}
            with open(broker_config_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save broker configs: {e}")
    
    def _save_strategy_configs(self):
        """Save all strategy configurations to file."""
        strategy_config_file = self.config_dir / "strategies.json"
        try:
            data = {name: asdict(config) for name, config in self.strategies.items()}
            with open(strategy_config_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save strategy configs: {e}")
    
    def get_environment_config(self) -> Dict[str, Any]:
        """Get environment-specific configuration."""
        env_config_file = self.config_dir / f"{self.settings.environment.value}.json"
        
        if env_config_file.exists():
            try:
                with open(env_config_file) as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to load environment config: {e}")
        
        return {}
    
    def validate_configuration(self) -> List[str]:
        """Validate configuration and return list of issues."""
        issues = []
        
        # Validate database connection
        if not self.database.password and self.settings.environment == Environment.PRODUCTION:
            issues.append("Database password not set in production")
        
        # Validate security settings
        if not self.security.master_key:
            issues.append("Master encryption key not set")
        
        if not self.security.jwt_secret:
            issues.append("JWT secret not set")
        
        # Validate broker configurations
        enabled_brokers = [b for b in self.brokers.values() if b.enabled]
        if not enabled_brokers:
            issues.append("No brokers enabled")
        
        # Validate production settings
        if self.settings.is_production:
            if self.settings.debug:
                issues.append("Debug mode enabled in production")
            
            if self.trading.enable_paper_trading:
                issues.append("Paper trading enabled in production")
        
        return issues
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        return {
            'settings': self.settings.dict(),
            'database': asdict(self.database),
            'redis': asdict(self.redis),
            'security': asdict(self.security),
            'monitoring': asdict(self.monitoring),
            'trading': asdict(self.trading),
            'brokers': {k: asdict(v) for k, v in self.brokers.items()},
            'strategies': {k: asdict(v) for k, v in self.strategies.items()}
        }


# Global configuration manager instance
config_manager = ConfigManager()

# Convenience accessors
settings = config_manager.settings
database_config = config_manager.database
redis_config = config_manager.redis
security_config = config_manager.security
monitoring_config = config_manager.monitoring
trading_config = config_manager.trading
