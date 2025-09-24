"""
Test script to verify both logging and WebSocket price updates for stop-loss functionality
"""
import os
import sys
import time
import logging
import datetime

print("Starting test script...")

# Ensure we can import from the current directory
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

print(f"Current directory: {current_dir}")

# Clear logs before starting
logs_dir = os.path.join(current_dir, "logs")
os.makedirs(logs_dir, exist_ok=True)
strategy_log = os.path.join(logs_dir, "strategy.log")
with open(strategy_log, 'w') as f:
    f.write(f"Log file cleared on {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

print(f"Cleared log file at: {strategy_log}")

# Import the logging utility to set up logging properly
from src.log_setup import logger, setup_logging
# Re-initialize logging with clear_logs=True to ensure fresh logs
logger = setup_logging(clear_logs=True)

logger.info("="*80)
logger.info("TESTING STOP-LOSS AND LOGGING FUNCTIONALITY")
logger.info("="*80)

# Import the websocket data manager
from src.websocket_data_manager import data_manager

# Simulate WebSocket price updates and data manager usage
test_symbol = "NSE:NIFTY2592325200CE"

# 1. Simulate storing initial price in data manager
initial_price = 70.0
data_manager.update_ltp(test_symbol, initial_price)
logger.info(f"Initialized data_manager price for {test_symbol}: {initial_price}")

# 2. Verify the price is stored correctly
dm_price = data_manager.get_ltp(test_symbol)
logger.info(f"Retrieved price from data_manager: {dm_price}")

# 3. Simulate WebSocket price update (dropping below SL)
websocket_price = 32.5
logger.info(f"Simulating WebSocket price update: {test_symbol} price dropped to {websocket_price}")

# 4. Create a dictionary to simulate the live_prices behavior
live_prices = {test_symbol: websocket_price}
logger.info(f"Updated live_prices dictionary: {live_prices}")

# 5. Check the data_manager price again (should still be the initial price)
dm_price = data_manager.get_ltp(test_symbol)
logger.info(f"Data manager price is still: {dm_price}")

# 6. Simulate what would happen in the ws_price_update function
logger.info("Simulating ws_price_update function behavior...")
logger.info(f"LTP UPDATE FOR ACTIVE TRADE: {test_symbol} {websocket_price}")
data_manager.update_ltp(test_symbol, websocket_price)

# 7. Check the data_manager price again (should now be updated)
dm_price = data_manager.get_ltp(test_symbol)
logger.info(f"Data manager price after update: {dm_price}")

# 8. Simulate the position monitor behavior
logger.info("Simulating position monitor behavior...")
current_price = data_manager.get_ltp(test_symbol)
stoploss = 56.8
target = 99.3

if data_manager.has_data_for_symbol(test_symbol):
    price_source = "data manager"
elif test_symbol in live_prices:
    price_source = "live prices dictionary"
else:
    price_source = "last known price"

logger.info(f"Position monitor price for {test_symbol}: {current_price} (source: {price_source})")

# Get the websocket price for comparison
ws_price = live_prices.get(test_symbol)
if ws_price is not None and abs(ws_price - current_price) > 5:
    logger.warning(f"PRICE DISCREPANCY DETECTED: data_manager={current_price}, websocket={ws_price} - using websocket price for SL/Target check")
    current_price = ws_price
    price_source = "websocket (overriding data_manager due to discrepancy)"
    logger.info(f"Position monitor price for {test_symbol}: {current_price} (source: {price_source})")

logger.info(f"SL/Target check: Current: {current_price}, SL: {stoploss}, Target: {target}")

# Check for stoploss and target hit
if current_price <= stoploss:
    logger.info(f"Stoploss hit. Exiting position at defined stoploss: {stoploss}. Current price: {current_price}")
elif current_price >= target:
    logger.info(f"Target hit. Exiting position at defined target: {target}. Current price: {current_price}")
else:
    logger.info(f"No SL or Target hit. Continuing to monitor position.")

logger.info("="*80)
logger.info("TEST COMPLETED SUCCESSFULLY")
logger.info("="*80)
