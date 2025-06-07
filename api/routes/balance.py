from fastapi import APIRouter, Depends
from typing import List
from algosat.core.db import get_all_brokers, get_latest_balance_summaries_for_all_brokers
from algosat.api.dependencies import get_db
from algosat.api.auth_dependencies import get_current_user
from algosat.common.logger import get_logger

logger = get_logger("api.balance_summary")

router = APIRouter(dependencies=[Depends(get_current_user)])

@router.get("/balance_summary", response_model=List[dict])
async def get_balance_summary_api(db=Depends(get_db)):
    """
    Get today's latest balance summary for all brokers.
    Returns: [{broker_id, broker_name, summary, fetched_at}]
    """
    logger.info("HIT: /balance_summary API endpoint")
    brokers = await get_all_brokers(db)
    logger.info(f"Fetched {len(brokers)} brokers for balance summary: {[b['broker_name'] for b in brokers]}")
    summaries = await get_latest_balance_summaries_for_all_brokers(db)
    logger.info(f"Fetched {len(summaries)} balance summaries from DB")
    broker_id_to_name = {int(b["id"]): b["broker_name"] for b in brokers}
    result = []
    for s in summaries:
        broker_id = int(s["broker_id"])
        broker_name = broker_id_to_name.get(broker_id, "unknown")
        logger.info(f"Summary for broker_id={broker_id}: broker_name={broker_name}, summary={s['summary']}")
        result.append({
            "broker_id": broker_id,
            "broker_name": broker_name,
            "summary": s["summary"],
            "fetched_at": s["fetched_at"]
        })
    logger.info(f"Returning {len(result)} broker balance summaries from API")
    return result
