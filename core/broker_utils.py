from algosat.core.db import AsyncSessionLocal, update_broker
from algosat.core.time_utils import get_ist_now

async def update_broker_status(broker_name, status, notes="", last_check=None):
    """Helper to update broker status in DB."""
    now_ist = last_check or get_ist_now()
    async with AsyncSessionLocal() as session:
        await update_broker(session, broker_name, {
            "status": status,
            "last_check": now_ist,
            "updated_at": now_ist,
            "notes": notes
        })
