# algosat/core/db.py

try:
    from algosat.config import settings
except ModuleNotFoundError as e:
    raise ImportError(
        "Could not import 'settings' from 'algosat.config'. "
        "Make sure you are running your app from the project root with 'python -m algosat.api.enhanced_app' or 'python -m algosat.main'. "
        f"Original error: {e}"
    )

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import inspect, Table, MetaData, update, select, delete, func, text, and_, case # Modified import

import os
from datetime import datetime, timezone  # moved to top
from algosat.common.default_strategy_configs import DEFAULT_STRATEGY_CONFIGS
from algosat.core.time_utils import get_ist_now

from algosat.core.dbschema import metadata, orders, broker_credentials, strategies, strategy_configs, strategy_symbols, users, broker_balance_summaries # Added users, broker_balance_summaries

# 1) Create the Async Engine
engine = create_async_engine(
    str(settings.database_url),  # Use the unified config object
    echo=False,        # Set True during dev to see SQL queries
    pool_size=5,       
    max_overflow=10,   # extra connections beyond pool_size
)

# 2) Create a session factory
AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,  # keep objects alive after commit
)

# Database session getter for backward compatibility
def get_database_session():
    """
    Get a database session. Use this in async context managers.
    Example:
        async with get_database_session() as session:
            # Your database operations
    """
    return AsyncSessionLocal()

async def has_table(table_name: str) -> bool:
    """
    Check if a table exists in the database.
    """
    async with engine.begin() as conn:
        # Use inspect to check for table existence
        return await conn.run_sync(lambda sync_conn: inspect(sync_conn).has_table(table_name))

async def list_tables() -> list[str]:
    """
    List all tables in the database.
    """
    async with engine.begin() as conn:
        return await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())

async def create_table_ddl(table_to_create: Table) -> None:
    """
    Create the specified table in the database.
    The table_to_create argument must be a SQLAlchemy Table object.
    Example:
        from sqlalchemy import MetaData, Table, Column, Integer, String
        metadata_obj = MetaData()
        my_sample_table = Table(
            "my_sample_table",
            metadata_obj,
            Column("id", Integer, primary_key=True),
            Column("name", String(50)),
        )
        # await create_table_ddl(my_sample_table)
    """
    async with engine.begin() as conn:
        await conn.run_sync(table_to_create.create, checkfirst=True)

async def drop_table_ddl(table_to_drop: Table) -> None:
    """
    Drop the specified table from the database.
    The table_to_drop argument must be a SQLAlchemy Table object.
    Warning: This is a destructive operation.
    Example:
        # Assuming my_sample_table is a SQLAlchemy Table object defined elsewhere
        # await drop_table_ddl(my_sample_table)
    """
    async with engine.begin() as conn:
        await conn.run_sync(table_to_drop.drop, checkfirst=True)

async def update_rows_in_table(
    target_table: Table,
    condition: any,  # SQLAlchemy boolean clause (e.g., target_table.c.id == 1)
    new_values: dict # e.g., {"name": "new name"}
) -> None:
    """
    Update rows in the specified table that match the condition.
    Args:
        target_table: SQLAlchemy Table object.
        condition: A SQLAlchemy boolean clause element for the WHERE condition.
                   Example: target_table.c.id == 1
        new_values: A dictionary of column names to new values.
                    Example: {"name": "Updated Name"}
    Example:
        # Assuming my_sample_table is a SQLAlchemy Table object defined elsewhere
        # condition = my_sample_table.c.id == 10
        # await update_rows_in_table(my_sample_table, condition, {"name": "A New Value"})
    """
    stmt = update(target_table).where(condition).values(new_values)
    async with engine.begin() as conn:
        await conn.execute(stmt)
        # For information: result.rowcount would give the number of affected rows



# --- Async database initialization ---
async def init_db() -> None:
    """
    Create all tables and indexes defined on metadata if they do not exist.
    Uses the AsyncEngine to run the creation in a transaction.
    """
    async with engine.begin() as conn:
        # metadata.create_all will issue CREATE TABLE IF NOT EXISTS and create indexes
        await conn.run_sync(metadata.create_all)

# --- Broker CRUD ---
async def get_all_brokers(session):
    result = await session.execute(select(broker_credentials))
    return [dict(row._mapping) for row in result.fetchall()]

async def get_broker_by_name(session, broker_name):
    result = await session.execute(select(broker_credentials).where(broker_credentials.c.broker_name == broker_name))
    row = result.first()
    return dict(row._mapping) if row else None

async def add_broker(session, broker_data):
    stmt = broker_credentials.insert().values(**broker_data)
    res = await session.execute(stmt)
    await session.commit()
    broker_id = res.inserted_primary_key[0]
    result = await session.execute(select(broker_credentials).where(broker_credentials.c.id == broker_id))
    row = result.first()
    return dict(row._mapping) if row else None

async def update_broker(session, broker_name, update_data):
    stmt = (
        update(broker_credentials)
        .where(broker_credentials.c.broker_name == broker_name)
        .values(**update_data)
    )
    await session.execute(stmt)
    await session.commit()
    result = await session.execute(select(broker_credentials).where(broker_credentials.c.broker_name == broker_name))
    row = result.first()
    return dict(row._mapping) if row else None

async def delete_broker(session, broker_name):
    stmt = delete(broker_credentials).where(broker_credentials.c.broker_name == broker_name)
    await session.execute(stmt)
    await session.commit()
    return True

async def get_broker_by_id(session, broker_id):
    from algosat.core.dbschema import broker_credentials
    result = await session.execute(select(broker_credentials).where(broker_credentials.c.id == broker_id))
    row = result.first()
    return dict(row._mapping) if row else None

# --- Strategy Config CRUD ---
async def get_all_strategy_configs(session):
    result = await session.execute(select(strategy_configs))
    return [dict(row._mapping) for row in result.fetchall()]

async def get_strategy_config_by_id(session, config_id):
    result = await session.execute(select(strategy_configs).where(strategy_configs.c.id == config_id))
    row = result.first()
    return dict(row._mapping) if row else None

async def update_strategy_config(session, config_id, update_data):
    stmt = update(strategy_configs).where(strategy_configs.c.id == config_id).values(**update_data)
    await session.execute(stmt)
    await session.commit()
    result = await session.execute(select(strategy_configs).where(strategy_configs.c.id == config_id))
    row = result.first()
    return dict(row._mapping) if row else None

async def create_strategy_config(session, strategy_id, config_data):
    """
    Create a new strategy config.
    """
    from algosat.core.dbschema import strategy_configs
    
    now = get_ist_now()
    config_data.update({
        'strategy_id': strategy_id,
        'created_at': now,
        'updated_at': now
    })
    
    stmt = strategy_configs.insert().values(**config_data)
    res = await session.execute(stmt)
    await session.commit()
    
    config_id = res.inserted_primary_key[0]
    result = await session.execute(select(strategy_configs).where(strategy_configs.c.id == config_id))
    row = result.first()
    return dict(row._mapping) if row else None

async def delete_strategy_config(session, config_id):
    """
    Delete a strategy config from the database.
    """
    # First check if config exists
    config = await get_strategy_config_by_id(session, config_id)
    if not config:
        return None
    
    # Delete the config
    await session.execute(
        delete(strategy_configs).where(strategy_configs.c.id == config_id)
    )
    await session.commit()
    return config

async def enable_strategy_config(session, config_id):
    # Get config
    config = await get_strategy_config_by_id(session, config_id)
    if not config:
        return None
    strategy_id = config["strategy_id"]
    symbol = config["symbol"]
    # Disable all others for this (strategy_id, symbol)
    await session.execute(
        update(strategy_configs)
        .where(strategy_configs.c.strategy_id == strategy_id)
        .where(strategy_configs.c.symbol == symbol)
        .values(enabled=False)
    )
    # Enable selected
    await session.execute(
        update(strategy_configs)
        .where(strategy_configs.c.id == config_id)
        .values(enabled=True)
    )
    await session.commit()
    return await get_strategy_config_by_id(session, config_id)

async def disable_strategy_config(session, config_id):
    await session.execute(
        update(strategy_configs)
        .where(strategy_configs.c.id == config_id)
        .values(enabled=False)
    )
    await session.commit()
    return await get_strategy_config_by_id(session, config_id)

# --- Strategy Symbol CRUD ---
async def add_strategy_symbol(session, strategy_id, symbol, config_id, status='active'):
    """
    Add a symbol to a strategy with a specific config.
    """
    now = get_ist_now()
    
    # Check if the strategy-symbol combination already exists
    existing = await session.execute(
        select(strategy_symbols).where(
            and_(
                strategy_symbols.c.strategy_id == strategy_id,
                strategy_symbols.c.symbol == symbol
            )
        )
    )
    existing_row = existing.first()
    
    if existing_row:
        # Update existing record
        await session.execute(
            update(strategy_symbols)
            .where(strategy_symbols.c.id == existing_row.id)
            .values(
                config_id=config_id,
                status=status,
                updated_at=now
            )
        )
        await session.commit()
        
        # Return updated record
        result = await session.execute(
            select(strategy_symbols).where(strategy_symbols.c.id == existing_row.id)
        )
        row = result.first()
        return dict(row._mapping) if row else None
    else:
        # Create new record
        stmt = strategy_symbols.insert().values(
            strategy_id=strategy_id,
            symbol=symbol,
            config_id=config_id,
            status=status,
            created_at=now,
            updated_at=now
        )
        res = await session.execute(stmt)
        await session.commit()
        
        symbol_id = res.inserted_primary_key[0]
        result = await session.execute(
            select(strategy_symbols).where(strategy_symbols.c.id == symbol_id)
        )
        row = result.first()
        return dict(row._mapping) if row else None

async def list_strategy_symbols(session, strategy_id):
    """
    List all symbols for a given strategy.
    """
    result = await session.execute(
        select(strategy_symbols)
        .where(strategy_symbols.c.strategy_id == strategy_id)
        .order_by(strategy_symbols.c.created_at.desc())
    )
    return [dict(row._mapping) for row in result.fetchall()]

async def get_strategy_symbol_by_id(session, symbol_id):
    """
    Get a strategy symbol by its ID.
    """
    result = await session.execute(
        select(strategy_symbols).where(strategy_symbols.c.id == symbol_id)
    )
    row = result.first()
    return dict(row._mapping) if row else None

async def set_strategy_symbol_status(session, symbol_id, status):
    """
    Set the status of a strategy symbol (e.g., 'active', 'inactive', 'paused').
    """
    now = get_ist_now()
    
    await session.execute(
        update(strategy_symbols)
        .where(strategy_symbols.c.id == symbol_id)
        .values(status=status, updated_at=now)
    )
    await session.commit()
    
    return await get_strategy_symbol_by_id(session, symbol_id)

async def delete_strategy_symbol(session, symbol_id):
    """
    Delete a strategy symbol.
    """
    # First check if symbol exists
    symbol = await get_strategy_symbol_by_id(session, symbol_id)
    if not symbol:
        return None
    
    # Delete the symbol
    await session.execute(
        delete(strategy_symbols).where(strategy_symbols.c.id == symbol_id)
    )
    await session.commit()
    return symbol

async def update_strategy_symbol(session, symbol_id, update_data):
    """
    Update a strategy symbol.
    """
    now = get_ist_now()
    update_data['updated_at'] = now
    
    stmt = update(strategy_symbols).where(strategy_symbols.c.id == symbol_id).values(**update_data)
    await session.execute(stmt)
    await session.commit()
    
    return await get_strategy_symbol_by_id(session, symbol_id)

async def get_strategy_symbols_by_config_id(session, config_id):
    """
    Get all symbols using a specific config.
    """
    result = await session.execute(
        select(strategy_symbols)
        .where(strategy_symbols.c.config_id == config_id)
        .order_by(strategy_symbols.c.created_at.desc())
    )
    return [dict(row._mapping) for row in result.fetchall()]

# --- Strategy CRUD ---
async def get_all_strategies(session):
    result = await session.execute(select(strategies))
    return [dict(row._mapping) for row in result.fetchall()]

async def get_strategy_by_id(session, strategy_id):
    result = await session.execute(select(strategies).where(strategies.c.id == strategy_id))
    row = result.first()
    return dict(row._mapping) if row else None

async def update_strategy(session, strategy_id, update_data):
    """
    Update a strategy with new data.
    """
    from algosat.core.time_utils import get_ist_now
    now = get_ist_now()
    update_data['updated_at'] = now
    
    stmt = update(strategies).where(strategies.c.id == strategy_id).values(**update_data)
    await session.execute(stmt)
    await session.commit()
    
    return await get_strategy_by_id(session, strategy_id)

async def enable_strategy(session, strategy_id):
    """
    Enable a strategy by setting enabled=True.
    """
    return await update_strategy(session, strategy_id, {'enabled': True})

async def disable_strategy(session, strategy_id):
    """
    Disable a strategy by setting enabled=False.
    """
    return await update_strategy(session, strategy_id, {'enabled': False})

async def get_strategy_configs_by_strategy_id(session, strategy_id):
    result = await session.execute(
        select(strategy_configs).where(strategy_configs.c.strategy_id == strategy_id).order_by(strategy_configs.c.created_at.desc())
    )
    return [dict(row._mapping) for row in result.fetchall()]

async def get_strategy_configs_paginated(session, strategy_id, page=1, page_size=10):
    """
    Get strategy configs with pagination support.
    """
    offset = (page - 1) * page_size
    
    # Get total count
    count_query = select(func.count(strategy_configs.c.id)).where(strategy_configs.c.strategy_id == strategy_id)
    count_result = await session.execute(count_query)
    total_count = count_result.scalar()
    
    # Get configs with pagination
    configs_query = (
        select(strategy_configs)
        .where(strategy_configs.c.strategy_id == strategy_id)
        .order_by(strategy_configs.c.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    result = await session.execute(configs_query)
    configs = [dict(row._mapping) for row in result.fetchall()]
    
    return {
        'configs': configs,
        'total_count': total_count,
        'page': page,
        'page_size': page_size,
        'total_pages': (total_count + page_size - 1) // page_size
    }

async def get_active_strategy_symbols_with_configs(session):
    """
    Fetch all active symbols for enabled strategies along with their config details.
    Returns symbols with full strategy and config information needed for trading.
    
    Returns:
        List of rows with columns: symbol_id, strategy_id, strategy_key, strategy_name, 
        symbol, config_id, config_name, config_description, exchange, instrument, 
        trade_config, indicators_config, order_type, product_type
    """
    from sqlalchemy import select
    
    stmt = (
        select(
            strategy_symbols.c.id.label('symbol_id'),
            strategies.c.id.label('strategy_id'),
            strategies.c.key.label('strategy_key'),
            strategies.c.name.label('strategy_name'),
            strategies.c.order_type,
            strategies.c.product_type,
            strategy_symbols.c.symbol,
            strategy_symbols.c.status.label('symbol_status'),
            strategy_configs.c.id.label('config_id'),
            strategy_configs.c.name.label('config_name'),
            strategy_configs.c.description.label('config_description'),
            strategy_configs.c.exchange,
            strategy_configs.c.instrument,
            strategy_configs.c.trade.label('trade_config'),
            strategy_configs.c.indicators.label('indicators_config')
        )
        .select_from(
            strategy_symbols
            .join(strategies, strategy_symbols.c.strategy_id == strategies.c.id)
            .join(strategy_configs, strategy_symbols.c.config_id == strategy_configs.c.id)
        )
        .where(strategies.c.enabled == True)
        .where(strategy_symbols.c.status == 'active')
    )
    
    result = await session.execute(stmt)
    return result.fetchall()

async def get_enabled_default_strategy_configs(session):
    """
    DEPRECATED: This function is for the old schema where configs had is_default flag.
    Use get_active_strategy_symbols_with_configs() instead for the new schema.
    
    Fetch all default configs for enabled strategies.
    """
    stmt = (
        select(strategy_configs)
        .join(strategies, strategy_configs.c.strategy_id == strategies.c.id)
        .where(strategies.c.enabled == True)
        .where(strategy_configs.c.is_default == True)
    )
    result = await session.execute(stmt)
    return result.fetchall()


# New: Insert only default strategies (no configs)
async def insert_default_strategies(conn, default_strategy_configs) -> bool:
    """
    Insert default strategies into the DB without configs.
    """
    now = get_ist_now()
    for key, default_cfg in default_strategy_configs.items():
        ins = strategies.insert().values(
            key=key,
            name=default_cfg.get("name", key),
            description=default_cfg.get("description", ""),
            enabled=True,
            created_at=now,
            updated_at=now,
        )
        await conn.execute(ins)
    return True

async def insert_default_strategy_configs(conn, default_strategy_configs) -> bool:
    """
    Insert default strategy_configs for existing strategies.
    Handles missing keys robustly and logs errors for incomplete configs.
    """
    import logging
    now = get_ist_now()
    strategy_key_to_id = {}
    for key in default_strategy_configs:
        result = await conn.execute(
            select(strategies.c.id).where(strategies.c.key == key)
        )
        strategy_id = result.scalar_one_or_none()
        if strategy_id:
            strategy_key_to_id[key] = strategy_id

    for key, default_cfg in default_strategy_configs.items():
        strategy_id = strategy_key_to_id.get(key)
        if not strategy_id:
            continue
        # Provide defaults for missing fields
        symbol = default_cfg.get("symbol", "")
        exchange = default_cfg.get("exchange", "")
        instrument = default_cfg.get("instrument")
        trade = default_cfg.get("trade", {})
        indicators = default_cfg.get("indicators", {})
        is_default = default_cfg.get("is_default", True)
        enabled = default_cfg.get("enabled", True)
        if not symbol or not exchange:
            logging.warning(f"Skipping config for strategy '{key}' due to missing symbol or exchange.")
            continue
        ins_cfg = strategy_configs.insert().values(
            strategy_id=strategy_id,
            symbol=symbol,
            exchange=exchange,
            instrument=instrument,
            trade=trade,
            indicators=indicators,
            is_default=is_default,
            enabled=enabled,
            created_at=now,
            updated_at=now,
        )
        await conn.execute(ins_cfg)
    return True

async def has_any_strategies(conn) -> bool:
    """
    Return True if the strategies table has any rows, else False.
    """
    result = await conn.execute(select(strategies))
    return result.first() is not None

async def has_any_strategy_configs() -> bool:
    """
    Return True if the strategy_configs table has any rows, else False.
    """
    from algosat.core.dbschema import strategy_configs
    from algosat.core.db import engine
    async with engine.begin() as conn:
        result = await conn.execute(select(strategy_configs))
        return result.first() is not None


async def seed_default_strategies_and_configs() -> bool:
    """
    Seed default strategies and/or configs if tables are empty.
    Also resets the sequence for strategies and strategy_configs tables if seeding is performed.
    """
    seeded = False
    async with engine.begin() as conn:
        has_strats = await has_any_strategies(conn)
        has_cfgs = await has_any_strategy_configs()

        # If no strategies, insert them and reset sequence
        if not has_strats:
            await insert_default_strategies(conn, DEFAULT_STRATEGY_CONFIGS)
            await reset_table_sequence(conn, 'strategies', 'strategies_id_seq')
            seeded = True

        # If no configs, insert only configs (requires strategies to exist) and reset sequence
        if not has_cfgs:
            await insert_default_strategy_configs(conn, DEFAULT_STRATEGY_CONFIGS)
            await reset_table_sequence(conn, 'strategy_configs', 'strategy_configs_id_seq')
            seeded = True

    return seeded

async def reset_table_sequence(conn, table_name: str, sequence_name: str, restart_with: int = 1):
    """
    Reset the sequence for a table's autoincrementing primary key (PostgreSQL).
    """
    await conn.execute(text(f"ALTER SEQUENCE {sequence_name} RESTART WITH {restart_with};"))


# Example usage in your seeding/init logic (call after dropping and recreating tables):
# await reset_table_sequence(conn, 'strategies', 'strategies_id_seq')
# await reset_table_sequence(conn, 'strategy_configs', 'strategy_configs_id_seq')

from sqlalchemy import select
from algosat.core.dbschema import broker_credentials

async def get_trade_enabled_brokers(async_session=None):
    """
    Return a list of broker names where trade_execution_enabled is True.
    """
    from algosat.core.db import AsyncSessionLocal
    session = async_session or AsyncSessionLocal()
    async with session as sess:
        result = await sess.execute(
            select(broker_credentials.c.broker_name)
            .where(broker_credentials.c.trade_execution_enabled == True)
            .where(broker_credentials.c.is_enabled == True)
        )
        return [row[0] for row in result.fetchall()]

async def insert_order(session, order_data):
    """
    Insert a new order into the orders table.
    Args:
        session: SQLAlchemy async session
        order_data: dict with order fields
    Returns:
        The inserted order row as a dict, or None if failed.
    """
    from algosat.core.dbschema import orders
    stmt = orders.insert().values(**order_data)
    res = await session.execute(stmt)
    await session.commit()
    order_id = res.inserted_primary_key[0] if res.inserted_primary_key else None
    if order_id:
        result = await session.execute(select(orders).where(orders.c.id == order_id))
        row = result.first()
        return dict(row._mapping) if row else None
    return None

# --- Order CRUD Operations ---

async def get_all_orders(session: AsyncSession):
    """
    Retrieve all orders (no broker join).
    """
    stmt = (
        select(
            orders.c.id,
            orders.c.strategy_symbol_id,
            orders.c.strike_symbol,
            orders.c.pnl,
            orders.c.candle_range,
            orders.c.entry_price,
            orders.c.stop_loss,
            orders.c.target_price,
            orders.c.signal_time,
            orders.c.entry_time,
            orders.c.exit_time,
            orders.c.exit_price,
            orders.c.status,
            orders.c.reason,
            orders.c.atr,
            orders.c.supertrend_signal,
            orders.c.lot_qty,
            orders.c.side,
            orders.c.qty,
            orders.c.created_at,
            orders.c.updated_at
        )
        .order_by(orders.c.signal_time.desc().nullslast(), orders.c.id.desc())
    )
    result = await session.execute(stmt)
    rows = result.fetchall()
    print(f"DEBUG DB: get_all_orders fetched {len(rows)} rows")
    if rows:
        print(f"DEBUG DB: first row raw: {rows[0]}")
    converted = [dict(row._mapping) for row in rows]
    print(f"DEBUG DB: converted to {len(converted)} dicts")
    if converted:
        print(f"DEBUG DB: first dict: {converted[0]}")
    return converted

async def get_order_by_id(session: AsyncSession, order_id: int):
    """
    Retrieve a specific order by its ID (logical order only, no broker join).
    """
    from algosat.core.dbschema import orders
    stmt = select(orders).where(orders.c.id == order_id)
    result = await session.execute(stmt)
    row = result.first()
    return dict(row._mapping) if row else None

async def get_orders_by_broker(session: AsyncSession, broker_name: str):
    """
    Retrieve orders filtered by broker_name.
    Joins orders with broker_credentials.
    """
    stmt = (
        select(
            orders.c.id,
            orders.c.symbol,
            orders.c.status,
            orders.c.side,
            broker_credentials.c.broker_name,
            orders.c.entry_price,
            orders.c.lot_qty,
            orders.c.signal_time,
            orders.c.entry_time,
        )
        .select_from(orders.join(broker_credentials, orders.c.broker_id == broker_credentials.c.id))
        .where(broker_credentials.c.broker_name == broker_name)
        .order_by(orders.c.signal_time.desc().nullslast(), orders.c.id.desc())
    )
    result = await session.execute(stmt)
    return [dict(row._mapping) for row in result.fetchall()]

async def get_orders_by_broker_and_strategy(session: AsyncSession, broker_name: str, strategy_config_id: int):
    """
    Retrieve orders filtered by both broker_name and strategy_config_id.
    Joins orders with broker_credentials.
    """
    stmt = (
        select(
            orders.c.id,
            orders.c.symbol,
            orders.c.status,
            orders.c.side,
            broker_credentials.c.broker_name,
            orders.c.entry_price,
            orders.c.lot_qty,
            orders.c.signal_time,
            orders.c.entry_time,
        )
        .select_from(orders.join(broker_credentials, orders.c.broker_id == broker_credentials.c.id))
        .where(broker_credentials.c.broker_name == broker_name)
        .where(orders.c.strategy_config_id == strategy_config_id)
        .order_by(orders.c.signal_time.desc().nullslast(), orders.c.id.desc())
    )
    result = await session.execute(stmt)
    return [dict(row._mapping) for row in result.fetchall()]

async def get_orders_by_symbol(session: AsyncSession, symbol: str):
    """
    Retrieve orders filtered by symbol.
    """
    stmt = (
        select(
            orders.c.id,
            orders.c.strategy_symbol_id,
            orders.c.strike_symbol,
            orders.c.pnl,
            orders.c.candle_range,
            orders.c.entry_price,
            orders.c.stop_loss,
            orders.c.target_price,
            orders.c.signal_time,
            orders.c.entry_time,
            orders.c.exit_time,
            orders.c.exit_price,
            orders.c.status,
            orders.c.reason,
            orders.c.atr,
            orders.c.supertrend_signal,
            orders.c.lot_qty,
            orders.c.side,
            orders.c.qty,
            orders.c.created_at,
            orders.c.updated_at
        )
        .where(orders.c.strike_symbol.ilike(f'%{symbol}%'))
        .order_by(orders.c.signal_time.desc().nullslast(), orders.c.id.desc())
    )
    result = await session.execute(stmt)
    return [dict(row._mapping) for row in result.fetchall()]

async def get_user_by_username(session: AsyncSession, username: str):
    from algosat.core.dbschema import users
    stmt = select(users).where(users.c.username == username)
    result = await session.execute(stmt)
    row = result.first()
    return dict(row._mapping) if row else None

async def get_user_by_email(session: AsyncSession, email: str):
    from algosat.core.dbschema import users
    stmt = select(users).where(users.c.email == email)
    result = await session.execute(stmt)
    row = result.first()
    return dict(row._mapping) if row else None

async def create_user(session: AsyncSession, username: str, email: str, hashed_password: str, full_name: str = None, role: str = "user"):
    from algosat.core.dbschema import users
    new_user = {
        "username": username,
        "email": email,
        "hashed_password": hashed_password,
        "full_name": full_name,
        "role": role,
        "is_active": True,
    }
    stmt = users.insert().values(**new_user)
    await session.execute(stmt)
    await session.commit()
    # Fetch the user just created
    result = await session.execute(select(users).where(users.c.username == username))
    row = result.first()
    return dict(row._mapping) if row else None

from sqlalchemy import select
from algosat.core.dbschema import orders

async def get_open_orders_for_symbol(session, symbol: str):
    """Return all open orders for a given symbol (status = 'OPEN' or equivalent)."""
    stmt = select(orders).where(
        orders.c.symbol == symbol,
        orders.c.status.in_(["OPEN", "PARTIALLY_FILLED"])  # Add other statuses as needed
    )
    result = await session.execute(stmt)
    return [dict(row._mapping) for row in result.fetchall()]

async def get_open_orders_for_symbol_and_tradeday(session, symbol: str, trade_day, strategy_config_id: int = None):
    """Return all open orders for a given symbol, strategy, and trade day (status = 'OPEN' or equivalent)."""
    from datetime import datetime
    from sqlalchemy import and_
    from algosat.core.time_utils import to_ist
    # Convert trade_day to IST date if not already
    ist_day = to_ist(datetime.combine(trade_day, datetime.min.time())).date()
    start_dt = to_ist(datetime.combine(ist_day, datetime.min.time()))
    end_dt = to_ist(datetime.combine(ist_day, datetime.max.time()))
    filters = [
        orders.c.symbol == symbol,
        orders.c.status.in_(["AWAITING_ENTRY", "OPEN", "PARTIALLY_FILLED"]),
        orders.c.signal_time >= start_dt,
        orders.c.signal_time <= end_dt
    ]
    if strategy_config_id is not None:
        filters.append(orders.c.strategy_config_id == strategy_config_id)
    stmt = select(orders).where(and_(*filters))
    result = await session.execute(stmt)
    return [dict(row._mapping) for row in result.fetchall()]

async def get_open_orders_for_strategy_symbol_and_tradeday(session, strategy_config_id: int, symbol: str, trade_day):
    """Return all open orders for a given strategy config, symbol, and trade day."""
    return await get_open_orders_for_symbol_and_tradeday(session, symbol, trade_day, strategy_config_id)

async def get_open_orders_for_strategy_and_tradeday(session, strategy_id: int, trade_day):
    """
    Return all open orders for a given strategy on a specific trade day.
    Joins orders -> strategy_symbols -> strategies to find orders by strategy_id.
    """
    from sqlalchemy import join, func, or_
    
    # Convert trade_day to date for comparison
    if hasattr(trade_day, 'date'):
        trade_date = trade_day.date()
    else:
        trade_date = trade_day
    
    # Define what we consider "open" statuses - include more statuses
    open_statuses = ['AWAITING_ENTRY', 'OPEN', 'PARTIALLY_FILLED', 'PENDING', 'TRIGGER_PENDING']
    
    # Join orders with strategy_symbols to get strategy_id relationship
    join_stmt = join(
        orders, 
        strategy_symbols, 
        orders.c.strategy_symbol_id == strategy_symbols.c.id
    )
    
    stmt = (
        select(orders)
        .select_from(join_stmt)
        .where(
            and_(
                strategy_symbols.c.strategy_id == strategy_id,
                orders.c.status.in_(open_statuses),
                or_(
                    func.date(orders.c.signal_time) == trade_date,
                    func.date(orders.c.entry_time) == trade_date,
                    # If both are null, check created_at
                    and_(
                        orders.c.signal_time.is_(None),
                        orders.c.entry_time.is_(None),
                        func.date(orders.c.created_at) == trade_date
                    )
                )
            )
        )
        .order_by(orders.c.signal_time.desc())
    )
    
    result = await session.execute(stmt)
    return [dict(row._mapping) for row in result.fetchall()]

# --- Data Provider Broker ---
async def get_data_enabled_broker(session):
    """
    Return the broker row where is_data_provider=True and is_enabled=True.
    """
    result = await session.execute(
        select(broker_credentials).where(
            broker_credentials.c.is_data_provider == True,
            broker_credentials.c.is_enabled == True
        )
    )
    row = result.first()
    return dict(row._mapping) if row else None

async def get_broker_executions_by_order_id(session, order_id: int):
    """
    Return all broker_executions rows for a given logical order_id, including broker_id for downstream use.
    """
    from algosat.core.dbschema import broker_executions
    stmt = select(broker_executions).where(broker_executions.c.parent_order_id == order_id)
    result = await session.execute(stmt)
    return [dict(row._mapping) for row in result.fetchall()]

async def get_granular_executions_by_order_id(session, order_id: int, side: str = None):
    """
    Return granular execution records for a given logical order_id.
    
    Args:
        session: Database session
        order_id: Parent order ID from orders table
        side: Optional filter by 'ENTRY' or 'EXIT'
        
    Returns:
        List of execution records with actual traded prices and quantities
    """
    from algosat.core.dbschema import broker_executions
    from sqlalchemy import and_
    
    conditions = [broker_executions.c.parent_order_id == order_id]
    if side:
        conditions.append(broker_executions.c.side == side)
    
    stmt = select(broker_executions).where(and_(*conditions)).order_by(
        broker_executions.c.execution_time,
        broker_executions.c.sequence_number
    )
    result = await session.execute(stmt)
    return [dict(row._mapping) for row in result.fetchall()]

async def get_executions_summary_by_order_id(session, order_id: int):
    """
    Get execution summary for an order with VWAP calculations.
    
    Returns:
        {
            'entry_executions': [...],
            'exit_executions': [...],
            'entry_vwap': float,
            'exit_vwap': float,
            'entry_qty': int,
            'exit_qty': int,
            'realized_pnl': float,
            'unrealized_pnl': float
        }
    """
    entry_executions = await get_granular_executions_by_order_id(session, order_id, 'ENTRY')
    exit_executions = await get_granular_executions_by_order_id(session, order_id, 'EXIT')
    
    # Calculate entry VWAP
    entry_total_value = sum(float(ex['execution_price']) * int(ex['executed_quantity']) for ex in entry_executions)
    entry_qty = sum(int(ex['executed_quantity']) for ex in entry_executions)
    entry_vwap = entry_total_value / entry_qty if entry_qty > 0 else 0.0
    
    # Calculate exit VWAP
    exit_total_value = sum(float(ex['execution_price']) * int(ex['executed_quantity']) for ex in exit_executions)
    exit_qty = sum(int(ex['executed_quantity']) for ex in exit_executions)
    exit_vwap = exit_total_value / exit_qty if exit_qty > 0 else 0.0
    
    # Calculate P&L
    realized_pnl = 0.0
    unrealized_pnl = 0.0
    
    if entry_vwap > 0 and exit_vwap > 0:
        # Realized P&L based on closed quantity
        closed_qty = min(entry_qty, exit_qty)
        # Note: This assumes BUY side - in production, should read actual side from orders table
        realized_pnl = (exit_vwap - entry_vwap) * closed_qty
    
    # Unrealized P&L would need current market price (to be implemented later)
    remaining_qty = entry_qty - exit_qty
    if remaining_qty > 0:
        # unrealized_pnl = (current_market_price - entry_vwap) * remaining_qty
        pass
    
    return {
        'entry_executions': entry_executions,
        'exit_executions': exit_executions,
        'entry_vwap': entry_vwap,
        'exit_vwap': exit_vwap,
        'entry_qty': entry_qty,
        'exit_qty': exit_qty,
        'realized_pnl': realized_pnl,
        'unrealized_pnl': unrealized_pnl
    }

# --- Trade Statistics and P&L Functions ---

async def get_strategy_symbol_trade_stats(session: AsyncSession, strategy_symbol_id: int):
    """
    Get trade statistics for a specific strategy symbol.
    Returns live trades (open orders) and total trades (completed orders) with P&L.
    """
    from algosat.core.dbschema import orders
    
    # Get live (open) orders
    live_stmt = select(orders).where(
        and_(
            orders.c.strategy_symbol_id == strategy_symbol_id,
            orders.c.status.in_(['open', 'pending', 'active', 'partial'])  # Open order statuses
        )
    )
    live_result = await session.execute(live_stmt)
    live_orders = live_result.fetchall()
    
    # Get completed orders for total stats
    completed_stmt = select(orders).where(
        and_(
            orders.c.strategy_symbol_id == strategy_symbol_id,
            orders.c.status.in_(['completed', 'filled', 'closed'])  # Completed order statuses
        )
    )
    completed_result = await session.execute(completed_stmt)
    completed_orders = completed_result.fetchall()
    
    # Calculate live P&L (unrealized) - enhanced with granular executions
    live_pnl = 0.0
    for order in live_orders:
        order_dict = dict(order._mapping)
        order_id = order_dict.get('id')
        
        # Try to get granular P&L first, fallback to legacy calculation
        try:
            summary = await get_executions_summary_by_order_id(session, order_id)
            live_pnl += summary.get('unrealized_pnl', 0.0)
        except:
            # Fallback to legacy calculation
            entry_price = order_dict.get('entry_price')
            qty = order_dict.get('qty', 0)
            # Live P&L calculation would need current market price - for now set to 0
            # This can be enhanced later with real-time price data
    
    # Calculate total P&L (realized) - enhanced with granular executions
    total_pnl = 0.0
    for order in completed_orders:
        order_dict = dict(order._mapping)
        order_id = order_dict.get('id')
        
        # Try to get granular P&L first, fallback to legacy calculation
        try:
            summary = await get_executions_summary_by_order_id(session, order_id)
            total_pnl += summary.get('realized_pnl', 0.0)
        except:
            # Fallback to legacy calculation
            entry_price = order_dict.get('entry_price')
            exit_price = order_dict.get('exit_price')
            qty = order_dict.get('qty', 0)
            side = order_dict.get('side', 'BUY')
            
            if entry_price and exit_price and qty:
                if side.upper() == 'BUY':
                    pnl = (exit_price - entry_price) * qty
                else:  # SELL
                    pnl = (entry_price - exit_price) * qty
                total_pnl += pnl
    
    return {
        'live_trade_count': len(live_orders),
        'live_pnl': live_pnl,
        'total_trade_count': len(completed_orders),
        'total_pnl': total_pnl,
        'all_trade_count': len(live_orders) + len(completed_orders)
    }

async def get_strategy_trade_stats(session: AsyncSession, strategy_id: int):
    """
    Get aggregated trade statistics for all symbols in a strategy.
    """
    from algosat.core.dbschema import orders
    
    # Join orders with strategy_symbols to get strategy-level data
    stmt = select(
        orders.c.id,
        orders.c.strategy_symbol_id,
        orders.c.entry_price,
        orders.c.exit_price,
        orders.c.qty,
        orders.c.side,
        orders.c.status,
        strategy_symbols.c.symbol,
        strategy_symbols.c.config_id
    ).select_from(
        orders.join(strategy_symbols, orders.c.strategy_symbol_id == strategy_symbols.c.id)
    ).where(
        and_(
            strategy_symbols.c.strategy_id == strategy_id,
            orders.c.status.in_(['completed', 'filled', 'closed'])
        )
    )
    
    result = await session.execute(stmt)
    orders_data = result.fetchall()
    
    # Aggregate by symbol
    symbol_stats = {}
    total_pnl = 0.0
    total_trades = 0
    
    for order in orders_data:
        order_dict = dict(order._mapping)
        symbol_id = order_dict['strategy_symbol_id']
        symbol_name = order_dict['symbol']
        config_id = order_dict['config_id']
        
        if symbol_id not in symbol_stats:
            symbol_stats[symbol_id] = {
                'symbol': symbol_name,
                'config_id': config_id,
                'trade_count': 0,
                'pnl': 0.0
            }
        
        # Calculate P&L for this order
        entry_price = order_dict.get('entry_price')
        exit_price = order_dict.get('exit_price')
        qty = order_dict.get('qty', 0)
        side = order_dict.get('side', 'BUY')
        
        if entry_price and exit_price and qty:
            if side.upper() == 'BUY':
                pnl = (exit_price - entry_price) * qty
            else:  # SELL
                pnl = (entry_price - exit_price) * qty
            
            symbol_stats[symbol_id]['pnl'] += pnl
            total_pnl += pnl
        
        symbol_stats[symbol_id]['trade_count'] += 1
        total_trades += 1
    
    return {
        'total_trades': total_trades,
        'total_pnl': total_pnl,
        'symbol_stats': symbol_stats
    }

async def get_trades_for_symbol(session: AsyncSession, strategy_symbol_id: int, limit: int = 100):
    """
    Get detailed trade history for a specific strategy symbol.
    """
    from algosat.core.dbschema import orders
    
    stmt = select(orders).where(
        orders.c.strategy_symbol_id == strategy_symbol_id
    ).order_by(
        orders.c.created_at.desc()
    ).limit(limit)
    
    result = await session.execute(stmt)
    return [dict(row._mapping) for row in result.fetchall()]

async def insert_broker_balance_summary(session, broker_id: int, summary: dict):
    """
    Insert a new broker balance summary record.
    """
    stmt = broker_balance_summaries.insert().values(
        broker_id=broker_id,
        summary=summary,
        fetched_at=datetime.utcnow()
    )
    await session.execute(stmt)
    await session.commit()

async def upsert_broker_balance_summary(session, broker_id: int, summary: dict):
    """
    Upsert broker balance summary for today (overwrite if exists for today).
    """
    # Get today's date at midnight UTC
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    stmt = select(broker_balance_summaries).where(
        and_ (broker_balance_summaries.c.broker_id == broker_id, broker_balance_summaries.c.date == today)
    )
    result = await session.execute(stmt)
    row = result.first()
    if row:
        # Update existing
        await session.execute(
            broker_balance_summaries.update()
            .where(broker_balance_summaries.c.id == row._mapping['id'])
            .values(summary=summary, fetched_at=datetime.now(timezone.utc))
        )
    else:
        # Insert new
        await session.execute(
            broker_balance_summaries.insert().values(
                broker_id=broker_id,
                summary=summary,
                date=today,
                fetched_at=datetime.now(timezone.utc)
            )
        )
    await session.commit()

async def get_latest_broker_balance_summary(session, broker_id: int):
    """
    Get today's broker balance summary for a broker.
    """
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    stmt = (
        select(broker_balance_summaries)
        .where(and_(broker_balance_summaries.c.broker_id == broker_id, broker_balance_summaries.c.date == today))
        .order_by(broker_balance_summaries.c.fetched_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    row = result.first()
    return dict(row._mapping) if row else None

async def get_latest_balance_summaries_for_all_brokers(session):
    """
    Get today's balance summary for each broker (by broker_id).
    """
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    stmt = select(broker_balance_summaries).where(broker_balance_summaries.c.date == today)
    result = await session.execute(stmt)
    return [dict(row._mapping) for row in result.fetchall()]

async def get_orders_summary_by_symbol(session: AsyncSession, symbol: str):
    """
    Get aggregated P&L and trade statistics for a specific symbol.
    Returns total P&L, trade count, and other statistics from orders.
    """
    from sqlalchemy import func
    
    stmt = (
        select(
            func.count(orders.c.id).label('total_trades'),
            func.sum(orders.c.pnl).label('total_pnl'),
            func.sum(case((orders.c.status == 'OPEN', orders.c.pnl), else_=0)).label('live_pnl'),
            func.count(case((orders.c.status == 'OPEN', orders.c.id))).label('open_trades'),
            func.count(case((orders.c.status == 'CLOSED', orders.c.id))).label('closed_trades'),
            func.count(case((and_(orders.c.status == 'CLOSED', orders.c.pnl > 0), orders.c.id))).label('winning_trades')
        )
        .where(orders.c.strike_symbol.ilike(f'%{symbol}%'))
    )
    result = await session.execute(stmt)
    row = result.first()
    
    if row:
        return {
            'symbol': symbol,
            'total_trades': row.total_trades or 0,
            'total_pnl': float(row.total_pnl) if row.total_pnl else 0.0,
            'live_pnl': float(row.live_pnl) if row.live_pnl else 0.0,
            'open_trades': row.open_trades or 0,
            'closed_trades': row.closed_trades or 0,
            'winning_trades': row.winning_trades or 0
        }
    else:
        return {
            'symbol': symbol,
            'total_trades': 0,
            'total_pnl': 0.0,
            'live_pnl': 0.0,
            'open_trades': 0,
            'closed_trades': 0,
            'winning_trades': 0
        }
async def get_orders_by_strategy_symbol_id(session: AsyncSession, strategy_symbol_id: int):
    """
    Retrieve all orders for a specific strategy_symbol_id.
    Uses the same logic as get_all_orders but filters by strategy_symbol_id.
    """
    stmt = (
        select(
            orders.c.id,
            orders.c.strategy_symbol_id,
            orders.c.strike_symbol,
            orders.c.pnl,
            orders.c.candle_range,
            orders.c.entry_price,
            orders.c.stop_loss,
            orders.c.target_price,
            orders.c.signal_time,
            orders.c.entry_time,
            orders.c.exit_time,
            orders.c.exit_price,
            orders.c.status,
            orders.c.reason,
            orders.c.atr,
            orders.c.supertrend_signal,
            orders.c.lot_qty,
            orders.c.side,
            orders.c.qty,
            orders.c.created_at,
            orders.c.updated_at
        )
        .where(orders.c.strategy_symbol_id == strategy_symbol_id)
        .order_by(orders.c.signal_time.desc().nullslast(), orders.c.id.desc())
    )
    result = await session.execute(stmt)
    rows = result.fetchall()
    print(f"DEBUG DB: get_orders_by_strategy_symbol_id({strategy_symbol_id}) fetched {len(rows)} rows")
    if rows:
        print(f"DEBUG DB: first row raw: {rows[0]}")
    converted = [dict(row._mapping) for row in rows]
    print(f"DEBUG DB: converted to {len(converted)} dicts")
    if converted:
        print(f"DEBUG DB: first dict: {converted[0]}")
    return converted

async def get_strategy_symbol_by_name(session: AsyncSession, symbol_name: str):
    """
    Get strategy_symbol record by symbol name.
    """
    stmt = (
        select(
            strategy_symbols.c.id,
            strategy_symbols.c.symbol,
            strategy_symbols.c.strategy_id,
            strategy_symbols.c.config_id
        )
        .where(strategy_symbols.c.symbol == symbol_name)
    )
    result = await session.execute(stmt)
    row = result.first()
    
    if row:
        return dict(row._mapping)
    else:
        return None

