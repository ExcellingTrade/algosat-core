"""
Dashboard API routes for main dashboard statistics.
"""

from datetime import datetime, timedelta
from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func, and_, cast, Float
from algosat.api.dependencies import get_db
from algosat.api.auth_dependencies import get_current_user
from algosat.core.dbschema import broker_balance_summaries, broker_credentials, orders
from algosat.core.time_utils import get_ist_datetime
from algosat.common.logger import get_logger

logger = get_logger("dashboard_api")
router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("/summary")
async def get_dashboard_summary(session=Depends(get_db)) -> Dict[str, Any]:
    """
    Get dashboard summary statistics including:
    - Total balance across all brokers (today)
    - Balance change from yesterday
    - Active strategies count
    - Today's P&L (placeholder for now)
    """
    try:
        # Get current date in IST
        today = get_ist_datetime().date()
        yesterday = today - timedelta(days=1)
        
        # Get today's total balance across all brokers
        today_balance_query = select(
            func.sum(
                cast(broker_balance_summaries.c.summary.op('->>')('total_balance'), Float)
            ).label('total_balance')
        ).where(
            func.date(broker_balance_summaries.c.date) == today
        )
        
        today_result = await session.execute(today_balance_query)
        today_row = today_result.first()
        today_total_balance = float(today_row.total_balance) if today_row.total_balance else 0.0
        
        # Get yesterday's total balance for comparison
        yesterday_balance_query = select(
            func.sum(
                cast(broker_balance_summaries.c.summary.op('->>')('total_balance'), Float)
            ).label('total_balance')
        ).where(
            func.date(broker_balance_summaries.c.date) == yesterday
        )
        
        yesterday_result = await session.execute(yesterday_balance_query)
        yesterday_row = yesterday_result.first()
        yesterday_total_balance = float(yesterday_row.total_balance) if yesterday_row.total_balance else 0.0
        
        # Calculate balance change
        balance_change = today_total_balance - yesterday_total_balance
        balance_change_percentage = 0.0
        if yesterday_total_balance > 0:
            balance_change_percentage = (balance_change / yesterday_total_balance) * 100
        
        # Get active strategies count (from strategies table where enabled=true)
        from algosat.core.dbschema import strategies
        active_strategies_query = select(
            func.count(strategies.c.id).label('count')
        ).where(
            strategies.c.enabled == True
        )
        
        strategies_result = await session.execute(active_strategies_query)
        strategies_row = strategies_result.first()
        active_strategies_count = int(strategies_row.count) if strategies_row.count else 0
        
        # Get open positions count
        open_positions_query = select(
            func.count(orders.c.id).label('count'),
            func.sum(orders.c.pnl).label('total_pnl')
        ).where(
            orders.c.status == 'OPEN'
        )
        
        positions_result = await session.execute(open_positions_query)
        positions_row = positions_result.first()
        open_positions_count = int(positions_row.count) if positions_row.count else 0
        today_pnl = float(positions_row.total_pnl) if positions_row.total_pnl else 0.0
        
        # Format the response
        dashboard_summary = {
            "total_balance": {
                "amount": today_total_balance,
                "change": balance_change,
                "change_percentage": round(balance_change_percentage, 2),
                "is_positive": balance_change >= 0
            },
            "todays_pnl": {
                "amount": round(today_pnl, 2),
                "change_percentage": 0.0,  # Placeholder - can be enhanced later
                "is_positive": today_pnl >= 0
            },
            "open_positions": {
                "count": open_positions_count,
                "total_pnl": round(today_pnl, 2)
            },
            "active_strategies": {
                "count": active_strategies_count,
                "profit_count": 0,  # Placeholder
                "loss_count": 0     # Placeholder
            },
            "last_updated": get_ist_datetime().isoformat()
        }
        
        logger.info(f"Dashboard summary generated: Total balance ₹{today_total_balance:,.2f}, Change: {balance_change_percentage:+.2f}%")
        
        return dashboard_summary
        
    except Exception as e:
        logger.error(f"Error fetching dashboard summary: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch dashboard summary")


@router.get("/broker-balances")
async def get_broker_balances_summary(session=Depends(get_db)) -> Dict[str, Any]:
    """
    Get detailed broker balance breakdown for today.
    """
    try:
        today = get_ist_datetime().date()
        
        # Get today's balance by broker
        broker_balances_query = select(
            broker_credentials.c.broker_name,
            broker_balance_summaries.c.summary,
            broker_balance_summaries.c.fetched_at
        ).select_from(
            broker_balance_summaries.join(
                broker_credentials, 
                broker_balance_summaries.c.broker_id == broker_credentials.c.id
            )
        ).where(
            func.date(broker_balance_summaries.c.created_at) == today
        ).order_by(
            broker_balance_summaries.c.fetched_at.desc()
        )
        
        result = await session.execute(broker_balances_query)
        rows = result.fetchall()
        
        broker_details = []
        total_balance = 0.0
        total_available = 0.0
        total_utilized = 0.0
        
        for row in rows:
            # Parse the JSON summary
            summary = row.summary if isinstance(row.summary, dict) else {}
            
            broker_detail = {
                "broker_name": row.broker_name,
                "total_balance": float(summary.get("total_balance", 0.0)),
                "available": float(summary.get("available", 0.0)),
                "utilized": float(summary.get("utilized", 0.0)),
                "last_updated": row.fetched_at.isoformat()
            }
            broker_details.append(broker_detail)
            
            total_balance += broker_detail["total_balance"]
            total_available += broker_detail["available"]
            total_utilized += broker_detail["utilized"]
        
        return {
            "brokers": broker_details,
            "summary": {
                "total_balance": total_balance,
                "total_available": total_available,
                "total_utilized": total_utilized,
                "broker_count": len(broker_details)
            },
            "last_updated": get_ist_datetime().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error fetching broker balances summary: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch broker balances summary")


@router.get("/open-positions")
async def get_open_positions_count(session=Depends(get_db)) -> Dict[str, Any]:
    """
    Get count of open positions and their details.
    """
    try:
        # Get open orders count
        open_orders_query = select(
            func.count(orders.c.id).label('count')
        ).where(
            orders.c.status == 'OPEN'
        )
        
        open_orders_result = await session.execute(open_orders_query)
        open_orders_row = open_orders_result.first()
        open_positions_count = int(open_orders_row.count) if open_orders_row.count else 0
        
        # Get open orders details for additional info
        open_orders_details_query = select(
            orders.c.id,
            orders.c.symbol,
            orders.c.qty,
            orders.c.entry_price,
            orders.c.current_price,
            orders.c.pnl,
            orders.c.entry_time,
            orders.c.strategy_id
        ).where(
            orders.c.status == 'OPEN'
        ).order_by(
            orders.c.entry_time.desc()
        )
        
        details_result = await session.execute(open_orders_details_query)
        open_orders_details = details_result.fetchall()
        
        # Calculate total PnL for open positions
        total_pnl = 0.0
        positions_details = []
        
        for order in open_orders_details:
            order_dict = dict(order)
            positions_details.append({
                "order_id": order_dict["id"],
                "symbol": order_dict["symbol"],
                "quantity": order_dict["qty"],
                "entry_price": float(order_dict["entry_price"]) if order_dict["entry_price"] else 0.0,
                "current_price": float(order_dict["current_price"]) if order_dict["current_price"] else 0.0,
                "pnl": float(order_dict["pnl"]) if order_dict["pnl"] else 0.0,
                "entry_time": order_dict["entry_time"].isoformat() if order_dict["entry_time"] else None,
                "strategy_id": order_dict["strategy_id"]
            })
            
            if order_dict["pnl"]:
                total_pnl += float(order_dict["pnl"])
        
        return {
            "open_positions_count": open_positions_count,
            "total_pnl": round(total_pnl, 2),
            "positions": positions_details,
            "last_updated": get_ist_datetime().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error fetching open positions: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch open positions")
