from fastapi import Depends
from core.db import AsyncSessionLocal

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
