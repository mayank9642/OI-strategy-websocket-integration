"""
Test the WebSocket Data Manager implementation
"""
from src.websocket_data_manager import data_manager
import logging
import time

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()

# Test updating and retrieving LTP data
data_manager.update_ltp('NSE:NIFTY25SEP25400CE', 75.5)
logger.info(f"LTP for NSE:NIFTY25SEP25400CE: {data_manager.get_ltp('NSE:NIFTY25SEP25400CE')}")

# Test updating multiple symbols
data_manager.update_ltp('NSE:NIFTY25SEP25400PE', 82.3)
logger.info(f"LTP for NSE:NIFTY25SEP25400PE: {data_manager.get_ltp('NSE:NIFTY25SEP25400PE')}")

# Test data health check
logger.info("Data health check:")
health = data_manager.data_health_check()
for symbol, status in health.items():
    logger.info(f"  {symbol}: {status}")

# Test checking if we have data for a symbol
logger.info(f"Has data for NSE:NIFTY25SEP25400CE: {data_manager.has_data_for_symbol('NSE:NIFTY25SEP25400CE')}")
logger.info(f"Has data for NSE:NONEXISTENT: {data_manager.has_data_for_symbol('NSE:NONEXISTENT')}")

# Test data age
time.sleep(2)
logger.info(f"Data age for NSE:NIFTY25SEP25400CE: {data_manager.get_age_seconds('NSE:NIFTY25SEP25400CE')} seconds")

# Test reset
data_manager.reset()
logger.info(f"After reset - LTP for NSE:NIFTY25SEP25400CE: {data_manager.get_ltp('NSE:NIFTY25SEP25400CE')}")
logger.info(f"After reset - Has data for NSE:NIFTY25SEP25400CE: {data_manager.has_data_for_symbol('NSE:NIFTY25SEP25400CE')}")

logger.info("WebSocket Data Manager test completed successfully")
