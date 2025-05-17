# algosat/core/db.py

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import inspect, Table, MetaData, update, select, delete  # Modified import

from config import settings
from core.dbschema import metadata
from core.dbschema import broker_credentials, strategy_configs, strategies  # Importing the new tables

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


