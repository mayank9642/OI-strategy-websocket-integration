"""
Run the automated options trading strategy
"""
import os
import sys
import datetime

# Ensure we can import from the current directory
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# Clear logs before starting
logs_dir = os.path.join(current_dir, "logs")
os.makedirs(logs_dir, exist_ok=True)
strategy_log = os.path.join(logs_dir, "strategy.log")
with open(strategy_log, 'w') as f:
    f.write(f"Log file cleared on {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

# Import the logging utility to set up logging properly
from src.log_setup import logger, setup_logging
# Re-initialize logging with clear_logs=True to ensure fresh logs
logger = setup_logging(clear_logs=True)
logger.info("="*80)
logger.info("STARTING STRATEGY EXECUTION")
logger.info("="*80)

# Import the websocket data manager
from src.websocket_data_manager import data_manager
logger.info("WebSocket data manager imported for consistent LTP data handling")

# Print Python path for debugging
logger.info(f"Python path includes: {sys.path}")

def monkey_patch_option_symbol_conversion():
    """Apply symbol conversion to all relevant functions"""
    try:
        # Import the symbol formatter
        from src.symbol_formatter import convert_option_symbol_format
        import src.nse_data_new
        import pandas as pd
        
        # Save original function
        original_get_option_chain = src.nse_data_new.get_nifty_option_chain
        
        # Create patched version that fixes symbols
        def patched_get_option_chain(*args, **kwargs):
            result = original_get_option_chain(*args, **kwargs)
            
            if isinstance(result, pd.DataFrame) and 'symbol' in result.columns:
                # Log original symbols first
                if not result.empty:
                    logger.info("Original option symbols:")
                    for i, symbol in enumerate(result['symbol'].iloc[:5]):
                        logger.info(f"  {i+1}. {symbol}")
                
                # Apply the conversion to all symbols
                logger.info("Converting option symbols to Fyers API format")
                result['symbol'] = result['symbol'].apply(convert_option_symbol_format)
                
                # Log the converted symbols
                if not result.empty:
                    logger.info("Converted option symbols:")
                    for i, symbol in enumerate(result['symbol'].iloc[:5]):
                        logger.info(f"  {i+1}. {symbol}")
            
            return result
            
        # Apply the patch
        src.nse_data_new.get_nifty_option_chain = patched_get_option_chain
        logger.info("Option symbol format conversion applied")
        
        return True
    except Exception as e:
        logger.error(f"Failed to apply option symbol conversion: {e}")
        return False

def apply_websocket_patch():
    """Apply the improved websocket implementation"""
    try:
        # Import the improved websocket module and monkey patch
        from src.improved_websocket import enhanced_start_market_data_websocket
        import src.fyers_api_utils
        
        # Save the original function
        original_websocket_fn = src.fyers_api_utils.start_market_data_websocket
        
        # Replace with improved version
        src.fyers_api_utils.start_market_data_websocket = enhanced_start_market_data_websocket
        logger.info("Replaced standard websocket with improved implementation")
        
        return True
    except Exception as e:
        logger.error(f"Failed to apply websocket patch: {e}")
        return False

def run_strategy():
    """Run the trading strategy with all fixes applied"""
    logger.info("="*80)
    logger.info("RUNNING AUTOMATED OPTIONS TRADING STRATEGY WITH FIXES")
    logger.info("="*80)
    # Apply necessary patches
    if not monkey_patch_option_symbol_conversion():
        return False
        
    if not apply_websocket_patch():
        return False
    
    try:
        # Import the strategy
        from src.strategy import OpenInterestStrategy
        
        # Create strategy instance
        strategy = OpenInterestStrategy()
        
        # Initialize for trading day
        logger.info("Initializing strategy for trading day...")
        init_success = strategy.initialize_day()
        if not init_success:
            logger.error("Failed to initialize strategy - check logs for details")
            return False
        # Check if market is open, if not wait for it to open
        ist_now = strategy.get_ist_datetime()
        current_time = ist_now.time()
        market_open_time = datetime.time(9, 15)
        analysis_time = datetime.time(9, 20)

        if current_time < analysis_time:
            logger.info("Waiting for 9:20 before running OI analysis and strategy...")
            result = strategy.wait_for_market_open()
        else:
            # Run the strategy with force analysis to take a trade
            logger.info("It's 9:20 or later. Running strategy with force analysis enabled to take a trade...")
            result = strategy.run_strategy(force_analysis=True)
        
        # Log final status
        logger.info("Strategy execution completed")
        return True
        
    except Exception as e:
        import traceback
        logger.error(f"Error running strategy: {e}")
        logger.error(traceback.format_exc())
        return False

if __name__ == "__main__":
    run_strategy()
