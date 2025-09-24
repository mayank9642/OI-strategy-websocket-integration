"""
Test the updated logging configuration
"""
import os
import sys
import logging

# Configure basic logging to see what's happening
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logging.info("Starting test_logging_fix.py")

# Ensure we can import from the current directory
current_dir = os.path.dirname(os.path.abspath(__file__))
logging.info(f"Current directory: {current_dir}")
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# Check if log_setup.py exists
log_setup_path = os.path.join(current_dir, "src", "log_setup.py")
logging.info(f"Checking if log_setup.py exists at: {log_setup_path}")
logging.info(f"File exists: {os.path.exists(log_setup_path)}")

try:
    # Import the logging utility to set up logging properly
    from src.log_setup import logger
    logging.info("Successfully imported logger from src.log_setup")
except Exception as e:
    logging.error(f"Error importing logger: {e}")
    import traceback
    logging.error(traceback.format_exc())

# Try to write directly to the logs directory
try:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    logs_dir = os.path.join(base_dir, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    
    test_log_path = os.path.join(logs_dir, "test_log_fix.log")
    logging.info(f"Writing to test log at: {test_log_path}")
    
    with open(test_log_path, "w") as f:
        f.write(f"Test log entry at {os.path.abspath(__file__)}\n")
        f.write(f"Current working directory: {os.getcwd()}\n")
    
    logging.info(f"Successfully wrote to test log")
except Exception as e:
    logging.error(f"Error writing to test log: {e}")
    import traceback
    logging.error(traceback.format_exc())
