from datetime import datetime, timedelta, date
import pytz
from typing import Optional

# --- Time Utility Functions ---
def get_ist_datetime() -> datetime:
    """
    Get the current datetime in Indian Standard Time (IST).
    :return: A datetime object in IST.
    """
    ist_timezone = pytz.timezone("Asia/Kolkata")
    return datetime.now(ist_timezone)

def localize_to_ist(input_datetime: datetime) -> datetime:
    """
    Localize a naive datetime object to IST or ensure an aware datetime is in IST.
    :param input_datetime: A naive or aware datetime object.
    :return: A datetime object localized to IST timezone.
    """
    ist_timezone = pytz.timezone("Asia/Kolkata")
    if input_datetime.tzinfo is None:
        return ist_timezone.localize(input_datetime)
    else:
        return input_datetime.astimezone(ist_timezone)

def calculate_end_date(current_date: datetime, interval_minutes: int) -> datetime:
    """
    Calculate the end date/time to fetch historical data, ensuring no incomplete candles are included.
    :param current_date:
    :param interval_minutes: Candle interval in minutes.
    :return: Adjusted datetime object for the end date.
    """
    end_date = (current_date - timedelta(minutes=interval_minutes)).replace(second=0, microsecond=0)
    return end_date

def get_ist_now() -> datetime:
    """Return current IST datetime."""
    return get_ist_datetime()

def get_ist_today() -> date:
    """Return current IST date."""
    return get_ist_now().date()

def ist_strftime(dt: datetime, fmt: str) -> str:
    """Format a datetime in IST."""
    return dt.astimezone().strftime(fmt)

def convert_to_epoch(dt_object: Optional[datetime]) -> Optional[int]:
    """
    Convert a datetime object to a Unix epoch timestamp (seconds since 1970-01-01 UTC).
    If the input is None, returns None.
    If the datetime object is naive, it's assumed to be in UTC.
    """
    if dt_object is None:
        return None
    if dt_object.tzinfo is None:
        # Assume UTC if naive, or localize to UTC if that's the desired behavior
        # For Fyers, timestamps are often expected in UTC epoch
        dt_object = pytz.utc.localize(dt_object)
    elif dt_object.tzinfo != pytz.utc:
        dt_object = dt_object.astimezone(pytz.utc)
    
    return int(dt_object.timestamp())

def convert_epoch_to_ist_datetime(epoch_timestamp: int) -> datetime:
    """
    Convert a Unix epoch timestamp to an IST datetime object.
    """
    utc_dt = datetime.fromtimestamp(epoch_timestamp, tz=pytz.utc)
    ist_timezone = pytz.timezone("Asia/Kolkata")
    return utc_dt.astimezone(ist_timezone)
