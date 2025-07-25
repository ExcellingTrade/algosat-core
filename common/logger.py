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
import os
# Ensure all logging and time functions use IST (Asia/Kolkata)
os.environ['TZ'] = 'Asia/Kolkata'
time.tzset()
import traceback
from datetime import datetime, timezone, timedelta
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler

from algosat.common import constants
from algosat.core.time_utils import get_ist_now 


class SafeRotatingFileHandler(RotatingFileHandler):
    """
    Custom RotatingFileHandler that keeps rollover files in the same date directory.
    """
    
    def __init__(self, filename, mode='a', maxBytes=0, backupCount=0, encoding=None, delay=False):
        """
        Initialize with date directory support for rollovers.
        """
        # Ensure the directory exists
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        super().__init__(filename, mode, maxBytes, backupCount, encoding, delay)
    
    def doRollover(self):
        """
        Override to keep rollover files in the same date directory.
        """
        if self.stream:
            self.stream.close()
            self.stream = None
        
        # Get the directory and base name
        log_dir = os.path.dirname(self.baseFilename)
        base_name = os.path.basename(self.baseFilename)
        
        # Ensure directory exists
        os.makedirs(log_dir, exist_ok=True)
        
        # Rotate existing backup files
        if self.backupCount > 0:
            for i in range(self.backupCount - 1, 0, -1):
                sfn = os.path.join(log_dir, f"{base_name}.{i}")
                dfn = os.path.join(log_dir, f"{base_name}.{i + 1}")
                if os.path.exists(sfn):
                    if os.path.exists(dfn):
                        os.remove(dfn)
                    os.rename(sfn, dfn)
            
            # Move current file to .1
            dfn = os.path.join(log_dir, f"{base_name}.1")
            if os.path.exists(dfn):
                os.remove(dfn)
            if os.path.exists(self.baseFilename):
                os.rename(self.baseFilename, dfn)
        
        # Create new log file
        if not self.delay:
            self.stream = self._open()


class SafeTimedRotatingFileHandler(TimedRotatingFileHandler):
    """
    Custom TimedRotatingFileHandler that handles missing directories gracefully
    and keeps all log files (including rollovers) in date-specific directories.
    
    This prevents FileNotFoundError when the log cleanup process removes
    date directories that the handler is trying to access during rollover.
    """
    
    def __init__(self, filename, when='h', interval=1, backupCount=0, encoding=None, delay=False, utc=False, atTime=None):
        """
        Initialize with date directory support for rollovers.
        """
        # Ensure the directory exists
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        super().__init__(filename, when, interval, backupCount, encoding, delay, utc, atTime)
    
    def getFilesToDelete(self):
        """
        Override to handle missing directories gracefully and only look in the same date directory.
        """
        try:
            # Get the directory of the current log file
            log_dir = os.path.dirname(self.baseFilename)
            if not os.path.exists(log_dir):
                return []
            
            # Get base filename without path
            base_name = os.path.basename(self.baseFilename)
            
            # Look for rollover files in the same date directory only
            files_to_delete = []
            if os.path.exists(log_dir):
                for filename in os.listdir(log_dir):
                    # Check if it's a rollover file of this log
                    if filename.startswith(base_name) and filename != base_name:
                        full_path = os.path.join(log_dir, filename)
                        if os.path.isfile(full_path):
                            files_to_delete.append(full_path)
            
            # Sort and keep only the ones beyond backupCount
            files_to_delete.sort()
            if len(files_to_delete) <= self.backupCount:
                return []
            
            return files_to_delete[:-self.backupCount] if self.backupCount > 0 else files_to_delete
            
        except (FileNotFoundError, OSError) as e:
            # If the directory doesn't exist, just return empty list
            return []
    
    def doRollover(self):
        """
        Override to handle missing directories during rollover and keep files in date directories.
        """
        try:
            # Ensure the directory exists before rollover
            log_dir = os.path.dirname(self.baseFilename)
            os.makedirs(log_dir, exist_ok=True)
            
            # Close the current file
            if self.stream:
                self.stream.close()
                self.stream = None
            
            # Get current time for rollover
            current_time = int(time.time())
            dst_name = self.rotation_filename(self.baseFilename + "." + 
                                            time.strftime(self.suffix, time.localtime(current_time)))
            
            # Ensure rollover file stays in the same date directory
            dst_name = os.path.join(log_dir, os.path.basename(dst_name))
            
            # Rotate the file
            if os.path.exists(self.baseFilename):
                os.rename(self.baseFilename, dst_name)
            
            # Clean up old files
            if self.backupCount > 0:
                for s in self.getFilesToDelete():
                    try:
                        os.remove(s)
                    except OSError:
                        pass
            
            # Create new log file
            if not self.delay:
                self.stream = self._open()
                
        except (FileNotFoundError, OSError) as e:
            # If rollover fails due to missing directory, recreate and continue
            try:
                log_dir = os.path.dirname(self.baseFilename)
                os.makedirs(log_dir, exist_ok=True)
                # Reset the handler to use the current log file
                if not self.delay:
                    self.stream = self._open()
            except Exception as inner_e:
                # If we still can't create the directory, fall back to console logging
                print(f"Critical logging error: {inner_e}", file=sys.stderr) 

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

log_dir = os.path.join(os.path.dirname(__file__), '../../logs')


def _ensure_all_directories():
    """Ensure all required directories exist and remove unwanted ones."""
    wanted_dirs = [
        constants.LOG_DIR,
        constants.CACHE_DIR,
        getattr(constants, 'BACKTEST_RESULTS_DIR', None),
        getattr(constants, 'FYER_LOG_DIR', None),
    ]
    for d in wanted_dirs:
        if d:
            os.makedirs(d, exist_ok=True)
    # Optionally, remove unwanted/legacy folders here if you have a list
    # Example: remove old temp folders, etc.
    # for old_dir in ["/opt/algosat/old_logs", ...]:
    #     if os.path.exists(old_dir):
    #         shutil.rmtree(old_dir)


def _ensure_log_directories():
    """Ensure only the logs directory exists."""
    os.makedirs(constants.LOG_DIR, exist_ok=True)


def get_log_file():
    """
    Return the single daily log file for the whole project.
    """
    today_date = get_ist_now().strftime("%Y-%m-%d")
    date_dir = os.path.join(constants.LOG_DIR, today_date)
    os.makedirs(date_dir, exist_ok=True)
    log_file = os.path.join(date_dir, f"algosat-{today_date}.log")
    return log_file


class ISTFormatter(logging.Formatter):
    """Custom formatter to display log times in IST (Asia/Kolkata)."""
    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created, tz=timezone.utc).astimezone(
            timezone(timedelta(hours=5, minutes=30))
        )
        if datefmt:
            s = dt.strftime(datefmt)
        else:
            s = dt.strftime("%Y-%m-%d %H:%M:%S")
        return s


# Update all formatters to include line number
# For file handler
file_formatter = ISTFormatter(
    "%(asctime)s - %(name)s - %(filename)s:%(lineno)d - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
# For console handler (RichHandler)
console_formatter = ISTFormatter(
    "%(asctime)s | %(levelname)s | %(filename)s:%(lineno)d | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def configure_root_logger():
    """Configure the root logger with a single daily rotating file handler and color console handler."""
    global _ROOT_LOGGER_CONFIGURED
    if _ROOT_LOGGER_CONFIGURED:
        return
    _ensure_all_directories()
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # File handler: DEBUG level, daily file, rotation by size
    log_file = get_log_file()
    file_handler = SafeRotatingFileHandler(
        log_file, maxBytes=MAX_LOG_FILE_SIZE, backupCount=BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(file_formatter)
    root_logger.addHandler(file_handler)

    # Console handler: INFO+ with ISTFormatter
    for handler in root_logger.handlers:
        if isinstance(handler, RichHandler):
            handler.setFormatter(console_formatter)

    # --- Auto cleanup of old logs (7 days) ---
    try:
        from core.time_utils import get_ist_datetime
        now = get_ist_datetime()
        for log_file in glob.glob(os.path.join(constants.LOG_DIR, "*.log*")):
            file_time = datetime.fromtimestamp(os.path.getmtime(log_file)).astimezone(now.tzinfo).date()
            if (now.date() - file_time).days > 7:
                os.remove(log_file)
                root_logger.debug(f"Deleted old log file: {log_file}")
    except Exception as e:
        root_logger.error(f"Error during log auto-cleanup: {e}", exc_info=True)

    _ROOT_LOGGER_CONFIGURED = True


def get_logger(module_name: str) -> logging.Logger:
    """
    Get or configure a logger for the specified module.
    - All loggers whose name starts with 'api.' will log to logs/api-YYYY-MM-DD.log (rotated daily)
    - All others log to the main daily log file
    """
    logger = logging.getLogger(module_name)
    
    # Always check if we need to update the log file for today's date
    # This handles cases where the process runs across midnight
    today = get_ist_now().strftime('%Y-%m-%d')
    date_dir = os.path.join(log_dir, today)
    os.makedirs(date_dir, exist_ok=True)
    
    if module_name.startswith("api."):
        expected_log_file = os.path.join(date_dir, f"api-{today}.log")
    elif module_name == "broker_monitor":
        expected_log_file = os.path.join(date_dir, f"broker_monitor-{today}.log")
    else:
        expected_log_file = os.path.join(date_dir, f"algosat-{today}.log")
    
    # Check if logger needs new handler for today's date
    needs_new_handler = True
    if logger.handlers:
        for handler in logger.handlers:
            if isinstance(handler, SafeTimedRotatingFileHandler):
                if handler.baseFilename == expected_log_file:
                    needs_new_handler = False
                    break
                else:
                    # Remove old handler with wrong date
                    logger.removeHandler(handler)
                    handler.close()
    
    if needs_new_handler:
        # Use SafeRotatingFileHandler for size-based rotation instead of time-based
        # This keeps all rollover files in the same date directory with proper numbering
        file_handler = SafeRotatingFileHandler(
            expected_log_file,
            maxBytes=MAX_LOG_FILE_SIZE,  # 2.3 MB
            backupCount=7,
            encoding="utf-8"
        )
        file_handler.setLevel(logging.DEBUG)
        file_formatter = ISTFormatter(
            "%(asctime)s - %(name)s - %(filename)s:%(lineno)d - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
        logger.setLevel(logging.DEBUG)
    
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
    - General logs: Retain files for 7 days (updated from 3).
    - Cache files: Retain files for 15 days.
    - Backtest files: Retain files for 15 days.
    """
    logger = get_logger("logger_cleanup")
    
    try:
        from algosat.core.time_utils import get_ist_datetime
        now = get_ist_datetime()
        
        # Cleanup logs in Fyer folder (keep 3-day files)
        for log_file in glob.glob(os.path.join(constants.FYER_LOG_DIR, "*.log*")):
            file_time = datetime.fromtimestamp(os.path.getmtime(log_file)).astimezone(now.tzinfo).date()
            if (now.date() - file_time).days > 3:
                os.remove(log_file)
                logger.debug(f"Deleted old log file: {log_file}")
        
        # Cleanup general logs (keep 7-day files)
        for date_dir in os.listdir(log_dir):
            full_date_dir = os.path.join(log_dir, date_dir)
            if not os.path.isdir(full_date_dir):
                continue
            try:
                dir_date = datetime.strptime(date_dir, "%Y-%m-%d").date()
            except Exception:
                continue  # skip non-date dirs
            if (now.date() - dir_date).days > 1:
                import shutil
                shutil.rmtree(full_date_dir)
                logger.debug(f"Deleted old log directory: {full_date_dir}")
        
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


def clean_broker_monitor_logs():
    """Remove broker_monitor logs older than 1 day from the logs directory."""
    try:
        from algosat.core.time_utils import get_ist_datetime
        now = get_ist_datetime()
        log_dir = os.path.join(os.path.dirname(__file__), '../../logs')
        for date_dir in os.listdir(log_dir):
            full_date_dir = os.path.join(log_dir, date_dir)
            if not os.path.isdir(full_date_dir):
                continue
            for fname in os.listdir(full_date_dir):
                if fname.startswith("broker_monitor-") and fname.endswith(".log"):
                    fpath = os.path.join(full_date_dir, fname)
                    file_time = datetime.fromtimestamp(os.path.getmtime(fpath)).astimezone(now.tzinfo)
                    if (now - file_time).days > 1:
                        os.remove(fpath)
                        print(f"Deleted old broker_monitor log: {fpath}")
    except Exception as e:
        print(f"Error during broker_monitor log cleanup: {e}")


# Example usage
# (Removed __main__ block; call cleanup_logs_and_cache and clean_broker_monitor_logs from your main app entrypoint)
