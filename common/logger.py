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
import traceback
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

import colorlog
from filelock import FileLock

from common import constants

# Constants for logging configuration
MAX_LOG_FILE_SIZE = int(2.3 * 1024 * 1024)  # 2.3 MB
BACKUP_COUNT = 7
DEFAULT_LOG_LEVEL = logging.INFO

# Create a dictionary to store configured loggers (module_name -> logger)
_LOGGERS = {}

# Root logger configuration (done once)
_ROOT_LOGGER_CONFIGURED = False


def _ensure_log_directories():
    """Ensure all necessary log directories exist."""
    os.makedirs(constants.LOG_DIR, exist_ok=True)
    os.makedirs(constants.FYER_LOG_DIR, exist_ok=True)


def get_log_file():
    """
    Determine the log file name dynamically based on the executed script.
    
    :return: The log file path.
    """
    try:
        # Get the name of the main script being executed
        main_module = sys.modules.get('__main__')
        if not main_module or not hasattr(main_module, '__file__'):
            # Fallback for interactive sessions or other edge cases
            script_name = "console"
        else:
            script_path = Path(main_module.__file__)
            script_name = script_path.stem  # Get filename without extension
        
        # Get today's date in YYYY-MM-DD format
        today_date = datetime.now().strftime("%Y-%m-%d")
        
        # Create the log file path
        log_file = os.path.join(constants.LOG_DIR, f"{script_name}-live-{today_date}.log")
        return log_file
    except Exception as e:
        # Print the error and stack trace for debugging
        print(f"Error determining log file: {e}")
        traceback.print_exc()
        
        # Use a fallback log file if any error occurs
        fallback_log = os.path.join(constants.LOG_DIR, "fallback.log")
        return fallback_log


def configure_root_logger():
    """Configure the root logger with basic settings."""
    global _ROOT_LOGGER_CONFIGURED
    
    if _ROOT_LOGGER_CONFIGURED:
        return
    
    # Ensure the log directories exist
    _ensure_log_directories()
    
    # Configure the root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    
    # Console handler for the root logger
    console_formatter = colorlog.ColoredFormatter(
        "%(log_color)s%(asctime)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        log_colors={
            "DEBUG": "cyan",
            "INFO": "green",
            "WARNING": "yellow",
            "ERROR": "red",
            "CRITICAL": "red,bg_white",
        },
    )
    
    console_handler = colorlog.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)
    
    _ROOT_LOGGER_CONFIGURED = True


def get_logger(module_name: str) -> logging.Logger:
    """
    Get or configure a logger for the specified module.
    This is the recommended function to use when getting loggers.
    
    :param module_name: The name of the module requesting the logger.
    :return: Configured logger instance.
    """
    # Check if this logger is already configured
    if module_name in _LOGGERS:
        return _LOGGERS[module_name]
    
    # Configure the root logger if not done already
    configure_root_logger()
    
    # Get the log file path
    log_file = get_log_file()
    log_lock_file = f"{log_file}.lock"
    
    # Create or get logger for the module
    logger = logging.getLogger(module_name)
    
    # Set module-specific log level
    log_level = constants.LOG_LEVELS.get(module_name, 
                                         constants.LOG_LEVELS.get("default", DEFAULT_LOG_LEVEL))
    
    # Convert string level to actual level
    if isinstance(log_level, str):
        log_level = getattr(logging, log_level)
    
    logger.setLevel(log_level)
    
    # File formatter with detailed information
    file_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(filename)s:%(lineno)d - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    
    # Function to safely rotate logs with a lock
    def rotate_log(src, dest):
        """Safely rotate logs with a lock, ensuring lock file is only created during rotation."""
        try:
            with FileLock(log_lock_file):
                if os.path.exists(src):
                    os.replace(src, dest)
        except Exception as e:
            print(f"Error rotating logs: {e}")
        finally:
            if os.path.exists(log_lock_file):
                os.remove(log_lock_file)
    
    # Add file handler
    try:
        file_handler = RotatingFileHandler(
            log_file, maxBytes=MAX_LOG_FILE_SIZE, backupCount=BACKUP_COUNT, encoding="utf-8"
        )
        file_handler.setLevel(logging.DEBUG)  # File logs everything
        file_handler.setFormatter(file_formatter)
        file_handler.rotator = rotate_log
        
        logger.addHandler(file_handler)
    except Exception as e:
        # If file handler fails, log the error to console but continue
        print(f"Error setting up file handler for logger: {e}")
        traceback.print_exc()
    
    # Store the configured logger for future use
    _LOGGERS[module_name] = logger
    
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
