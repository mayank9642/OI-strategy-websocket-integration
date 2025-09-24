"""
Test script to verify logging configuration
"""
import os
import sys
import logging
import logging.handlers
import datetime

# Ensure logs directory exists
os.makedirs("logs", exist_ok=True)

# Clear the strategy.log file to ensure we see new entries
with open('logs/strategy.log', 'w') as f:
    f.write(f"Log file cleared on {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

# Configure root logger with both console and file handlers
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Clear any existing handlers
for handler in logger.handlers[:]:
    logger.removeHandler(handler)

# Create formatter
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

# Add console handler
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# Add file handler for strategy log
file_handler = logging.handlers.RotatingFileHandler(
    'logs/strategy.log', 
    maxBytes=10*1024*1024,  # 10MB
    backupCount=5  # Keep 5 backup files
)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# Log test messages
logging.info("This is a test message that should appear in both console and strategy.log")
logging.warning("This is a warning message")

# Try importing and initializing the strategy
try:
    # Add the current directory to the Python path
    current_dir = os.path.dirname(os.path.abspath(__file__))
    if current_dir not in sys.path:
        sys.path.insert(0, current_dir)
        
    from src.strategy import OpenInterestStrategy
    strategy = OpenInterestStrategy()
    logging.info("Successfully imported and initialized strategy")
except Exception as e:
    import traceback
    logging.error(f"Error initializing strategy: {e}")
    logging.error(traceback.format_exc())

print("Test completed. Check logs/strategy.log to see if messages were logged.")
