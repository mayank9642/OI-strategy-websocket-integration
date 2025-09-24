"""
Test script to verify the logging functionality
"""
import os
import sys

# Add the project directory to path
current_dir = os.path.dirname(os.path.abspath(__file__))
print(f"Current directory: {current_dir}")
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)
print(f"Python path: {sys.path}")

# Check logs directory
logs_dir = os.path.join(current_dir, "logs")
os.makedirs(logs_dir, exist_ok=True)
print(f"Logs directory exists: {os.path.exists(logs_dir)}")
print(f"Logs directory path: {logs_dir}")

try:
    # Import the logging utility
    from src.log_setup import logger, setup_logging
    print("Successfully imported logging utility")
except Exception as e:
    print(f"Error importing logging utility: {e}")

try:
    # Force a fresh setup with cleared logs
    logger = setup_logging(clear_logs=True)
    print("Successfully set up logging")

    # Log some test messages
    logger.debug("This is a DEBUG message")
    logger.info("This is an INFO message")
    logger.warning("This is a WARNING message")
    logger.error("This is an ERROR message")
    
    print("Logging calls completed")
except Exception as e:
    print(f"Error during logging: {e}")

# Manually write to log file as a test
try:
    with open(os.path.join(logs_dir, "strategy.log"), "a") as f:
        f.write("Direct write test to strategy.log\n")
    print("Direct write to log file completed")
except Exception as e:
    print(f"Error writing directly to log file: {e}")

print("Test complete. Check the logs/strategy.log file.")
