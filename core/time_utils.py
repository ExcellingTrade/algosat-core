from datetime import datetime, timedelta, date
from utils.utils import localize_to_ist, get_ist_datetime

# --- Time Utility Functions ---
def get_ist_now():
    """Return current IST datetime."""
    from utils.utils import get_ist_datetime
    return get_ist_datetime()

def get_ist_today():
    """Return current IST date."""
    return get_ist_now().date()

def ist_strftime(dt, fmt):
    """Format a datetime in IST."""
    return dt.astimezone().strftime(fmt)
