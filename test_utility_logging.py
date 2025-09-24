"""
Test script that uses the logging utility
"""
import sys
import os
import traceback

# Ensure we can import from the current directory
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# Import the logging utility first
from src.log_setup import logger

# Log test messages
logger.info("This is a test message from the utility-based logging")
logger.warning("This is a warning message from the utility-based logging")

# Try importing and initializing the strategy
try:
    from src.strategy import OpenInterestStrategy
    strategy = OpenInterestStrategy()
    logger.info("Successfully imported and initialized strategy with utility-based logging")
except Exception as e:
    logger.error(f"Error initializing strategy: {e}")
    logger.error(traceback.format_exc())

print("Test completed. Check logs/strategy.log to see if messages were logged.")
