"""
logger.py

This module provides a flexible logging setup for use across different components
of the application.

Features:
- Dynamically generates log filenames based on the executed script.
- Supports rotating file logs by size (2.3 MB max per file) and retaining up to 7 days of logs.
- Includes console logging with colored output for better readability.
- Allows module-specific log levels configurable via constants.

Usage:
    from common.logger import get_logger
    
    logger = get_logger(__name__)  # Pass the module name for log level configuration
    logger.info("This is an INFO message.")
    logger.debug("This is a DEBUG message.")
"""
import glob
import logging
import os
import sys
import time
import traceback
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler

from common import constants
from core.time_utils import get_ist_now 

# Constants for logging configuration
MAX_LOG_FILE_SIZE = int(2.3 * 1024 * 1024)  # 2.3 MB
BACKUP_COUNT = 7
DEFAULT_LOG_LEVEL = logging.INFO

# Create a dictionary to store configured loggers (module_name -> logger)
_LOGGERS = {}

# Root logger configuration (done once)
_ROOT_LOGGER_CONFIGURED = False


# --- Console Handler Improvements: RichHandler with custom colors and minimal output ---
console = Console()

# Custom log level styles for RichHandler
level_styles = {
    "DEBUG": "cyan",
    "INFO": "green",
    "WARNING": "yellow",
    "ERROR": "bold red",
    "CRITICAL": "bold magenta"
}

class ColorfulLogFormatter(logging.Formatter):
    def format(self, record):
        levelname = record.levelname
        color = level_styles.get(levelname, "")
        record.levelname = f"[{color}]{levelname}[/{color}]"
        return super().format(record)

# Use RichHandler for pretty, minimal, colored console output
console_handler = RichHandler(
    console=console,
    show_time=True,      # Show HH:MM:SS (local/IST)
    show_level=True,     # Colored log level
    show_path=False,     # Hide module/file in console for clarity
    markup=True,         # Allow color markup in log messages
    rich_tracebacks=True
)
console_handler.setLevel(logging.INFO)  # Only show INFO and above in console

# Optional: attach custom formatter for color (RichHandler already styles, but for extra control)
console_formatter = logging.Formatter(
    "%(message)s"
)
console_handler.setFormatter(console_formatter)

# Remove ISTFormatter usage for console (let RichHandler handle time nicely)
# Only add the handler if not already present
if not any(isinstance(h, RichHandler) for h in logging.getLogger().handlers):
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(console_handler)

# Suppress unwanted logs from external modules in the console (e.g., SmartAPI/angel/zerodha/fyers)
logging.getLogger("smartConnect").setLevel(logging.WARNING)
logging.getLogger("SmartAPI").setLevel(logging.WARNING)
logging.getLogger("angel").setLevel(logging.WARNING)
logging.getLogger("zerodha").setLevel(logging.WARNING)
logging.getLogger("fyers").setLevel(logging.WARNING)


def _ensure_log_directories():
    """Ensure only the logs directory exists."""
    os.makedirs(constants.LOG_DIR, exist_ok=True)


def get_log_file():
    """
    Return the single daily log file for the whole project.
    """
    today_date = get_ist_now().strftime("%Y-%m-%d")
    log_file = os.path.join(constants.LOG_DIR, f"algosat-{today_date}.log")
    return log_file


def configure_root_logger():
    """Configure the root logger with a single daily rotating file handler and color console handler."""
    global _ROOT_LOGGER_CONFIGURED
    if _ROOT_LOGGER_CONFIGURED:
        return
    _ensure_log_directories()
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # File handler: DEBUG level, daily file, rotation by size
    log_file = get_log_file()
    file_formatter = ISTFormatter(
        "%(asctime)s - %(name)s - %(filename)s:%(lineno)d - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = RotatingFileHandler(
        log_file, maxBytes=MAX_LOG_FILE_SIZE, backupCount=BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(file_formatter)
    root_logger.addHandler(file_handler)

    _ROOT_LOGGER_CONFIGURED = True


def get_logger(module_name: str) -> logging.Logger:
    """
    Get or configure a logger for the specified module.
    Uses RichHandler for console output and standard file logging.
    """
    # File handler for persistent logs (DEBUG and above)
    logger = logging.getLogger(module_name)
    if not logger.handlers:
        # Add file handler if not already present
        from logging.handlers import RotatingFileHandler
        from datetime import datetime
        import os
        log_dir = os.path.join(os.path.dirname(__file__), '../../logs')
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, f"algosat-{get_ist_now().strftime('%Y-%m-%d')}.log")
        file_handler = RotatingFileHandler(log_file, maxBytes=2*1024*1024, backupCount=7, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
        logger.setLevel(logging.DEBUG)  # Ensure logger emits DEBUG logs
    # logger.propagate = False
    return logger


# For backward compatibility
def configure_logger(module_name: str) -> logging.Logger:
    """
    Legacy function to configure and return a logger for the specified module.
    For new code, use get_logger() instead.
    
    :param module_name: The name of the module requesting the logger.
    :return: Configured logger instance.
    """
    return get_logger(module_name)


def cleanup_logs_and_cache():
    """
    Clean up old logs and cache files based on specified criteria.
    - Logs in Fyer folder: Retain files for 3 days.
    - General logs: Retain files for 3 days.
    - Cache files: Retain files for 15 days.
    - Backtest files: Retain files for 15 days.
    """
    logger = get_logger("logger_cleanup")
    
    try:
        from utils.utils import get_ist_datetime
        now = get_ist_datetime()
        
        # Cleanup logs in Fyer folder (keep 3-day files)
        for log_file in glob.glob(os.path.join(constants.FYER_LOG_DIR, "*.log*")):
            file_time = datetime.fromtimestamp(os.path.getmtime(log_file)).astimezone(now.tzinfo).date()
            if (now.date() - file_time).days > 3:
                os.remove(log_file)
                logger.debug(f"Deleted old log file: {log_file}")
        
        # Cleanup general logs (keep 3-day files)
        for log_file in glob.glob(os.path.join(constants.LOG_DIR, "*.log*")):
            file_time = datetime.fromtimestamp(os.path.getmtime(log_file)).astimezone(now.tzinfo).date()
            if (now.date() - file_time).days > 3:
                os.remove(log_file)
                logger.debug(f"Deleted old log file: {log_file}")
        
        # Cleanup cache files (keep 15-day files)
        for cache_file in glob.glob(os.path.join(constants.CACHE_DIR, "*")):
            file_time = datetime.fromtimestamp(os.path.getmtime(cache_file)).astimezone(now.tzinfo)
            if (now - file_time).days > 15:
                os.remove(cache_file)
                logger.debug(f"Deleted old cache file: {cache_file}")
        
        # Cleanup backtest files (keep 15-day files)
        for backtest_file in glob.glob(os.path.join(constants.BACKTEST_RESULTS_DIR, "*")):
            file_time = datetime.fromtimestamp(os.path.getmtime(backtest_file)).astimezone(now.tzinfo)
            if (now - file_time).days > 15:
                os.remove(backtest_file)
                logger.debug(f"Deleted old backtest file: {backtest_file}")
                
    except Exception as e:
        logger.error(f"Error during log cleanup: {e}", exc_info=True)


# Example usage
if __name__ == "__main__":
    # Clean up old logs
    cleanup_logs_and_cache()
    
    # Use the logger
    logger = get_logger("example_module")
    logger.info("This is an INFO message to test console output.")
    logger.debug("This is a DEBUG message that should go to the file.")
    
    # Test the legacy function too
    legacy_logger = configure_logger("legacy_module")
    legacy_logger.info("This is a message from the legacy logger function.")
