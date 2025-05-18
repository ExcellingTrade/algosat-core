# algosat/core/db.py

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import inspect, Table, MetaData, update, select, delete  # Modified import

from config import settings
from core.dbschema import metadata
from core.dbschema import broker_credentials, strategy_configs, strategies  # Importing the new tables
from datetime import datetime  # moved to top
from common.default_strategy_configs import DEFAULT_STRATEGY_CONFIGS
from core.time_utils import get_ist_now

# 1) Create the Async Engine
engine = create_async_engine(
    str(settings.database_url),  
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

async def get_session() -> AsyncSession:
    """
    Async generator that yields a DB session, then closes it.
    Use this as a FastAPI dependency or call directly in core code.
    """
    async with AsyncSessionLocal() as session:
        yield session

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
    from core.dbschema import strategy_configs
    from core.db import engine
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
    await conn.execute(f"ALTER SEQUENCE {sequence_name} RESTART WITH {restart_with};")


# Example usage in your seeding/init logic (call after dropping and recreating tables):
# await reset_table_sequence(conn, 'strategies', 'strategies_id_seq')
# await reset_table_sequence(conn, 'strategy_configs', 'strategy_configs_id_seq')
