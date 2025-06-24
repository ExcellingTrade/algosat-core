from sqlalchemy import select
from algosat.core.dbschema import strategy_symbols

async def get_strategy_symbol_id(session, strategy_id, symbol, config_id):
    """
    Return the id from strategy_symbols for the given (strategy_id, symbol, config_id).
    """
    stmt = select(strategy_symbols.c.id).where(
        strategy_symbols.c.strategy_id == strategy_id,
        strategy_symbols.c.symbol == symbol,
        strategy_symbols.c.config_id == config_id
    )
    result = await session.execute(stmt)
    row = result.first()
    return row[0] if row else None
