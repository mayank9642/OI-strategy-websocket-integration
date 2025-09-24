"""
Logging setup utility module
Import this at the start of any script to ensure consistent logging
"""
import os
import logging
import logging.handlers
import datetime
from pathlib import Path

def setup_logging(clear_logs=False):
    """
    Set up consistent logging configuration for all scripts
    
    Args:
        clear_logs (bool): If True, clear existing log files
    """
    # Get the project base directory (one level up from this file)
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    # Ensure logs directory exists
    logs_dir = os.path.join(base_dir, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    
    # Clear log files if requested
    if clear_logs:
        log_files = [os.path.join(logs_dir, 'strategy.log'), os.path.join(logs_dir, 'strategy_run.log')]
        for log_file in log_files:
            with open(log_file, 'w') as f:
                f.write(f"Log file cleared on {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    # Create a direct debug file to verify the function is being called
    with open(os.path.join(logs_dir, 'debug_log_setup.txt'), 'w') as f:
        f.write(f"Log setup function was called at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    # Configure root logger with both console and file handlers
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # Clear any existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    # Create formatter
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
      # Add console handler with stream lock for thread safety
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.createLock()
    logger.addHandler(console_handler)
    
    # Add file handler for strategy log with file lock
    strategy_log_handler = logging.FileHandler(os.path.join(logs_dir, 'strategy.log'), mode='a')
    strategy_log_handler.setFormatter(formatter)
    logger.addHandler(strategy_log_handler)
    
    # Add a separate file handler for strategy_run.log
    run_log_handler = logging.FileHandler(os.path.join(logs_dir, 'strategy_run.log'), mode='a')
    run_log_handler.setFormatter(formatter)
    logger.addHandler(run_log_handler)
    
    # Log a direct message to verify
    logger.info("Logging configured with log_setup utility")
    
    # Return the configured logger
    return logger

# Auto-setup when imported
logger = setup_logging()
