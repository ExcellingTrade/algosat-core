# All DB access functions have been moved to db.py. Keep only non-DB order logic here.

from sqlalchemy import select
from algosat.core.dbschema import orders
from core.time_utils import get_ist_datetime

async def get_open_orders_for_symbol(session, symbol: str):
    """Return all open orders for a given symbol (status = 'OPEN' or equivalent)."""
    stmt = select(orders).where(
        orders.c.symbol == symbol,
        orders.c.status.in_(["OPEN", "PARTIALLY_FILLED"])  # Add other statuses as needed
    )
    result = await session.execute(stmt)
    return [dict(row._mapping) for row in result.fetchall()]

async def get_open_orders_for_symbol_and_tradeday(session, symbol: str, trade_day):
    """Return all open orders for a given symbol and trade day (status = 'OPEN' or equivalent)."""
    # trade_day should be a date object
    from datetime import datetime, timedelta
    start_dt = datetime.combine(trade_day, datetime.min.time())
    end_dt = datetime.combine(trade_day, datetime.max.time())
    stmt = select(orders).where(
        orders.c.symbol == symbol,
        orders.c.status.in_(["OPEN", "PARTIALLY_FILLED"]),
        orders.c.entry_time >= start_dt,
        orders.c.entry_time <= end_dt
    )
    result = await session.execute(stmt)
    return [dict(row._mapping) for row in result.fetchall()]
