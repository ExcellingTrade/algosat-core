# algosat/core/schema.py

from sqlalchemy import (
    MetaData, Table, Column, Integer, String, Boolean,
    JSON, DateTime, ForeignKey, text, UniqueConstraint, Index, Float, Numeric
)
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()

strategies = Table(
    "strategies", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("key", String, nullable=False, unique=True),  # e.g. OptionBuy, OptionSell, SwingHighLow
    Column("name", String, nullable=False),
    Column("description", String, nullable=True),
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
    Column("name", String, nullable=False),  # Added name
    Column("description", String, nullable=True),  # Added description
    Column("exchange", String, nullable=False),
    Column("instrument", String, nullable=True),
    Column("trade", JSON, nullable=False, server_default=text("'{}'::jsonb")),
    Column("indicators", JSON, nullable=False, server_default=text("'{}'::jsonb")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),

    UniqueConstraint("strategy_id", "name", name="uq_strategy_config_name_per_strategy"),
)


strategy_symbols = Table(
    "strategy_symbols", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("strategy_id", Integer, ForeignKey("strategies.id"), nullable=False),
    Column("symbol", String, nullable=False),
    Column("config_id", Integer, ForeignKey("strategy_configs.id"), nullable=False),
    Column("status", String, nullable=True, server_default=text("'active'")),
    Column("enable_smart_levels", Boolean, nullable=False, server_default=text("false")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),

    UniqueConstraint("strategy_id", "symbol", name="uq_strategy_symbol"),
    Index("ix_strategy_symbol_strategy_symbol_config_status", "strategy_id", "symbol", "config_id", "status"),
)

# Smart Level Strategy table
smart_levels = Table(
    "smart_levels", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("strategy_symbol_id", Integer, ForeignKey("strategy_symbols.id"), nullable=False, index=True),
    Column("name", String, nullable=False),
    Column("is_active", Boolean, nullable=False, server_default=text("true")),
    Column("entry_level", Float, nullable=False),
    Column("bullish_target", Float, nullable=True),
    Column("bearish_target", Float, nullable=True),
    Column("initial_lot_ce", Integer, nullable=True),
    Column("initial_lot_pe", Integer, nullable=True),
    Column("remaining_lot_ce", Integer, nullable=True),
    Column("remaining_lot_pe", Integer, nullable=True),
    Column("ce_buy_enabled", Boolean, nullable=False, server_default=text("false")),
    Column("ce_sell_enabled", Boolean, nullable=False, server_default=text("false")),
    Column("pe_buy_enabled", Boolean, nullable=False, server_default=text("false")),
    Column("pe_sell_enabled", Boolean, nullable=False, server_default=text("false")),
    Column("max_trades", Integer, nullable=True),
    Column("max_loss_trades", Integer, nullable=True),
    Column("pullback_percentage", Float, nullable=True),
    Column("notes", String, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
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
        "status",
        String,
        nullable=False,
        server_default=text("'DISCONNECTED'")
    ),
    Column(
        "last_auth_check",
        DateTime(timezone=True),
        nullable=True
    ),
    Column(
        "notes",
        String,
        nullable=True,
        server_default=text("''")
    ),
    Column(
        "max_loss",
        Numeric(15, 2),
        nullable=False,
        server_default=text("10000.0")
    ),
    Column(
        "max_profit",
        Numeric(15, 2),
        nullable=False,
        server_default=text("50000.0")
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
    Column("strategy_symbol_id", Integer, ForeignKey("strategy_symbols.id"), nullable=False, index=True),
    Column("strike_symbol", String(100), nullable=True, index=True),  # NEW: Actual tradeable symbol (e.g., "NSE:NIFTY50-25JUN25-23400-CE")
    Column("pnl", Numeric(15, 2), nullable=True, index=True),  # NEW: Profit/Loss for this order
    Column("candle_range",  Float, nullable=True),
    Column("entry_price",  Float, nullable=True),
    Column("stop_loss",  Float, nullable=True),
    Column("target_price",  Float, nullable=True),
    Column("orig_target", Float, nullable=True),  # NEW: Original target price, optional
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
    Column("signal_direction", String, nullable=True),  # UP/DOWN direction of the signal
    Column("qty", Integer, nullable=True),
    Column("executed_quantity", Integer, nullable=False), 
    # Spot and swing/level tracking fields
    Column("entry_spot_price", Float, nullable=True),
    Column("entry_spot_swing_high", Float, nullable=True),
    Column("entry_spot_swing_low", Float, nullable=True),
    Column("stoploss_spot_level", Float, nullable=True),
    Column("target_spot_level", Float, nullable=True),
    Column("entry_rsi", Float, nullable=True),  # RSI level at the time of entry
    Column("expiry_date", DateTime(timezone=True), nullable=True),  # NEW: Option expiry date
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
)

# Broker executions table: one row per actual execution (ENTRY/EXIT)
# Each actual fill/execution from broker gets a separate row
broker_executions = Table(
    "broker_executions", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("parent_order_id", Integer, ForeignKey("orders.id"), nullable=False, index=True),
    Column("broker_id", Integer, ForeignKey("broker_credentials.id"), nullable=False, index=True),
    
    # Core execution details - one execution per row
    Column("broker_order_id", String(100), nullable=False, index=True),  # Single broker order ID for this execution
    Column("side", String(10), nullable=False, index=True),  # 'ENTRY' or 'EXIT'
    Column("action", String(20), nullable=False, server_default=text("'BUY'")),  # NEW: Action column (BUY/SELL/EXIT/etc.)
    Column("execution_price", Numeric(15, 4), nullable=False),  # Actual traded price for this execution
    Column("executed_quantity", Integer, nullable=False),  # Actual executed quantity for this execution
    Column("execution_time", DateTime(timezone=True), nullable=True),  # When this execution happened
    Column("symbol", String(100), nullable=True),  # Symbol for this execution (useful for hedge orders)

    # Status and tracking
    Column("status", String(50), nullable=False, index=True),  # FILLED, PARTIAL, CANCELLED, etc.
    Column("order_type", String(20), nullable=True),  # MARKET, LIMIT, SL, etc.
    Column("product_type", String(20), nullable=True),  # MARKET, LIMIT, SL, etc.
    Column("notes", String(500), nullable=True),  # Any additional notes (manual exit, BO leg, etc.)

    # Legacy and raw data
    Column("raw_execution_data", JSONB, nullable=True),  # Complete broker response for this execution
    Column("order_messages", JSONB, nullable=True),  # Any messages related to this execution

    # Deprecated fields - keep for migration compatibility
    Column("broker_name", String, nullable=True),  # Deprecated: use broker_id
    # Column("broker_order_ids", JSONB, nullable=True),  # Deprecated: now single broker_order_id
    # Column("order_status_map", JSONB, nullable=True),  # Deprecated: status per execution
    # Column("raw_response", JSONB, nullable=True),  # Deprecated: use raw_execution_data

    Column("quantity", Integer, nullable=True),  # NEW: quantity column

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