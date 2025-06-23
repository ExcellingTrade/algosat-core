# algosat/core/schema.py

from sqlalchemy import (
    MetaData, Table, Column, Integer, String, Boolean,
    JSON, DateTime, ForeignKey, text, UniqueConstraint, Index, Float
)
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()

strategies = Table(
    "strategies", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("key", String, nullable=False, unique=True),  # e.g. OptionBuy, OptionSell, SwingHighLow
    Column("name", String, nullable=False),
    Column("order_type", String, nullable=False, server_default=text("'MARKET'"),
           info={"choices": ["MARKET", "LIMIT"]}),
    Column("product_type", String, nullable=False, server_default=text("'INTRADAY'"),
           info={"choices": ["INTRADAY", "DELIVERY"]}),
    Column("enabled", Boolean, nullable=False, server_default=text("true")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),

    # Add CHECK constraints for allowed values
    # (Postgres syntax, adjust if using another DB)
    # Note: SQLAlchemy's CheckConstraint can be used for cross-db support
)

strategy_configs = Table(
    "strategy_configs", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("strategy_id", Integer, ForeignKey("strategies.id"), nullable=False),
    Column("symbol", String, nullable=False),
    Column("exchange", String, nullable=False),
    Column("instrument", String, nullable=True),
    Column("product_type", String, nullable=False, server_default=text("'INTRADAY'")),  # "INTRADAY" or "DELIVERY"
    Column("trade", JSON, nullable=False, server_default=text("'{}'::jsonb")),
    Column("indicators", JSON, nullable=False, server_default=text("'{}'::jsonb")),
    Column("is_default", Boolean, nullable=False, server_default=text("false")),
    Column("enabled", Boolean, nullable=False, server_default=text("true")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),

    UniqueConstraint("strategy_id", "symbol", "is_default",
                     name="uq_strategy_symbol_default"),
    Index("ix_stratcfg_strategy_symbol_enabled_updated", 
          "strategy_id", "symbol", "enabled", "updated_at"),
)

trade_logs = Table(
    "trade_logs", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("config_id", Integer, ForeignKey("strategy_configs.id"), nullable=False),
    Column("timestamp", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("order_type", String, nullable=False),
    Column("qty", Integer, nullable=False),
    Column("price", JSON, nullable=False),
    Column("status", String, nullable=False),
    Column("raw_response", JSON),
)

broker_credentials = Table(
    "broker_credentials", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("broker_name", String, nullable=False, unique=True),
    Column(
        "credentials",
        JSON,
        nullable=False,
        server_default=text("'{}'::jsonb")
    ),
    Column(
        "required_auth_fields",
        JSON,
        nullable=False,
        server_default=text("'[]'::jsonb")
    ),
    Column(
        "is_enabled",
        Boolean,
        nullable=False,
        server_default=text("false")
    ),
    Column(
        "data_source_priority",
        Integer,
        nullable=False,
        server_default=text("0")
    ),
    Column(
        "trade_execution_enabled",
        Boolean,
        nullable=False,
        server_default=text("false")
    ),
    Column(
        "is_data_provider",
        Boolean,
        nullable=False,
        server_default=text("false")
    ),
    Column(
        "notes",
        String,
        nullable=True,
        server_default=text("''")
    ),
    Column(
        "global_settings",
        JSON,
        nullable=False,
        server_default=text("'{}'::jsonb")
    ),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()")
    ),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()")
    ),
)

# Ensure only one broker can be marked as the data provider
Index(
    "uq_single_data_provider",
    broker_credentials.c.is_data_provider,
    unique=True,
    postgresql_where=text("is_data_provider = true"),
)

# Orders table: logical orders (no broker-specific info)
orders = Table(
    "orders", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("strategy_config_id", Integer, ForeignKey("strategy_configs.id"), nullable=False, index=True),
    Column("symbol", String, nullable=False, index=True),
    Column("candle_range",  Float, nullable=True),
    Column("entry_price",  Float, nullable=True),
    Column("stop_loss",  Float, nullable=True),
    Column("target_price",  Float, nullable=True),
    Column("signal_time", DateTime(timezone=True), nullable=True),
    Column("entry_time", DateTime(timezone=True), nullable=True),
    Column("exit_time", DateTime(timezone=True), nullable=True),
    Column("exit_price", Float, nullable=True),
    Column("status", String, nullable=False, index=True),
    Column("reason", String, nullable=True),
    Column("atr", Float, nullable=True),
    Column("supertrend_signal", String, nullable=True),
    Column("lot_qty", Integer, nullable=True),
    Column("side", String, nullable=True),
    Column("qty", Integer, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
)

# Broker executions table: one row per broker per order
broker_executions = Table(
    "broker_executions", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("parent_order_id", Integer, ForeignKey("orders.id"), nullable=False, index=True),  # renamed from order_id
    Column("broker_id", Integer, ForeignKey("broker_credentials.id"), nullable=False, index=True),
    # Deprecated: broker_name, keep for migration only
    Column("broker_name", String, nullable=True, index=True),
    Column("broker_order_ids", JSONB, nullable=True),  # Broker's order ids (list)
    Column("order_status_map", JSONB, nullable=True),  # {order_id: status}
    Column("order_messages", JSONB, nullable=True),
    Column("status", String, nullable=False, index=True),
    Column("raw_response", JSONB, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
)

users = Table(
    "users", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("username", String, nullable=False, unique=True),
    Column("email", String, nullable=False, unique=True),
    Column("hashed_password", String, nullable=False),
    Column("full_name", String, nullable=True),
    Column("is_active", Boolean, nullable=False, server_default=text("true")),
    Column("role", String, nullable=False, server_default=text("'user'")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
)

broker_balance_summaries = Table(
    "broker_balance_summaries", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("broker_id", Integer, ForeignKey("broker_credentials.id"), nullable=False, index=True),
    Column("summary", JSON, nullable=False),  # Stores the full balance summary as returned by get_balance_summary
    Column("date", DateTime(timezone=True), nullable=False),  # Date (midnight) for the entry
    Column("fetched_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint("broker_id", "date", name="uq_broker_balance_brokerid_date"),
    Index("ix_broker_balance_brokerid_date", "broker_id", "date"),
)

# NOTE: The migrations folder is deprecated and will be removed as per current development workflow.
# All schema changes should be handled by dropping and recreating tables during development.