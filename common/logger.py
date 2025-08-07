"""
logger.py

This module provides a flexible logging setup for use across different components
of the application.

Features:
- Dynamically generates log filenames based on the executed script.
- Supports rotating file logs by size (2.3 MB max per file) and retaining up to 7 days of logs.
- Includes console logging with colored output for better readability.
- Allows module-specific log levels configurable via constants.
- Strategy-aware logging: Automatically routes logs to strategy-specific files based on execution context.

Usage:
    from common.logger import get_logger, set_strategy_context
    
    # Basic usage
    logger = get_logger(__name__)
    logger.info("This is an INFO message.")
    
    # Strategy-aware usage
    with set_strategy_context("option_buy"):
        logger.info("This will go to option_buy-YYYY-MM-DD.log")
"""
import glob
import logging
import os
import sys
import time
import re  # Add regex import
import os
# Ensure all logging and time functions use IST (Asia/Kolkata)
os.environ['TZ'] = 'Asia/Kolkata'
time.tzset()
import traceback
from datetime import datetime, timezone, timedelta
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from pathlib import Path
from contextvars import ContextVar
from contextlib import contextmanager
from typing import Optional

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

# Strategy context variable for async-safe strategy tracking
_strategy_context: ContextVar[Optional[str]] = ContextVar('strategy_context', default=None)

# Create a dictionary to store configured loggers (module_name -> logger)
_LOGGERS = {}

# Root logger configuration (done once)
_ROOT_LOGGER_CONFIGURED = False


@contextmanager
def set_strategy_context(strategy_name: str):
    """
    Context manager to set the current strategy context for logging.
    
    Usage:
        with set_strategy_context("option_buy"):
            logger.info("This will go to option_buy-YYYY-MM-DD.log")
    """
    token = _strategy_context.set(strategy_name.lower())
    try:
        yield
    finally:
        _strategy_context.reset(token)


def get_current_strategy_context() -> Optional[str]:
    """Get the current strategy context, if any."""
    return _strategy_context.get(None)


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


def get_strategy_aware_log_file(module_name: str) -> str:
    """
    Get the appropriate log file based on module name and current strategy context.
    
    Priority:
    1. API modules -> api-YYYY-MM-DD.log (ignores strategy context)
    2. Broker monitor -> broker_monitor-YYYY-MM-DD.log (ignores strategy context)
    3. Strategy context (if set) -> strategy_name-YYYY-MM-DD.log
    4. Default -> algosat-YYYY-MM-DD.log
    """
    today = get_ist_now().strftime('%Y-%m-%d')
    date_dir = os.path.join(constants.LOG_DIR, today)
    os.makedirs(date_dir, exist_ok=True)
    
    # API and broker_monitor always get their own files (ignore strategy context)
    if module_name.startswith("api."):
        return os.path.join(date_dir, f"api-{today}.log")
    elif module_name == "broker_monitor":
        return os.path.join(date_dir, f"broker_monitor-{today}.log")
    
    # Check strategy context for other modules
    strategy_context = get_current_strategy_context()
    if strategy_context:
        return os.path.join(date_dir, f"{strategy_context}-{today}.log")
    
    # Default fallback
    return os.path.join(date_dir, f"algosat-{today}.log")


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


class StrategyAwareFileHandler(logging.FileHandler):
    """
    Custom FileHandler that dynamically routes logs to strategy-specific files
    based on the current strategy context at the time of logging.
    """
    
    def __init__(self, module_name: str, mode='a', encoding=None, delay=False):
        self.module_name = module_name
        self.current_file = None
        self.current_stream = None
        # Initialize with default log file
        default_file = get_strategy_aware_log_file(module_name)
        super().__init__(default_file, mode, encoding, delay)
    
    def _get_current_log_file(self):
        """Get the appropriate log file based on current strategy context."""
        return get_strategy_aware_log_file(self.module_name)
    
    def emit(self, record):
        """
        Emit a record, dynamically routing to the correct file based on current context.
        """
        # Get the log file for current context
        target_file = self._get_current_log_file()
        
        # If target file changed, switch the stream
        if target_file != self.current_file:
            # Close current stream if it exists
            if self.current_stream:
                self.current_stream.close()
            
            # Ensure directory exists
            os.makedirs(os.path.dirname(target_file), exist_ok=True)
            
            # Open new stream
            self.current_file = target_file
            self.baseFilename = target_file  # Update baseFilename for logging framework
            self.current_stream = open(target_file, self.mode, encoding=self.encoding)
            self.stream = self.current_stream
        
        # Emit the record using parent class logic
        super().emit(record)
        
        # Ensure immediate write
        if self.stream:
            self.stream.flush()
    
    def close(self):
        """Close the handler and clean up streams."""
        if self.current_stream:
            self.current_stream.close()
            self.current_stream = None
        super().close()


def get_logger(module_name: str) -> logging.Logger:
    """
    Get or configure a logger for the specified module with strategy-aware routing.
    
    Uses a custom handler that dynamically routes logs based on current strategy context
    at the time each log message is written (not when logger is created).
    
    - Strategy context logs: logs/YYYY-MM-DD/strategy_name-YYYY-MM-DD.log
    - API logs: logs/YYYY-MM-DD/api-YYYY-MM-DD.log
    - Broker monitor logs: logs/YYYY-MM-DD/broker_monitor-YYYY-MM-DD.log  
    - Default logs: logs/YYYY-MM-DD/algosat-YYYY-MM-DD.log
    """
    logger = logging.getLogger(module_name)
    
    # Check if logger already has our custom handler
    has_strategy_handler = any(
        isinstance(handler, StrategyAwareFileHandler) 
        for handler in logger.handlers
    )
    
    if not has_strategy_handler:
        # Remove any existing file handlers to avoid duplicates
        for handler in list(logger.handlers):
            if isinstance(handler, (logging.FileHandler, logging.handlers.RotatingFileHandler)):
                logger.removeHandler(handler)
                handler.close()
        
        # Add our strategy-aware handler
        strategy_handler = StrategyAwareFileHandler(module_name)
        strategy_handler.setLevel(logging.DEBUG)
        
        file_formatter = ISTFormatter(
            "%(asctime)s - %(name)s - %(filename)s:%(lineno)d - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        strategy_handler.setFormatter(file_formatter)
        logger.addHandler(strategy_handler)
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
        
        # Cleanup general logs (keep 7-day files, but clean up old rollover files)
        for date_dir in os.listdir(log_dir):
            full_date_dir = os.path.join(log_dir, date_dir)
            if not os.path.isdir(full_date_dir):
                continue
            try:
                dir_date = datetime.strptime(date_dir, "%Y-%m-%d").date()
            except Exception:
                continue  # skip non-date dirs
            
            # Keep logs for 7 days, but clean up old rollover files from bad implementation
            if (now.date() - dir_date).days > 7:
                import shutil
                shutil.rmtree(full_date_dir)
                logger.debug(f"Deleted old log directory: {full_date_dir}")
            else:
                # Clean up unnecessary rollover files in current directories
                try:
                    for log_file in os.listdir(full_date_dir):
                        # Remove .1, .2, .3 etc rollover files that were created incorrectly
                        if re.match(r'.*\.log\.\d+$', log_file):
                            rollover_path = os.path.join(full_date_dir, log_file)
                            os.remove(rollover_path)
                            logger.debug(f"Cleaned up incorrect rollover file: {rollover_path}")
                except Exception as cleanup_error:
                    logger.warning(f"Error cleaning rollover files in {full_date_dir}: {cleanup_error}")
        
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
                    if (now - file_time).days > 7:
                        os.remove(fpath)
                        print(f"Deleted old broker_monitor log: {fpath}")
    except Exception as e:
        print(f"Error during broker_monitor log cleanup: {e}")


# Example usage
# (Removed __main__ block; call cleanup_logs_and_cache and clean_broker_monitor_logs from your main app entrypoint)
