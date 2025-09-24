"""
Enhanced websocket data manager for the OI Strategy

This module provides a solution for the LTP mixup problem by storing
websocket data in a dataframe and using that for monitoring breakouts
"""
import pandas as pd
import logging
import time
import threading
import datetime
import traceback
from collections import defaultdict

class WebsocketDataManager:
    """
    A class to manage and store websocket data to prevent LTP mixups
    """
    
    def __init__(self):
        """Initialize the data manager"""
        # DataFrame to store LTP data for all symbols
        self.ltp_data = pd.DataFrame(columns=['symbol', 'ltp', 'timestamp'])
        self.ltp_data.set_index('symbol', inplace=True)
        
        # Add a lock for thread safety
        self.data_lock = threading.Lock()
        
        # Dictionary to store last update time for each symbol
        self.last_update = {}
        
        # To track if we've got any data for a symbol
        self.data_received = defaultdict(bool)
        
        logging.info("WebsocketDataManager initialized for storing LTP data")
    
    def update_ltp(self, symbol, ltp):
        """
        Update the LTP data for a given symbol
        
        Args:
            symbol (str): The symbol to update
            ltp (float): The last traded price
        """
        with self.data_lock:
            current_time = time.time()
            self.last_update[symbol] = current_time
            
            try:
                # Update the dataframe with the new LTP
                if symbol not in self.ltp_data.index:
                    # If this is a new symbol, add it to the dataframe
                    self.ltp_data.loc[symbol] = [ltp, current_time]
                else:
                    # Otherwise, update the existing row
                    self.ltp_data.at[symbol, 'ltp'] = ltp
                    self.ltp_data.at[symbol, 'timestamp'] = current_time
                
                # Mark that we've received data for this symbol
                self.data_received[symbol] = True
                
                logging.debug(f"Updated LTP for {symbol}: {ltp}")
            except Exception as e:
                logging.error(f"Error updating LTP data for {symbol}: {e}")
                logging.debug(traceback.format_exc())
    
    def get_ltp(self, symbol):
        """
        Get the latest LTP for a symbol
        
        Args:
            symbol (str): The symbol to get LTP for
            
        Returns:
            float: The last traded price for the symbol or None if not available
        """
        with self.data_lock:
            if symbol not in self.ltp_data.index:
                return None
            
            return self.ltp_data.at[symbol, 'ltp']
    
    def has_data_for_symbol(self, symbol):
        """
        Check if we have any data for a symbol
        
        Args:
            symbol (str): The symbol to check
            
        Returns:
            bool: True if we have data for this symbol, False otherwise
        """
        return self.data_received.get(symbol, False)
    
    def websocket_callback_handler(self, symbol, key, ticks, tick_data):
        """
        Callback handler for the websocket data
        
        Args:
            symbol (str): The symbol from the websocket
            key (str): The data key type
            ticks (dict): The tick data
            tick_data (dict): Additional tick data
        """
        try:
            # Extract the LTP from the tick data
            ltp = tick_data.get('ltp')
            if ltp is not None:
                self.update_ltp(symbol, ltp)
        except Exception as e:
            logging.error(f"Error in websocket callback handler: {e}")
            logging.debug(traceback.format_exc())
    
    def get_last_update_time(self, symbol):
        """
        Get the last time a symbol was updated
        
        Args:
            symbol (str): The symbol to check
            
        Returns:
            float: The timestamp of the last update or 0 if never updated
        """
        return self.last_update.get(symbol, 0)
    
    def get_age_seconds(self, symbol):
        """
        Get the age of the data for a symbol in seconds
        
        Args:
            symbol (str): The symbol to check
            
        Returns:
            float: The age in seconds or None if no data available
        """
        last_update = self.get_last_update_time(symbol)
        if last_update == 0:
            return None
        
        return time.time() - last_update
    
    def data_health_check(self):
        """
        Check if we're receiving fresh data for all symbols
        
        Returns:
            dict: A dictionary with the health status of each symbol
        """
        health = {}
        current_time = time.time()
        
        with self.data_lock:
            for symbol in self.ltp_data.index:
                last_update = self.get_last_update_time(symbol)
                age = current_time - last_update if last_update > 0 else None
                
                if age is None:
                    health[symbol] = "No data received"
                elif age > 10:
                    health[symbol] = f"Data stale ({age:.1f} seconds old)"
                else:
                    health[symbol] = "Healthy"
        
        return health
    
    def reset(self):
        """
        Reset the data manager
        """
        with self.data_lock:
            self.ltp_data = pd.DataFrame(columns=['symbol', 'ltp', 'timestamp'])
            self.ltp_data.set_index('symbol', inplace=True)
            self.last_update.clear()
            self.data_received.clear()
        
        logging.info("WebsocketDataManager reset")

# Create a global instance
data_manager = WebsocketDataManager()
