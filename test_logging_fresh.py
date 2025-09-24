"""
Test logging to verify if it's working properly
"""
import os
import sys

# Add the project directory to path
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# Import the logging utility
from src.log_setup import logger, setup_logging

# Force a fresh setup with cleared logs
logger = setup_logging(clear_logs=True)

# Log some test messages
logger.debug("This is a DEBUG message")
logger.info("This is an INFO message")
logger.warning("This is a WARNING message")
logger.error("This is an ERROR message")

print("Test complete. Check the logs/strategy.log file.")
