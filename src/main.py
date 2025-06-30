import schedule
import time
import logging
import datetime
import os
import sys

# Add the parent directory to the system path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Use src namespace for imports
from src.strategy import OpenInterestStrategy
from src.config import load_config
from src.token_helper import ensure_valid_token
from src.auth import generate_access_token

# Ensure logs directory exists
os.makedirs('logs', exist_ok=True)

# Setup logging
logging.basicConfig(
    filename='logs/strategy.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def job(strategy):
    """Run the strategy job at specified intervals"""
    try:
        strategy.run_strategy()
    except Exception as e:
        logging.error(f"Error in scheduled job: {str(e)}")

def main():
    """Main function to start the strategy"""
    try:
        logging.info("Starting Open Interest Option Buying Strategy...")
        
        # Ensure we have a valid access token before starting
        logging.info("Checking authentication status...")
        access_token = ensure_valid_token()
        
        if not access_token:
            logging.warning("No valid access token found. Attempting to generate one...")
            access_token = generate_access_token()
            
            if not access_token:
                logging.error("Failed to generate access token. Please run auth.py separately.")
                raise Exception("Authentication failed")
                
        # Create strategy instance
        strategy_instance = OpenInterestStrategy()
        # Initialize strategy for the day
        if not strategy_instance.initialize_day():
            logging.error("Failed to initialize strategy. Exiting.")
            raise Exception("Strategy initialization failed")
        logging.info("Strategy initialized successfully.")

        # Run the strategy once immediately
        strategy_instance.run_strategy()
        
        return {"success": True, "message": "Strategy executed successfully"}
        
    except Exception as e:
        logging.error(f"Error in main: {str(e)}")
        return {"success": False, "error": str(e)}

def run_immediate():
    """Run the strategy immediately once, without scheduling"""
    try:
        logging.info("Starting Open Interest Option Buying Strategy (immediate mode)...")
        
        # Ensure we have a valid access token before starting
        logging.info("Checking authentication status...")
        access_token = ensure_valid_token()
        
        if not access_token:
            logging.warning("No valid access token found. Attempting to generate one...")
            access_token = generate_access_token()
            
            if not access_token:
                logging.error("Failed to generate access token. Please run auth.py separately.")
                raise Exception("Authentication failed")
        
        # Create strategy instance
        strategy_instance = OpenInterestStrategy()
        # Initialize strategy for the day
        if not strategy_instance.initialize_day():
            logging.error("Failed to initialize strategy. Exiting.")
            raise Exception("Strategy initialization failed")
        logging.info("Strategy initialized successfully.")

        # Run the strategy once immediately
        result = strategy_instance.run_strategy()
        logging.info("Strategy execution completed.")
        return result
    except Exception as e:
        logging.error(f"Error running immediate strategy: {str(e)}")
        return {"success": False, "error": str(e)}

def run_scheduled():
    """Run the strategy with normal scheduling"""
    try:
        logging.info("Starting Open Interest Option Buying Strategy (scheduled mode)...")
        
        # Ensure we have a valid access token before starting
        logging.info("Checking authentication status...")
        access_token = ensure_valid_token()
        
        if not access_token:
            logging.warning("No valid access token found. Attempting to generate one...")
            access_token = generate_access_token()
            
            if not access_token:
                logging.error("Failed to generate access token. Please run auth.py separately.")
                raise Exception("Authentication failed")
        
        logging.info("Authentication successful. Creating strategy instance...")
        
        # Create strategy instance
        strategy_instance = OpenInterestStrategy()
        # Initialize strategy for the day
        if not strategy_instance.initialize_day():
            logging.error("Failed to initialize strategy. Exiting.")
            raise Exception("Strategy initialization failed")
        logging.info("Strategy initialized successfully.")

        # Schedule jobs
        # Correct way to schedule for weekdays at 9:15 AM
        for day in ['monday', 'tuesday', 'wednesday', 'thursday', 'friday']:
            schedule.every().__getattribute__(day).at("09:15").do(strategy_instance.initialize_day)
        
        # Run the job every minute during market hours
        schedule.every(1).minutes.do(lambda: job(strategy_instance))
        
        logging.info("Strategy scheduled. Running main loop...")
        
        # Main loop
        while True:
            schedule.run_pending()
            time.sleep(1)
            
    except KeyboardInterrupt:
        logging.info("Strategy execution stopped by user.")
        if 'strategy_instance' in locals():
            strategy_instance.cleanup()
        return {"success": False, "error": "User interrupted"}
    except Exception as e:
        logging.critical(f"Unhandled exception: {str(e)}")
        if 'strategy_instance' in locals():
            strategy_instance.cleanup()
        return {"success": False, "error": str(e)}

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Open Interest Option Trading Strategy")
    parser.add_argument('--immediate', '-i', action='store_true', help='Run strategy immediately (skip 9:20 AM check)')
    args = parser.parse_args()
    
    if args.immediate:
        run_immediate()
    else:
        run_scheduled()