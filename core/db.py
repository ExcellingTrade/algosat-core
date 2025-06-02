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
from sqlalchemy import inspect, Table, MetaData, update, select, delete, func, text # Modified import

import os
from datetime import datetime  # moved to top
from algosat.common.default_strategy_configs import DEFAULT_STRATEGY_CONFIGS
from algosat.core.time_utils import get_ist_now

from algosat.core.dbschema import metadata, orders, broker_credentials, strategies, strategy_configs, users # Added users

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

# --- Strategy CRUD ---
async def get_all_strategies(session):
    result = await session.execute(select(strategies))
    return [dict(row._mapping) for row in result.fetchall()]

async def get_strategy_by_id(session, strategy_id):
    result = await session.execute(select(strategies).where(strategies.c.id == strategy_id))
    row = result.first()
    return dict(row._mapping) if row else None

async def get_strategy_configs_by_strategy_id(session, strategy_id):
    result = await session.execute(select(strategy_configs).where(strategy_configs.c.strategy_id == strategy_id))
    return [dict(row._mapping) for row in result.fetchall()]

async def get_enabled_default_strategy_configs(session):
    """
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

async def get_strategy_name_by_id(session, strategy_id):
    """
    Fetch the strategy name for a given strategy_id.
    """
    stmt = select(strategies.c.name).where(strategies.c.id == strategy_id)
    result = await session.execute(stmt)
    row = result.first()
    return row[0] if row else None


# New: Insert only default strategies (no configs)
async def insert_default_strategies(conn, default_strategy_configs) -> bool:
    """
    Insert default strategies into the DB without configs.
    """
    now = get_ist_now()
    for key, default_cfg in default_strategy_configs.items():
        ins = strategies.insert().values(
            key=key,
            name=key,
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
        select(orders)
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
    stmt = select(broker_executions).where(broker_executions.c.order_id == order_id)
    result = await session.execute(stmt)
    return [dict(row._mapping) for row in result.fetchall()]

async def get_all_open_orders(session):
    """
    Return all orders that are not in a final state (FILLED, CANCELLED, REJECTED, COMPLETE).
    """
    from algosat.core.dbschema import orders
    from algosat.core.order_request import OrderStatus
    final_statuses = [
        OrderStatus.FILLED,
        OrderStatus.CANCELLED,
        OrderStatus.REJECTED,
        OrderStatus.COMPLETE
    ]
    stmt = select(orders).where(~orders.c.status.in_([s.value for s in final_statuses]))
    result = await session.execute(stmt)
    return [dict(row._mapping) for row in result.fetchall()]
