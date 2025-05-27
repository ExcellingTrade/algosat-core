# algosat/core/schema.py

from sqlalchemy import (
    MetaData, Table, Column, Integer, String, Boolean,
    JSON, DateTime, ForeignKey, text, UniqueConstraint, Index, Float
)

metadata = MetaData()

strategies = Table(
    "strategies", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("key", String, nullable=False, unique=True),  # e.g. OptionBuy, OptionSell, SwingHighLow
    Column("name", String, nullable=False),
    Column("enabled", Boolean, nullable=False, server_default=text("true")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
)

strategy_configs = Table(
    "strategy_configs", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("strategy_id", Integer, ForeignKey("strategies.id"), nullable=False),
    Column("symbol", String, nullable=False),
    Column("exchange", String, nullable=False),
    Column("instrument", String, nullable=True),
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

orders = Table(
    "orders", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("strategy_config_id", Integer, ForeignKey("strategy_configs.id"), nullable=False, index=True),
    Column("broker_id", Integer, ForeignKey("broker_credentials.id"), nullable=False, index=True),
    Column("symbol", String, nullable=False, index=True),
    Column("candle_range",  String, nullable=True),
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
    Column("side", String, nullable=True),  # Changed from Integer to String for broker-agnostic side
    Column("order_ids", JSON, nullable=False, server_default=text("'[]'::jsonb")),
    Column("order_messages", JSON, nullable=False, server_default=text("'{}'::jsonb")),
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