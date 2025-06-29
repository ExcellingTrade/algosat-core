"""
Market Hours Utility Module

This module provides functions to determine if Indian stock markets are open
and control trading operations based on market hours.

Indian Stock Market Hours (NSE/BSE):
- Trading Hours: 9:15 AM to 3:30 PM IST (Monday to Friday)
- Pre-market: 9:00 AM to 9:15 AM IST
- Post-market: 3:40 PM to 4:00 PM IST
- Holidays: As per NSE/BSE calendar
"""

from datetime import datetime, time
import pytz
from typing import Tuple, Dict, Any
from algosat.core.time_utils import get_ist_datetime
from algosat.common.logger import get_logger

logger = get_logger("market_hours")

# Indian Stock Market Hours (IST)
MARKET_OPEN_TIME = time(9, 15)  # 9:15 AM
MARKET_CLOSE_TIME = time(15, 30)  # 3:30 PM
PRE_MARKET_START = time(9, 0)  # 9:00 AM
POST_MARKET_END = time(16, 0)  # 4:00 PM

# Weekend days (0=Monday, 6=Sunday)
WEEKEND_DAYS = [5, 6]  # Saturday, Sunday

def is_market_open() -> bool:
    """
    Check if the Indian stock market is currently open.
    
    Returns:
        bool: True if market is open, False otherwise
    """
    now_ist = get_ist_datetime()
    current_time = now_ist.time()
    current_weekday = now_ist.weekday()
    
    # Check if it's a weekend
    if current_weekday in WEEKEND_DAYS:
        return False
    
    # Check if current time is within market hours
    if MARKET_OPEN_TIME <= current_time <= MARKET_CLOSE_TIME:
        return True
    
    return False

def is_pre_market() -> bool:
    """
    Check if it's pre-market hours (9:00 AM - 9:15 AM IST).
    
    Returns:
        bool: True if it's pre-market, False otherwise
    """
    now_ist = get_ist_datetime()
    current_time = now_ist.time()
    current_weekday = now_ist.weekday()
    
    # Check if it's a weekend
    if current_weekday in WEEKEND_DAYS:
        return False
    
    # Check if current time is within pre-market hours
    if PRE_MARKET_START <= current_time < MARKET_OPEN_TIME:
        return True
    
    return False

def is_post_market() -> bool:
    """
    Check if it's post-market hours (3:30 PM - 4:00 PM IST).
    
    Returns:
        bool: True if it's post-market, False otherwise
    """
    now_ist = get_ist_datetime()
    current_time = now_ist.time()
    current_weekday = now_ist.weekday()
    
    # Check if it's a weekend
    if current_weekday in WEEKEND_DAYS:
        return False
    
    # Check if current time is within post-market hours
    if MARKET_CLOSE_TIME < current_time <= POST_MARKET_END:
        return True
    
    return False

def is_trading_day() -> bool:
    """
    Check if today is a trading day (Monday to Friday, excluding holidays).
    
    Note: This doesn't check for market holidays. You may want to extend
    this to include a holiday calendar check.
    
    Returns:
        bool: True if it's a trading day, False otherwise
    """
    now_ist = get_ist_datetime()
    current_weekday = now_ist.weekday()
    
    # Monday=0, Sunday=6
    return current_weekday not in WEEKEND_DAYS

def get_market_status() -> Dict[str, Any]:
    """
    Get comprehensive market status information.
    
    Returns:
        dict: Market status with detailed information
    """
    now_ist = get_ist_datetime()
    current_time = now_ist.time()
    current_weekday = now_ist.weekday()
    
    market_open = is_market_open()
    pre_market = is_pre_market()
    post_market = is_post_market()
    trading_day = is_trading_day()
    
    # Determine market state
    if not trading_day:
        state = "CLOSED_WEEKEND"
        message = "Market closed - Weekend"
    elif market_open:
        state = "OPEN"
        message = "Market is open for trading"
    elif pre_market:
        state = "PRE_MARKET"
        message = "Pre-market session"
    elif post_market:
        state = "POST_MARKET"
        message = "Post-market session"
    else:
        state = "CLOSED"
        message = "Market closed"
    
    # Calculate time until next market open
    next_open_time = None
    time_until_open = None
    
    if not market_open:
        if trading_day and current_time < MARKET_OPEN_TIME:
            # Market opens today
            next_open_time = datetime.combine(now_ist.date(), MARKET_OPEN_TIME)
            next_open_time = pytz.timezone("Asia/Kolkata").localize(next_open_time)
        else:
            # Market opens next trading day
            days_ahead = 1
            if current_weekday == 4:  # Friday
                days_ahead = 3  # Skip to Monday
            elif current_weekday == 5:  # Saturday
                days_ahead = 2  # Skip to Monday
            
            next_trading_date = now_ist.date().replace(day=now_ist.day + days_ahead)
            next_open_time = datetime.combine(next_trading_date, MARKET_OPEN_TIME)
            next_open_time = pytz.timezone("Asia/Kolkata").localize(next_open_time)
        
        time_until_open = (next_open_time - now_ist).total_seconds()
    
    return {
        "is_open": market_open,
        "is_pre_market": pre_market,
        "is_post_market": post_market,
        "is_trading_day": trading_day,
        "state": state,
        "message": message,
        "current_time": now_ist,  # Return datetime object, not ISO string
        "current_time_iso": now_ist.isoformat(),  # Keep ISO string for API responses
        "next_open_time": next_open_time.isoformat() if next_open_time else None,
        "seconds_until_open": int(time_until_open) if time_until_open else None,
        "market_hours": {
            "open": MARKET_OPEN_TIME.strftime("%H:%M"),
            "close": MARKET_CLOSE_TIME.strftime("%H:%M"),
            "pre_market": PRE_MARKET_START.strftime("%H:%M"),
            "post_market_end": POST_MARKET_END.strftime("%H:%M")
        }
    }

def should_enable_websocket() -> bool:
    """
    Determine if websocket feed should be enabled based on market hours.
    
    Enable websocket during:
    - Pre-market hours (9:00 AM - 9:15 AM)
    - Market hours (9:15 AM - 3:30 PM)
    - Post-market hours (3:30 PM - 4:00 PM)
    
    Returns:
        bool: True if websocket should be enabled, False otherwise
    """
    return is_market_open() or is_pre_market() or is_post_market()

def get_next_market_session_change() -> Tuple[datetime, str]:
    """
    Get the next time when market session will change and what it will change to.
    
    Returns:
        tuple: (next_change_time, next_state)
    """
    now_ist = get_ist_datetime()
    current_time = now_ist.time()
    current_weekday = now_ist.weekday()
    
    # If it's weekend, next change is Monday pre-market
    if current_weekday in WEEKEND_DAYS:
        days_ahead = 7 - current_weekday  # Days until Monday
        next_monday = now_ist.date().replace(day=now_ist.day + days_ahead)
        next_change = datetime.combine(next_monday, PRE_MARKET_START)
        next_change = pytz.timezone("Asia/Kolkata").localize(next_change)
        return next_change, "PRE_MARKET"
    
    # During trading day, find next session change
    if current_time < PRE_MARKET_START:
        # Before pre-market
        next_change = datetime.combine(now_ist.date(), PRE_MARKET_START)
        next_change = pytz.timezone("Asia/Kolkata").localize(next_change)
        return next_change, "PRE_MARKET"
    elif current_time < MARKET_OPEN_TIME:
        # During pre-market
        next_change = datetime.combine(now_ist.date(), MARKET_OPEN_TIME)
        next_change = pytz.timezone("Asia/Kolkata").localize(next_change)
        return next_change, "OPEN"
    elif current_time < MARKET_CLOSE_TIME:
        # During market hours
        next_change = datetime.combine(now_ist.date(), MARKET_CLOSE_TIME)
        next_change = pytz.timezone("Asia/Kolkata").localize(next_change)
        return next_change, "POST_MARKET"
    elif current_time < POST_MARKET_END:
        # During post-market
        next_change = datetime.combine(now_ist.date(), POST_MARKET_END)
        next_change = pytz.timezone("Asia/Kolkata").localize(next_change)
        return next_change, "CLOSED"
    else:
        # After market hours, next change is tomorrow pre-market
        if current_weekday == 4:  # Friday
            days_ahead = 3  # Skip to Monday
        else:
            days_ahead = 1
        
        next_trading_date = now_ist.date().replace(day=now_ist.day + days_ahead)
        next_change = datetime.combine(next_trading_date, PRE_MARKET_START)
        next_change = pytz.timezone("Asia/Kolkata").localize(next_change)
        return next_change, "PRE_MARKET"
