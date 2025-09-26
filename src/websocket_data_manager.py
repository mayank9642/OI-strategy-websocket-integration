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
        # Added volume_traded to track different data streams for same symbol
        self.ltp_data = pd.DataFrame(columns=["symbol", "ltp", "timestamp", "volume_traded", "stream_id"])
        self.ltp_data.set_index("symbol", inplace=True)
        
        # Add a lock for thread safety
        self.data_lock = threading.Lock()
        
        # Dictionary to store last update time for each symbol
        self.last_update = {}
        
        # To track if we've got any data for a symbol
        self.data_received = defaultdict(bool)
        
        # Keep track of option types for strict validation
        self.symbol_option_types = {}  # Maps symbol -> "CE" or "PE"
        
        # Keep track of volume for each symbol to detect different streams
        self.symbol_volumes = {}  # Maps symbol -> last known volume
        
        # Keep track of which stream is primary for a symbol
        self.primary_stream_ids = {}  # Maps symbol -> stream_id that should be considered primary
        
        logging.info("WebsocketDataManager initialized for storing LTP data with stream tracking")
    
    def update_ltp(self, symbol, ltp, volume_traded=None):
        """
        Update the LTP data for a given symbol
        
        Args:
            symbol (str): The symbol to update
            ltp (float): The last traded price
            volume_traded (int, optional): The volume traded for the symbol, used to identify data streams
        """
        with self.data_lock:
            current_time = time.time()
            
            try:
                # Basic validation - check if the symbol and LTP are valid
                if not symbol or not ltp or ltp <= 0 or ltp > 10000:  # Upper bound for reasonable option prices
                    logging.warning(f"Invalid symbol or price: Symbol={symbol}, LTP={ltp}")
                    return
                
                # Extract option type from symbol 
                symbol_type = None
                if "CE" in symbol:
                    symbol_type = "CE"
                elif "PE" in symbol:
                    symbol_type = "PE"
                else:
                    logging.warning(f"Cannot determine option type for symbol: {symbol}")
                    return
                
                # Track option type for this symbol (first encounter only)
                if symbol not in self.symbol_option_types:
                    self.symbol_option_types[symbol] = symbol_type
                    logging.debug(f"Registered symbol {symbol} as type {symbol_type}")
                
                # Option type validation for price updates - strict checking to prevent mixups
                if symbol in self.symbol_option_types:
                    expected_type = self.symbol_option_types[symbol]
                    
                    # Verify that the symbol still contains the expected option type marker
                    if expected_type == "CE" and "CE" not in symbol:
                        logging.warning(f"Option type mismatch: Symbol {symbol} was previously registered as CE")
                        return
                    elif expected_type == "PE" and "PE" not in symbol:
                        logging.warning(f"Option type mismatch: Symbol {symbol} was previously registered as PE")
                        return
                
                # Extra validation - symbol should end with correct option type
                if symbol_type == "CE" and not symbol.endswith("CE"):
                    logging.warning(f"CE symbol {symbol} doesn't end with 'CE' suffix, skipping update")
                    return
                elif symbol_type == "PE" and not symbol.endswith("PE"):
                    logging.warning(f"PE symbol {symbol} doesn't end with 'PE' suffix, skipping update")
                    return
                
                # Generate a stream identifier based on volume data if available
                stream_id = f"{symbol}_{volume_traded}" if volume_traded else symbol
                
                # Multiple data streams detection for the same symbol
                if volume_traded and symbol in self.symbol_volumes:
                    previous_volume = self.symbol_volumes[symbol]
                    
                    # If the volume is significantly different, we might be getting data from different streams
                    if abs(previous_volume - volume_traded) > 1000000:  # Significant difference in volume
                        logging.warning(f"Detected different data stream for {symbol}: Previous vol={previous_volume}, Current vol={volume_traded}")
                        
                        # If no primary stream is set for this symbol yet, make this one the primary
                        if symbol not in self.primary_stream_ids:
                            self.primary_stream_ids[symbol] = stream_id
                            logging.info(f"Setting primary stream for {symbol}: {stream_id}")
                        # If this doesn't match the primary stream, we should be careful with the data
                        elif self.primary_stream_ids[symbol] != stream_id:
                            logging.warning(f"Non-primary data stream update for {symbol}: {stream_id} (primary: {self.primary_stream_ids[symbol]})")
                            # Only update if it's the primary stream or we explicitly want to track all streams
                            # Here we'll only track the primary stream updates
                            if self.primary_stream_ids[symbol] != stream_id:
                                logging.warning(f"Skipping update from non-primary stream: {stream_id}")
                                return
                
                # Update volume tracking for the symbol
                if volume_traded:
                    self.symbol_volumes[symbol] = volume_traded
                
                # Update the timestamp before storing data
                self.last_update[symbol] = current_time
                
                # Update the dataframe with the new LTP
                if symbol not in self.ltp_data.index:
                    # If this is a new symbol, add it to the dataframe
                    self.ltp_data.loc[symbol] = [ltp, current_time, volume_traded, stream_id]
                    logging.debug(f"Added new symbol to LTP data: {symbol} = {ltp} (vol={volume_traded})")
                else:
                    # Otherwise, update the existing row
                    self.ltp_data.at[symbol, "ltp"] = ltp
                    self.ltp_data.at[symbol, "timestamp"] = current_time
                    if volume_traded:
                        self.ltp_data.at[symbol, "volume_traded"] = volume_traded
                        self.ltp_data.at[symbol, "stream_id"] = stream_id
                
                # Mark that we've received data for this symbol
                self.data_received[symbol] = True
                
                logging.debug(f"Updated LTP for {symbol} ({symbol_type}): {ltp} (vol={volume_traded})")
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
            
            return self.ltp_data.at[symbol, "ltp"]
    
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
            ltp = tick_data.get("ltp")
            if ltp is not None:
                # Extract volume data to identify unique data streams
                volume_traded = tick_data.get("vol_traded_today", 0)
                
                # Log incoming data for debugging
                option_type = "CE" if "CE" in symbol else ("PE" if "PE" in symbol else "Unknown")
                logging.debug(f"WEBSOCKET DATA: Symbol={symbol}, Type={option_type}, LTP={ltp}, Volume={volume_traded}")
                
                # Always update the LTP data for any valid symbol with volume data
                # The update_ltp method has validation to ensure no mix-ups
                self.update_ltp(symbol, ltp, volume_traded=volume_traded)
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
    
    def cleanup_stale_data(self, max_age_seconds=30):
        """
        Remove stale data from the data manager
        
        Args:
            max_age_seconds (int): Maximum age in seconds before data is considered stale
        """
        with self.data_lock:
            current_time = time.time()
            stale_symbols = []
            
            for symbol in self.ltp_data.index:
                last_update_time = self.last_update.get(symbol, 0)
                if current_time - last_update_time > max_age_seconds:
                    stale_symbols.append(symbol)
            
            for symbol in stale_symbols:
                try:
                    self.ltp_data.drop(symbol, inplace=True)
                    if symbol in self.last_update:
                        del self.last_update[symbol]
                    if symbol in self.data_received:
                        del self.data_received[symbol]
                    if symbol in self.symbol_option_types:
                        del self.symbol_option_types[symbol]
                    if symbol in self.symbol_volumes:
                        del self.symbol_volumes[symbol]
                    if symbol in self.primary_stream_ids:
                        del self.primary_stream_ids[symbol]
                    logging.info(f"Removed stale data for symbol: {symbol}")
                except Exception as e:
                    logging.error(f"Error removing stale data for {symbol}: {e}")
    
    def reset(self):
        """
        Reset the data manager
        """
        with self.data_lock:
            self.ltp_data = pd.DataFrame(columns=["symbol", "ltp", "timestamp", "volume_traded", "stream_id"])
            self.ltp_data.set_index("symbol", inplace=True)
            self.last_update.clear()
            self.data_received.clear()
            self.symbol_option_types.clear()
            self.symbol_volumes.clear()
            self.primary_stream_ids.clear()
        
        logging.info("WebsocketDataManager reset")

# Create a global instance
data_manager = WebsocketDataManager()
