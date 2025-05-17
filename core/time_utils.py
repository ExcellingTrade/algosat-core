import asyncio
from datetime import datetime, timedelta, date
from rich.console import Console
from rich.progress import Progress, BarColumn, TextColumn, TimeElapsedColumn, TimeRemainingColumn
from utils.utils import localize_to_ist, get_ist_datetime
from rich.logging import RichHandler
import logging

# Configure the logger
logging.basicConfig(level=logging.INFO, handlers=[RichHandler()])
logger = logging.getLogger("CandleLogger")

async def wait_for_first_candle_completion(interval_minutes, first_candle_time):
    current_time = get_ist_datetime()
    console = Console(width=150)
    first_candle_start = datetime.combine(current_time.date(),
                                          datetime.strptime(first_candle_time, "%H:%M").time())
    first_candle_close = localize_to_ist(first_candle_start + timedelta(minutes=interval_minutes))
    if current_time >= first_candle_close:
        logger.info("⏰ First candle has already completed.")
        return
    wait_time = (first_candle_close - current_time).total_seconds()
    human_readable_time = str(timedelta(seconds=wait_time)).split(".")[0]
    logger.info(f"Waiting for the first candle to complete. Estimated time remaining: {human_readable_time}.")
    with Progress(
            TextColumn("[blue bold]{task.description}[/]"),
            BarColumn(),
            TextColumn("[green]{task.completed} seconds elapsed[/]"),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            transient=True,  # Progress bar disappears after completion
            console=console
    ) as progress:
        task = progress.add_task(
            description="Waiting for first candle completion",
            total=wait_time
        )
        while not progress.finished:
            await asyncio.sleep(1)
            progress.update(task, advance=1)
    logger.info("✓ First candle completed. Waiting additional 20 seconds...")
    await asyncio.sleep(20)

def calculate_first_candle_details(current_date, first_candle_time, interval_minutes):
    try:
        first_candle_start = datetime.combine(current_date,
                                              datetime.strptime(first_candle_time, "%H:%M").time())
        first_candle_close = first_candle_start #+ timedelta(minutes=interval_minutes)
        from_date = first_candle_start
        to_date = first_candle_close
        return {
            "first_candle_start": first_candle_start,
            "first_candle_close": first_candle_close,
            "from_date": from_date,
            "to_date": to_date,
        }
    except Exception as error:
        raise ValueError(f"Error calculating first candle details: {error}")
