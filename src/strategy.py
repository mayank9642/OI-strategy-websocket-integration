import pandas as pd
import datetime
import time
import logging
import schedule
import json
import os
import pytz
import threading
import queue
import re
from datetime import date
from src.fyers_api_utils import (
    get_fyers_client, place_market_order, modify_order, exit_position,
    place_limit_order, place_sl_order, place_sl_limit_order, 
    get_order_status, get_historical_data, start_market_data_websocket, get_nifty_spot_price
)
from src.nse_data_new import get_nifty_option_chain
from src.config import load_config
from src.token_helper import ensure_valid_token

# Ensure logs directory exists
os.makedirs('logs', exist_ok=True)

# Setup logging
logging.basicConfig(
    filename='logs/strategy.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class OpenInterestStrategy:
    def __init__(self):
        self.config = load_config()
        self.fyers = get_fyers_client()
        self.active_trade = None
        self.highest_put_oi_strike = None
        self.highest_call_oi_strike = None
        self.put_premium_at_9_20 = None
        self.call_premium_at_9_20 = None
        self.entry_time = None
        self.order_id = None
        self.stop_loss_order_id = None
        self.target_order_id = None
        self.data_socket = None
        self.trade_history = []
        self.trade_taken_today = False  # Flag to track if a trade has been taken today
        # Ensure breakout levels are always defined
        self.put_breakout_level = None
        self.call_breakout_level = None
        
        # Paper trading mode (simulate trades without placing actual orders)
        self.paper_trading = self.config.get('strategy', {}).get('paper_trading', True)
        # Minimum premium threshold to avoid triggering trades on tiny values
        self.min_premium_threshold = self.config.get('strategy', {}).get('min_premium_threshold', 50.0)
        # Maximum allowed deviation from ATM in absolute points for strike selection
        self.max_strike_distance = self.config.get('strategy', {}).get('max_strike_distance', 500)
        
        # Load existing trade history if available
        try:
            if os.path.exists('logs/trade_history.csv'):
                self.trade_history = pd.read_csv('logs/trade_history.csv').to_dict('records')
                logging.info(f"Loaded {len(self.trade_history)} historical trades from CSV")
                
                # Check for today's Excel file
                today = date.today().strftime("%Y%m%d")
                excel_path = f'logs/trade_history_{today}.xlsx'
                if os.path.exists(excel_path) and os.path.getsize(excel_path) > 0:
                    logging.info(f"Excel trade history file {excel_path} exists")
        except Exception as e:
            logging.warning(f"Could not load trade history: {str(e)}")
        
    def reset_state(self):
        """Reset all state variables for a clean start"""
        # OI analysis results
        self.highest_put_oi_strike = None
        self.highest_call_oi_strike = None
        self.put_premium_at_9_20 = None
        self.call_premium_at_9_20 = None
        self.highest_put_oi_symbol = None
        self.highest_call_oi_symbol = None
        self.put_breakout_level = None
        self.call_breakout_level = None
        
        # Initialize trade state variables
        self.active_trade = None
        self.entry_time = None
        self.order_id = None
        self.stop_loss_order_id = None
        self.target_order_id = None
        self.trade_taken_today = False
        
        # Storage for live price updates
        self.live_prices = {}
        
        # Close existing WebSocket connection if any
        if hasattr(self, 'data_socket') and self.data_socket:
            try:
                self.data_socket.close()
                logging.info("Closed existing WebSocket connection")
            except Exception as e:
                logging.warning(f"Error closing WebSocket: {str(e)}")
        self.data_socket = None

    def initialize_day(self):
        """Reset variables for a new trading day"""
        # Check for valid token before starting the trading day
        try:
            # Clear the logs for a fresh start
            self.clear_logs()
            
            # Reset all state variables for a clean start
            self.reset_state()
            
            access_token = ensure_valid_token()
            if access_token:
                self.fyers = get_fyers_client(check_token=False)  # Token already checked
                logging.info("Authentication verified for today's trading session")
            else:
                logging.error("Failed to obtain valid access token for today's session")
                return False
                
            # Close any existing websocket connection
            if self.data_socket:
                try:
                    self.data_socket.close_connection()
                    logging.info("Closed previous websocket connection")
                except Exception as e:
                    logging.error(f"Error closing previous websocket: {str(e)}")
                    
            self.data_socket = None
            
            # Reset trading variables
            self.reset_state()
            
            logging.info("Strategy initialized for a new trading day")
            return True
            
        except Exception as e:
            logging.error(f"Error initializing day: {str(e)}")
            return False

    def identify_high_oi_strikes(self):
        """Identify strikes with highest open interest at 9:20 AM"""
        try:
            # Reset breakout levels for a fresh start
            self.put_breakout_level = None
            self.call_breakout_level = None
            
            # Check if markets are open today
            today = datetime.datetime.now()
            if today.weekday() > 4:  # Saturday or Sunday
                logging.warning("Markets are closed today (weekend). Skipping analysis.")
                return False
            
            # Get the current Nifty spot price
            from src.fyers_api_utils import get_nifty_spot_price
            spot_price = get_nifty_spot_price()
            logging.info(f"Current Nifty spot price: {spot_price}")
            
            # Find suitable strikes starting with the current expiry
            logging.info("Starting OI analysis to find suitable strikes...")
            result = self._find_suitable_strikes(0, spot_price)
            
            # Verify that breakout levels are properly set
            if result is False or self.put_breakout_level is None or self.call_breakout_level is None:
                logging.error("OI analysis failed or breakout levels not set. Aborting strategy for today.")
                # Clear any partially set data to avoid confusion
                self.highest_put_oi_strike = None
                self.highest_call_oi_strike = None
                self.put_premium_at_9_20 = None
                self.call_premium_at_9_20 = None
                self.highest_put_oi_symbol = None
                self.highest_call_oi_symbol = None
                self.put_breakout_level = None
                self.call_breakout_level = None
                return False
            
            # Final validation of the selected strikes and their premiums
            logging.info("OI analysis completed successfully")
            logging.info(f"Selected strikes - PUT: {self.highest_put_oi_strike} (Premium: {self.put_premium_at_9_20}, Breakout: {self.put_breakout_level})")
            logging.info(f"Selected strikes - CALL: {self.highest_call_oi_strike} (Premium: {self.call_premium_at_9_20}, Breakout: {self.call_breakout_level})")
            return result
            
        except Exception as e:
            logging.error(f"Error identifying high OI strikes: {str(e)}")
            import traceback
            logging.error(f"Traceback: {traceback.format_exc()}")
            
            # Clear any partially set data
            self.highest_put_oi_strike = None
            self.highest_call_oi_strike = None
            self.put_premium_at_9_20 = None
            self.call_premium_at_9_20 = None
            self.highest_put_oi_symbol = None
            self.highest_call_oi_symbol = None
            self.put_breakout_level = None
            self.call_breakout_level = None
            return False

    def _find_suitable_strikes(self, expiry_index=0, spot_price=None):
        """Find suitable strikes for the given expiry index"""
        try:
            logging.info(f"Fetching option chain data for expiry index {expiry_index}...")
            option_chain = get_nifty_option_chain(expiry_index)
            
            if option_chain is None or option_chain.empty:
                logging.error(f"Failed to fetch option chain for expiry index {expiry_index}")
                if expiry_index < 2:  # Try next expiry if available
                    logging.info(f"Trying next expiry (index {expiry_index + 1})...")
                    return self._find_suitable_strikes(expiry_index + 1, spot_price)
                return False
                
            if spot_price is None:
                if 'strike_price' in option_chain.columns:
                    spot_price = option_chain['strike_price'].median()
                    logging.info(f"Using median strike_price as spot: {spot_price}")
                elif 'ltp' in option_chain.columns:
                    spot_price = option_chain['ltp'].median()
                    logging.info(f"Using median ltp as spot: {spot_price}")
                else:
                    from src.fyers_api_utils import get_nifty_spot_price
                    spot_price = get_nifty_spot_price()
                    logging.info(f"Fetched spot price from API: {spot_price}")
            
            # Identify ATM strike (closest to spot price)
            atm_strike = round(spot_price / 100) * 100
            
            # Filter by distance from ATM
            max_distance = self.max_strike_distance  # Max distance from ATM
            logging.info(f"Filtering options within {max_distance} points of ATM strike {atm_strike}")
            
            try:
                filtered_chain = option_chain[(option_chain['strikePrice'] >= atm_strike - max_distance) & 
                                             (option_chain['strikePrice'] <= atm_strike + max_distance)]
                
                if filtered_chain.empty:
                    logging.warning(f"No options found within {max_distance} points of ATM. Using full chain.")
                    filtered_chain = option_chain
            except Exception as e:
                logging.error(f"Error filtering option chain: {str(e)}")
                logging.info("Using full option chain without filtering")
                filtered_chain = option_chain
            
            # Find strike with highest put OI
            put_chain = filtered_chain[filtered_chain['option_type'] == 'PE']
            if not put_chain.empty:
                put_oi_sorted = put_chain.sort_values('openInterest', ascending=False)
                logging.info(f"Top 3 PUT OI strikes: {put_oi_sorted[['strikePrice', 'openInterest', 'lastPrice']].head(3).to_dict('records')}")
                
                self.highest_put_oi_strike = int(put_oi_sorted['strikePrice'].iloc[0])
                put_premium_row = put_oi_sorted[put_oi_sorted['strikePrice'] == self.highest_put_oi_strike]
                
                if put_premium_row.empty:
                    logging.error(f"No row found for highest PUT OI strike {self.highest_put_oi_strike}. DataFrame: {put_oi_sorted}")
                    if expiry_index < 2:
                        return self._find_suitable_strikes(expiry_index + 1, spot_price)
                    return False
                    
                if 'lastPrice' not in put_premium_row.columns:
                    logging.error(f"'lastPrice' column missing for highest PUT OI strike {self.highest_put_oi_strike}. Columns: {put_premium_row.columns.tolist()}")
                    logging.error(f"Row data: {put_premium_row}")
                    if expiry_index < 2:
                        return self._find_suitable_strikes(expiry_index + 1, spot_price)
                    return False
                    
                self.put_premium_at_9_20 = float(put_premium_row['lastPrice'].iloc[0])
                self.highest_put_oi_symbol = put_premium_row['symbol'].iloc[0]
                logging.info(f"Highest PUT OI Strike: {self.highest_put_oi_strike}, Premium: {self.put_premium_at_9_20}, Symbol: {self.highest_put_oi_symbol}")
            else:
                logging.error("No PUT options found in filtered chain")
                if expiry_index < 2:
                    return self._find_suitable_strikes(expiry_index + 1, spot_price)
                return False
                
            # Find strike with highest call OI
            call_chain = filtered_chain[filtered_chain['option_type'] == 'CE']
            if not call_chain.empty:
                call_oi_sorted = call_chain.sort_values('openInterest', ascending=False)
                logging.info(f"Top 3 CALL OI strikes: {call_oi_sorted[['strikePrice', 'openInterest', 'lastPrice']].head(3).to_dict('records')}")
                
                self.highest_call_oi_strike = int(call_oi_sorted['strikePrice'].iloc[0])
                call_premium_row = call_oi_sorted[call_oi_sorted['strikePrice'] == self.highest_call_oi_strike]
                
                if call_premium_row.empty:
                    logging.error(f"No row found for highest CALL OI strike {self.highest_call_oi_strike}. DataFrame: {call_oi_sorted}")
                    if expiry_index < 2:
                        return self._find_suitable_strikes(expiry_index + 1, spot_price)
                    return False
                    
                if 'lastPrice' not in call_premium_row.columns:
                    logging.error(f"'lastPrice' column missing for highest CALL OI strike {self.highest_call_oi_strike}. Columns: {call_premium_row.columns.tolist()}")
                    logging.error(f"Row data: {call_premium_row}")
                    if expiry_index < 2:
                        return self._find_suitable_strikes(expiry_index + 1, spot_price)
                    return False
                    
                self.call_premium_at_9_20 = float(call_premium_row['lastPrice'].iloc[0])
                self.highest_call_oi_symbol = call_premium_row['symbol'].iloc[0]
                logging.info(f"Highest CALL OI Strike: {self.highest_call_oi_strike}, Premium: {self.call_premium_at_9_20}, Symbol: {self.highest_call_oi_symbol}")
                logging.info(f"Highest CE OI details: {{'strikePrice': {self.highest_call_oi_strike}, 'symbol': '{self.highest_call_oi_symbol}', 'lastPrice': {self.call_premium_at_9_20}, 'openInterest': {int(call_oi_sorted['openInterest'].iloc[0])}}}")
            else:
                logging.error("No CALL options found in filtered chain")
                if expiry_index < 2:
                    return self._find_suitable_strikes(expiry_index + 1, spot_price)
                return False
                
            # Check if premiums are too low (filter out options with very low premiums)
            premium_threshold_met = True
            
            if (self.put_premium_at_9_20 < self.min_premium_threshold or 
                self.call_premium_at_9_20 < self.min_premium_threshold):
                logging.info(f"First highest OI strikes have premiums below threshold ({self.min_premium_threshold}), checking 2nd highest OI strikes...")
                premium_threshold_met = False
                self._find_second_highest_oi_strikes(option_chain, spot_price)
            
            # If premiums are still below threshold after checking 2nd highest OI, try next expiry
            if (self.put_premium_at_9_20 < self.min_premium_threshold or 
                self.call_premium_at_9_20 < self.min_premium_threshold):
                if expiry_index < 2:  # Limit to next 2 expiries
                    logging.info(f"Both 1st and 2nd highest OI strikes have premiums below threshold ({self.min_premium_threshold}), checking next expiry...")
                    next_expiry_index = expiry_index + 1
                    # Return the result of the next expiry call directly, do not continue in parent
                    return self._find_suitable_strikes(next_expiry_index, spot_price)
                else:
                    logging.warning(f"Reached maximum expiry index {expiry_index}. Using best available premiums despite being below threshold.")
                    premium_threshold_met = True  # Force continue with what we have
            
            # Only set breakout levels if valid premiums are found and not returning early
            if premium_threshold_met or expiry_index >= 2:
                logging.info(f"Final PUT selection - Strike: {self.highest_put_oi_strike}, Premium: {self.put_premium_at_9_20}")
                logging.info(f"Strike distance from spot: {abs(self.highest_put_oi_strike - spot_price)} points")
                logging.info(f"Final CALL selection - Strike: {self.highest_call_oi_strike}, Premium: {self.call_premium_at_9_20}")
                logging.info(f"Strike distance from spot: {abs(self.highest_call_oi_strike - spot_price)} points")
                
                # Calculate breakout levels (10% increase)
                self.put_breakout_level = round(self.put_premium_at_9_20 * 1.10, 1)
                self.call_breakout_level = round(self.call_premium_at_9_20 * 1.10, 1)
                logging.info(f"PUT Breakout Level: {self.put_breakout_level}")
                logging.info(f"CALL Breakout Level: {self.call_breakout_level}")
                return option_chain
                
            return option_chain  # Should not reach here as we either return from recursive call or set breakout levels
            
        except Exception as e:
            logging.error(f"Error finding suitable strikes: {str(e)}")
            import traceback
            logging.error(f"Traceback: {traceback.format_exc()}")
            if expiry_index < 2:  # Try next expiry if we have one
                return self._find_suitable_strikes(expiry_index + 1, spot_price)
            return False
            
    def _start_tick_queue_consumer(self):
        """Start a background thread to consume ticks from the WebSocket tick_queue."""
        if not self.data_socket or not hasattr(self.data_socket, 'tick_queue'):
            logging.warning("No tick_queue found on data_socket; skipping tick consumer thread.")
            return
        if hasattr(self, '_tick_consumer_thread') and self._tick_consumer_thread and self._tick_consumer_thread.is_alive():
            logging.info("Tick consumer thread already running.")
            return
        import threading
        def tick_consumer():
            logging.info("Tick queue consumer thread started.")
            ticks_received = 0
            start_time = time.time()
            while self.data_socket and hasattr(self.data_socket, 'tick_queue'):
                try:
                    tick = self.data_socket.tick_queue.get(timeout=2)
                    symbol = tick.get('symbol')
                    ltp = tick.get('ltp')
                    if symbol and ltp is not None:
                        self.live_prices[symbol] = float(ltp)
                        if self.active_trade and symbol == self.active_trade.get('symbol'):
                            self.active_trade['last_known_price'] = float(ltp)
                    ticks_received += 1
                    # Log WebSocket statistics periodically
                    elapsed = time.time() - start_time
                    if elapsed >= 60:  # Every minute
                        logging.info(f"WebSocket stats: {ticks_received} ticks in {elapsed:.1f}s ({ticks_received/elapsed:.1f} ticks/sec)")
                        ticks_received = 0
                        start_time = time.time()
                except Exception as e:
                    # Timeout or queue empty is normal; log only real errors
                    if 'Empty' not in str(type(e)):
                        logging.debug(f"Tick queue consumer error: {e}")
        self._tick_consumer_thread = threading.Thread(target=tick_consumer, name="TickQueueConsumer", daemon=True)
        self._tick_consumer_thread.start()

    def monitor_for_breakout(self):
        """Continuously monitor option premiums for breakout using websocket for real-time data"""
        try:
            # Ensure breakout levels are set
            if self.put_breakout_level is None or self.call_breakout_level is None:
                logging.error("Breakout levels are not set. OI analysis may have failed. Aborting breakout monitoring.")
                logging.error(f"PUT breakout level: {self.put_breakout_level}, CALL breakout level: {self.call_breakout_level}")
                logging.error(f"PUT premium: {self.put_premium_at_9_20}, CALL premium: {self.call_premium_at_9_20}")
                logging.error(f"PUT strike: {self.highest_put_oi_strike}, CALL strike: {self.highest_call_oi_strike}")
                return
            # Set up websocket for put and call strikes if not already established
            if not self.data_socket:
                put_symbol = self.highest_put_oi_symbol
                call_symbol = self.highest_call_oi_symbol
                nifty_symbol = "NSE:NIFTY50-INDEX"
                symbols_to_monitor = [put_symbol, call_symbol, nifty_symbol]
                logging.info(f"Starting websocket connection for breakout monitoring: {symbols_to_monitor}")
                def ws_breakout_handler(symbol, key, value, tick_data):
                    if key == 'ltp':
                        self.live_prices[symbol] = float(value)
                from src.fyers_api_utils import start_market_data_websocket
                self.data_socket = start_market_data_websocket(symbols=symbols_to_monitor, callback_handler=ws_breakout_handler)
                logging.info("WebSocket connection established for breakout monitoring")
                self._start_tick_queue_consumer()
            # Also poll for breakouts as a fallback in case websocket fails
            def monitor_loop():
                while not self.active_trade:
                    try:
                        # Try to get prices from websocket first
                        put_symbol = self.highest_put_oi_symbol
                        call_symbol = self.highest_call_oi_symbol
                        current_put_premium = None
                        current_call_premium = None
                        # Try websocket first
                        if put_symbol in self.live_prices:
                            current_put_premium = self.live_prices[put_symbol]
                        if call_symbol in self.live_prices:
                            current_call_premium = self.live_prices[call_symbol]
                        # Fallback to API if needed
                        if current_put_premium is None or current_call_premium is None:
                            option_chain = get_nifty_option_chain()
                            if current_put_premium is None:
                                current_put_premium = option_chain[(option_chain['strikePrice'] == self.highest_put_oi_strike) & 
                                                         (option_chain['option_type'] == 'PE')]['lastPrice'].values[0]
                            if current_call_premium is None:
                                current_call_premium = option_chain[(option_chain['strikePrice'] == self.highest_call_oi_strike) & 
                                                          (option_chain['option_type'] == 'CE')]['lastPrice'].values[0]
                        # Log current premiums
                        data_source_put = "WS" if put_symbol in self.live_prices else "API"
                        data_source_call = "WS" if call_symbol in self.live_prices else "API"
                        logging.info(f"Current PUT premium: {current_put_premium} [{data_source_put}], Breakout level: {self.put_breakout_level}")
                        logging.info(f"Current CALL premium: {current_call_premium} [{data_source_call}], Breakout level: {self.call_breakout_level}")
                        # Check for PUT breakout with minimum premium threshold
                        if (self.put_breakout_level is not None and current_put_premium >= self.put_breakout_level and 
                            current_put_premium >= self.min_premium_threshold):
                            self.entry_time = self.get_ist_datetime()
                            symbol = self.highest_put_oi_symbol
                            logging.info(f"PUT BREAKOUT DETECTED: {symbol} at premium {current_put_premium}")
                            self.execute_trade(symbol, "BUY", current_put_premium)
                            break
                        # Check for CALL breakout with minimum premium threshold
                        if (self.call_breakout_level is not None and current_call_premium >= self.call_breakout_level and 
                            current_call_premium >= self.min_premium_threshold):
                            self.entry_time = self.get_ist_datetime()
                            symbol = self.highest_call_oi_symbol
                            logging.info(f"CALL BREAKOUT DETECTED: {symbol} at premium {current_call_premium}")
                            self.execute_trade(symbol, "BUY", current_call_premium)
                            break
                    except Exception as e:
                        logging.error(f"Error in continuous breakout monitoring: {str(e)}")
                    time.sleep(1)  # Check every second
            # Start the monitoring loop in the main thread (blocking until trade is entered)
            monitor_loop()
        except Exception as e:
            logging.error(f"Error monitoring for breakout: {str(e)}")
            return None
    
    def execute_trade(self, symbol, side, entry_price):
        """Execute the option trade with correct lot size for Nifty options"""
        try:
            # Use correct lot size for Nifty options
            qty = 75  # Nifty lot size (update if changed by exchange)
            
            # Calculate notional value and fixed risk metrics
            notional_value = entry_price * qty
            
            # Check if premium value is too low
            if entry_price < self.min_premium_threshold:
                logging.warning(f"Trade rejected: Premium value ({entry_price}) is below threshold ({self.min_premium_threshold})")
                return None
            
            # Log trade setup info
            if self.paper_trading:
                logging.info(f"PAPER TRADING MODE - Symbol: {symbol}, Price: {entry_price}")
            else:
                logging.info(f"LIVE TRADING - Symbol: {symbol}, Price: {entry_price}")
                
            logging.info(f"Trade Size: {qty} lots, Notional Value: {notional_value}")
            
            # Place order using Fyers API (or simulate for paper trading)
            order_response = None
            if self.paper_trading:
                # Simulate a successful order with a dummy ID in paper trading mode
                order_response = {'s': 'ok', 'id': f'PAPER-{int(time.time())}'}
                logging.info(f"Paper trade simulated: {symbol} {side} {qty}")
            else:
                # Place a real order via Fyers API
                order_response = place_market_order(self.fyers, symbol, qty, side)
            
            if order_response and order_response.get('s') == 'ok':
                self.order_id = order_response.get('id')
                
                # Ensure entry time is set
                if not self.entry_time:
                    self.entry_time = self.get_ist_datetime()
                    
                # Calculate the exit time (30 min after entry)
                exit_time = self.entry_time + datetime.timedelta(minutes=30)
                
                # Load config values for stop loss and risk-reward ratio
                config = load_config()
                stoploss_pct = config.get('strategy', {}).get('stoploss_pct', 20)
                risk_reward_ratio = config.get('strategy', {}).get('risk_reward_ratio', 2)
                
                # Calculate stop loss and target prices based on config
                stoploss_factor = 1 - (stoploss_pct / 100)  # e.g., 20% SL = 0.8 of entry price
                stoploss_price = round(entry_price * stoploss_factor, 1)
                
                # Calculate target using risk_reward_ratio (e.g., RR of 2 means target gain is 2x the potential loss)
                risk_amount = entry_price - stoploss_price  # Absolute amount at risk
                target_gain = risk_amount * risk_reward_ratio  # Target gain is RR times the risk amount
                target_price = round(entry_price + target_gain, 1)
                
                self.active_trade = {
                    'symbol': symbol,
                    'quantity': qty,
                    'entry_price': entry_price,
                    'entry_time': self.entry_time,
                    'stoploss': stoploss_price,
                    'target': target_price,
                    'exit_time': exit_time,  # 30-min time limit
                    'paper_trade': self.paper_trading  # Track if this is a paper trade
                }
                
                # Set the flag to indicate a trade has been taken today
                self.trade_taken_today = True
                logging.info("Daily trade limit: Trade has been taken for today.")
                
                # Log trade details with better formatting
                logging.info(f"=== {'PAPER' if self.paper_trading else 'LIVE'} TRADE EXECUTED ===")
                logging.info(f"Symbol: {symbol}")
                logging.info(f"Entry Price: {entry_price}")
                logging.info(f"Quantity: {qty} lots")
                logging.info(f"Entry Time: {self.entry_time.strftime('%Y-%m-%d %H:%M:%S')}")
                logging.info(f"Stoploss: {self.active_trade['stoploss']}")
                logging.info(f"Target: {self.active_trade['target']}")
                logging.info(f"Exit Time Limit: {self.active_trade['exit_time'].strftime('%Y-%m-%d %H:%M:%S')}")
                logging.info(f"========================")
                
                # Store trade information for reporting
                self.trade_history.append({
                    'date': self.entry_time.strftime('%Y-%m-%d'),
                    'symbol': symbol,
                    'entry_time': self.entry_time.strftime('%H:%M:%S'),
                    'entry_price': entry_price,
                    'quantity': qty,
                    'stoploss': self.active_trade['stoploss'],
                    'target': self.active_trade['target'],
                    'paper_trade': self.paper_trading
                })
                
                # Save updated trade history to CSV and Excel
                try:
                    self.save_trade_history()
                except AttributeError as e:
                    logging.error(f"Error saving trade history: {str(e)}")
                    # Fallback: save directly to CSV
                    pd.DataFrame(self.trade_history).to_csv('logs/trade_history.csv', index=False)
                    logging.info("Used fallback method to save trade history to CSV")
                
                # Start continuous position monitoring with second-by-second updates
                self.continuous_position_monitor()
                
                return True
            else:
                if not self.paper_trading:  # Only log errors for real trading
                    logging.error(f"Order placement failed: {order_response}")
                return False
                
        except Exception as e:
            logging.error(f"Error executing trade: {str(e)}")
            return False
    
    def manage_position(self):
        """Monitor and manage existing positions using real-time websocket data"""
        if not self.active_trade:
            return
        
        # Market hours check at the top of the function to ensure hard exit enforcement
        ist_now = self.get_ist_datetime()
        market_close_time = datetime.time(15, 30)  # 3:30 PM IST
        
        # Also check 30-minute max duration at the top level to ensure strict enforcement
        if self.active_trade and self.active_trade.get('entry_time'):
            entry_time = self.active_trade['entry_time']
            current_timestamp = ist_now.timestamp()
            entry_timestamp = entry_time.timestamp() if hasattr(entry_time, 'timestamp') else 0
            elapsed_minutes = (current_timestamp - entry_timestamp) / 60
            
            # If trade has been running for more than 30 minutes, force exit
            if elapsed_minutes > 30:
                logging.warning(f"HARD ENFORCEMENT: Trade has been running for {elapsed_minutes:.2f} minutes, exceeding 30-minute limit. Forcing exit.")
                symbol = self.active_trade['symbol']
                # Try to get latest price
                current_price = self.active_trade.get('last_known_price', self.active_trade.get('entry_price', 0))
                if symbol in self.live_prices:
                    current_price = self.live_prices[symbol]
                    
                exit_type = "MAX_DURATION"
                exit_price = current_price
                
                # Execute exit
                is_paper_trade = self.active_trade.get('paper_trade', self.paper_trading)
                exit_response = {'s': 'ok', 'id': f'PAPER-EXIT-{int(time.time())}'}
                if not is_paper_trade:
                    from src.fyers_api_utils import exit_position
                    exit_response = exit_position(self.fyers, symbol, self.active_trade['quantity'], "SELL")
                
                # Process the exit
                self.process_exit(exit_type, exit_price, exit_response)
                return
        
        # Force exit positions at market close
        if ist_now.time() >= market_close_time and self.active_trade:
            logging.warning("MARKET CLOSING: Forcing exit of all positions")
            symbol = self.active_trade['symbol']
            
            # Try to get the most recent price
            current_price = None
            if symbol in self.live_prices:
                current_price = self.live_prices[symbol]
            else:
                try:
                    from src.fyers_api_utils import get_ltp
                    current_price = get_ltp(self.fyers, symbol)
                except Exception as e:
                    logging.error(f"Error getting price at market close: {str(e)}")
                
            # If we still don't have a price, use the last known price
            if current_price is None:
                current_price = self.active_trade.get('last_known_price', 
                                                    self.active_trade.get('entry_price', 0))
                logging.warning(f"Using fallback price for market close exit: {current_price}")
                
            # Force exit at market close
            exit_type = "MARKET_CLOSE"
            exit_price = current_price
            logging.info(f"MARKET CLOSE EXIT: Exiting {symbol} at {current_price}")
            
            # Execute the exit
            is_paper_trade = self.active_trade.get('paper_trade', self.paper_trading)
            if is_paper_trade:
                exit_response = {'s': 'ok', 'id': f'PAPER-EXIT-{int(time.time())}'}
            else:
                # For live trading, execute a market order to close the position
                try:
                    exit_response = self.place_market_order(symbol, "SELL", self.active_trade['quantity'])
                except Exception as e:
                    logging.error(f"Error placing market close exit order: {str(e)}")
                    exit_response = {'s': 'error', 'message': str(e)}
            
            # Process the exit
            self.process_exit(exit_type, exit_price, exit_response)
            return
            
        # Log once every 5 seconds to confirm monitor is running
        should_log_heartbeat = (int(time.time()) % 5 == 0)
        if should_log_heartbeat:
            logging.info("Position monitor heartbeat - monitoring is active")
            
        try:
            # Get current market data
            symbol = self.active_trade['symbol']
            entry_price = self.active_trade['entry_price']
            quantity = self.active_trade['quantity']
            current_time = self.get_ist_datetime()
            
            # First try to get price from websocket for fastest and most accurate data
            current_price = None
            if symbol in self.live_prices:
                current_price = self.live_prices[symbol]
                if should_log_heartbeat:
                    logging.info(f"Using real-time websocket price for {symbol}: {current_price}")
            
            # If websocket price not available, try API methods
            if current_price is None:
                # Try direct API call first (faster than option chain)
                from src.fyers_api_utils import get_ltp
                current_price = get_ltp(self.fyers, symbol)
                
                if current_price is None:
                    # Fallback to option chain as last resort
                    try:
                        option_chain = get_nifty_option_chain()
                        if option_chain is not None and not option_chain.empty:
                            # Find the option in the chain
                            matching_options = option_chain[option_chain['symbol'] == symbol]
                            if not matching_options.empty:
                                current_price = matching_options.iloc[0]['last_price']
                            else:
                                logging.warning(f"Symbol {symbol} not found in option chain")
                    except Exception as e:
                        logging.error(f"Error fetching option chain: {str(e)}")
                        
                # If still no price, try fallback or use last known price
                if current_price is None:
                    current_price = self.get_fallback_option_price(symbol)
                    
                # If all methods failed, use last known price or skip
                if current_price is None:
                    current_price = self.active_trade.get('last_known_price')
                    if current_price is None:
                        logging.warning("Could not get current price data - skipping this monitoring cycle")
                        return None
                    logging.warning(f"Using last known price for {symbol}: {current_price}")
            
            # Update the last known price
            self.active_trade['last_known_price'] = current_price
            
            # Parse strike and option type from symbol
            # Extract strike price from symbol (format: NSE:NIFTY25JUN19500CE)
            symbol_parts = symbol.split(':')[1]  # Remove 'NSE:'
            strike = None
            option_type = 'CE' if symbol.endswith('CE') else 'PE'
            
            # Direct approach - extract 5 digits before CE or PE
            import re
            match = re.search(r'(\d{5})[CP]E$', symbol)
            if match:
                try:
                    strike = int(match.group(1))
                    # Removed excessive logging that happens every second
                except ValueError:
                    logging.error(f"Error converting extracted strike price to integer: {match.group(1)}")
            
            # If that didn't work, try to find it in option chain
            if not strike and 'option_chain' in locals() and option_chain is not None and not option_chain.empty:
                for idx, row in option_chain.iterrows():
                    if row['symbol'] == symbol:
                        strike = int(row['strikePrice'])
                        break
            
            # Initialize current_price
            current_price = None
            
            # Check if we have a valid option chain to work with
            if 'option_chain' in locals() and option_chain is not None and not option_chain.empty:
                if not strike:
                    # Try to get the last traded price directly from the option chain
                    direct_match = option_chain[option_chain['symbol'] == symbol]
                    if not direct_match.empty:
                        current_price = direct_match['lastPrice'].values[0]
                    else:
                        logging.warning(f"Could not parse strike price from symbol: {symbol}")
                else:
                    # Get current price from option chain
                    matching_options = option_chain[(option_chain['strikePrice'] == strike) & 
                                                (option_chain['option_type'] == option_type)]
                    
                    if matching_options.empty:
                        # Try direct symbol match
                        matching_options = option_chain[option_chain['symbol'] == symbol]
                        
                    if not matching_options.empty:
                        current_price = matching_options['lastPrice'].values[0]
            
            # If we still don't have a price, try the fallback method (direct API only)
            if current_price is None:
                current_price = self.get_fallback_option_price(symbol)
                if current_price is None:
                    logging.error("Could not determine current option price through any method")
                    # No simulation - just skip this monitoring cycle
                    logging.warning("Skipping this monitoring cycle due to unavailable price data")
                    return None
                else:
                    # Store the last known good price
                    self.active_trade['last_known_price'] = current_price
            
            # Check if this is a paper trade
            is_paper_trade = self.active_trade.get('paper_trade', self.paper_trading)
            
            # Calculate current P&L
            entry_value = entry_price * quantity
            current_value = current_price * quantity
            unrealized_pnl = current_value - entry_value
            unrealized_pnl_pct = (unrealized_pnl / entry_value) * 100 if entry_value > 0 else 0
            
            # Get current stoploss level (may be original or trailing)
            current_sl = self.active_trade['stoploss']
            
            # Display second-by-second trade information with a cleaner format
            # Add Time remaining until exit for better tracking
            time_remaining = None
            if self.active_trade and self.active_trade.get('exit_time'):
                # Handle timezone differences by ensuring both datetimes are naive or both are aware
                exit_time = self.active_trade['exit_time']
                if hasattr(exit_time, 'tzinfo') and exit_time.tzinfo is not None:
                    # If exit_time has timezone but current_time doesn't, make current_time timezone-aware
                    if current_time.tzinfo is None:
                        # Use the same timezone as exit_time
                        ist_tz = exit_time.tzinfo
                        current_time = current_time.replace(tzinfo=ist_tz)
                else:
                    # If exit_time has no timezone but current_time does, make exit_time timezone-aware
                    if current_time.tzinfo is not None and exit_time.tzinfo is None:
                        exit_time = exit_time.replace(tzinfo=current_time.tzinfo)
                
                # Now safely calculate time difference
                try:
                    time_diff = exit_time - current_time
                    mins, secs = divmod(time_diff.total_seconds(), 60)
                    time_remaining = f"{int(mins)}m{int(secs)}s"
                except Exception as e:
                    logging.warning(f"Error calculating time remaining: {str(e)}")
                    time_remaining = "N/A"
                
            logging.info(f"TRADE_UPDATE | {'PAPER' if is_paper_trade else 'LIVE'} | {symbol} | " + 
                        f"Entry: {entry_price:.2f} | LTP: {current_price:.2f} | " +
                        f"SL: {current_sl:.2f} | P&L: {unrealized_pnl:.2f} ({unrealized_pnl_pct:.2f}%) | " +
                        f"Time left: {time_remaining or 'N/A'}")
            
            # Update trailing stoploss if enabled
            config = load_config()
            use_trailing_stop = config.get('strategy', {}).get('use_trailing_stop', False)
            trailing_trigger_pct = config.get('strategy', {}).get('trailing_trigger_pct', 10)
            
            if use_trailing_stop and unrealized_pnl_pct >= trailing_trigger_pct:
                logging.debug(f"Trailing stop triggered at {unrealized_pnl_pct:.2f}% profit (threshold: {trailing_trigger_pct}%)")
                self.update_trailing_stoploss(current_price)
            
            # Check for partial exit opportunity
            partial_exit_taken = self.check_partial_exit(current_time, current_price)
            
            # Check exit conditions:
            exit_type = None
            exit_price = None
            
            # 1. Stoploss hit
            if current_price <= self.active_trade['stoploss']:
                exit_type = "STOPLOSS"
                exit_price = current_price
                logging.info(f"STOPLOSS HIT: Exiting {symbol} at {current_price}")
                
            # 2. Target hit
            elif current_price >= self.active_trade['target']:
                exit_type = "TARGET"
                exit_price = current_price
                logging.info(f"TARGET HIT: Exiting {symbol} at {current_price}")
                
            # 3. Time-based exit (check against both exit time and market close)
            # Ensure consistent datetime comparison by normalizing both times
            exit_time = self.active_trade['exit_time']
            
            # Convert to timestamp for reliable comparison (avoids timezone issues)
            current_timestamp = current_time.timestamp()
            exit_timestamp = exit_time.timestamp() if hasattr(exit_time, 'timestamp') else 0
            entry_timestamp = self.active_trade['entry_time'].timestamp() if hasattr(self.active_trade['entry_time'], 'timestamp') else 0
            
            # Calculate elapsed minutes since entry for logging and decision making
            elapsed_minutes = (current_timestamp - entry_timestamp) / 60
            
            # Check exit conditions with more explicit logging
            time_limit_exceeded = current_timestamp >= exit_timestamp
            max_trade_duration_exceeded = elapsed_minutes >= 30
            market_closing_soon = current_time.time() >= datetime.time(15, 25)
            
            if time_limit_exceeded or max_trade_duration_exceeded or market_closing_soon:
                # Determine the appropriate exit type based on conditions
                if market_closing_soon and current_time.time() < datetime.time(15, 30):
                    exit_type = "MARKET_CLOSING"
                    logging.info(f"MARKET CLOSING SOON: Exiting {symbol} at {current_price} before market close")
                elif max_trade_duration_exceeded:
                    exit_type = "MAX_DURATION"
                    logging.info(f"MAX DURATION EXCEEDED: Exiting {symbol} at {current_price} after {elapsed_minutes:.2f} minutes (30-min limit enforced)")
                else:
                    exit_type = "TIME"
                    logging.info(f"TIME EXIT: Exiting {symbol} at {current_price} after {elapsed_minutes:.2f} minutes")
                
                exit_price = current_price
            
            # Process exit if conditions are met
            if exit_type:
                # Execute exit order
                if is_paper_trade:
                    # Simulate exit for paper trade
                    exit_response = {'s': 'ok', 'id': f'PAPER-EXIT-{int(time.time())}'}
                    logging.info(f"Paper trade exit simulated: {symbol} SELL {quantity}")
                else:
                    # Place real exit order
                    exit_response = exit_position(self.fyers, self.active_trade['symbol'], quantity, "SELL")
                
                # Use the dedicated process_exit function for consistent handling
                self.process_exit(exit_type, exit_price, exit_response)
            return False
        except Exception as e:
            logging.error(f"Error in manage_position: {str(e)}")
            return False
    
    def process_exit(self, exit_type, exit_price, exit_response):
        """Process exit consistently for all exit types (stoploss, target, time, market close)"""
        if not self.active_trade:
            logging.warning("No active trade to exit")
            return
            
        if exit_response and exit_response.get('s') == 'ok':
            symbol = self.active_trade['symbol']
            quantity = self.active_trade['quantity']
            entry_price = self.active_trade['entry_price']
            is_paper_trade = self.active_trade.get('paper_trade', self.paper_trading)
            current_time = self.get_ist_datetime()
            
            # Calculate final P&L
            entry_value = entry_price * quantity
            exit_value = exit_price * quantity
            realized_pnl = exit_value - entry_value
            realized_pnl_pct = (realized_pnl / entry_value) * 100 if entry_value > 0 else 0
            
            # Log exit details
            duration = current_time - self.active_trade['entry_time']
            duration_minutes = duration.total_seconds() / 60
            
            # Enhanced exit reason logging
            exit_reason = {
                'STOPLOSS': 'Stoploss hit',
                'TARGET': 'Target achieved',
                'TIME': 'Time limit (30 min) reached',
                'MAX_DURATION': '30-minute hard limit enforced',
                'MARKET_CLOSING': 'Market closing soon (15:25)',
                'MARKET_CLOSE': 'Market closed (15:30)'
            }.get(exit_type, exit_type)
            
            logging.info(f"=== {'PAPER' if is_paper_trade else 'LIVE'} TRADE EXITED: {exit_type} ===")
            logging.info(f"Exit Reason: {exit_reason}")
            logging.info(f"Symbol: {symbol}")
            logging.info(f"Entry Price: {entry_price}")
            logging.info(f"Exit Price: {exit_price}")
            logging.info(f"Quantity: {quantity}")
            logging.info(f"P&L: {realized_pnl:.2f} ({realized_pnl_pct:.2f}%)")
            logging.info(f"Duration: {duration_minutes:.1f} minutes")
            logging.info(f"========================")
            
            # Update trade history
            for trade in self.trade_history:
                # Format entry time properly based on its type
                entry_time_str = self.active_trade['entry_time']
                trade_entry_time = trade['entry_time']
                
                # Convert datetime to string if needed for comparison
                if isinstance(entry_time_str, datetime.datetime):
                    entry_time_str = entry_time_str.strftime('%H:%M:%S')
                
                # Simple string match or check if entry times match approximately
                entry_time_match = (trade['symbol'] == symbol and 
                                  (trade_entry_time == entry_time_str or 
                                   (isinstance(trade_entry_time, str) and trade_entry_time.split(':')[0:2] == entry_time_str.split(':')[0:2])))
                    
                if entry_time_match:
                    trade['exit_time'] = current_time.strftime('%H:%M:%S')
                    trade['exit_price'] = exit_price
                    trade['exit_type'] = exit_type
                    trade['pnl'] = realized_pnl
                    trade['pnl_percent'] = realized_pnl_pct
                    trade['duration_minutes'] = duration_minutes
            
            # Save updated trade history
            try:
                self.save_trade_history()
            except AttributeError as e:
                logging.error(f"Error saving trade history: {str(e)}")
                # Fallback: save directly to CSV
                pd.DataFrame(self.trade_history).to_csv('logs/trade_history.csv', index=False)
                
            # Clear the active trade
            self.active_trade = None
            
            # Record performance metrics
            self.record_performance(symbol, 
                                   'CE' if symbol.endswith('CE') else 'PE', 
                                   0,  # This is position_id, typically 0 for paper trades 
                                   entry_price, 
                                   exit_price, 
                                   quantity, 
                                   realized_pnl, 
                                   realized_pnl_pct, 
                                   exit_type, 
                                   duration_minutes, 
                                   is_paper_trade)
            
            # Clean up resources
            if hasattr(self, 'tick_queue'):
                self.tick_queue = queue.Queue()  # Clear any pending ticks
                
            return True
        else:
            # Handle failed exit attempt
            logging.error(f"Failed to exit position: {exit_response}")
            return False
    
    def continuous_position_monitor(self):
        """Monitor active position continuously with second-by-second updates using websocket"""
        if not self.active_trade:
            logging.info("No active trade to monitor")
            return
            
        try:
            # Create a monitor thread that runs until position is closed
            def monitor_thread():
                consecutive_errors = 0
                max_consecutive_errors = 5  # Allow up to 5 consecutive errors before logging a warning
                
                logging.info("Position monitor thread started")
                import threading
                logging.info(f"Monitor thread ID: {threading.get_ident()}")
                
                # Set up websocket for real-time price monitoring if not already established
                if not self.data_socket:
                    symbol = self.active_trade['symbol']
                    nifty_symbol = "NSE:NIFTY50-INDEX"
                    symbols_to_monitor = [symbol, nifty_symbol]
                    
                    logging.info(f"Starting websocket connection for symbols: {symbols_to_monitor}")
                    
                    # Define callback to handle websocket data
                    def ws_data_handler(symbol, key, value, tick_data):
                        if key == 'ltp' and symbol in symbols_to_monitor:
                            # Store the tick data in the live_prices dictionary
                            self.live_prices[symbol] = float(value)
                            
                            if symbol == self.active_trade['symbol']:
                                # Update last known price in active trade
                                self.active_trade['last_known_price'] = float(value)
                    
                    # Start websocket connection
                    from src.fyers_api_utils import start_market_data_websocket
                    self.data_socket = start_market_data_websocket(symbols=symbols_to_monitor, callback_handler=ws_data_handler)
                    logging.info("Websocket connection established for real-time price updates")
                
                # Create a direct per-second update function that uses websocket data when available
                def simple_price_update():
                    """Simplified price update that just logs current status"""
                    if not self.active_trade:
                        return
                        
                    symbol = self.active_trade['symbol']
                    entry_price = self.active_trade['entry_price']
                    current_time = self.get_ist_datetime()
                    
                    # Try to get price using websocket first, then fall back to API
                    from src.fyers_api_utils import get_ltp
                    current_price = get_ltp(self.fyers, symbol, self.data_socket) or self.active_trade.get('last_known_price', entry_price)
                    
                    # Store the latest price
                    if current_price:
                        self.active_trade['last_known_price'] = current_price
                    
                    # Update only if we have a price
                    if current_price:
                        # Calculate P&L
                        quantity = self.active_trade['quantity']
                        entry_value = entry_price * quantity
                        current_value = current_price * quantity
                        unrealized_pnl = current_value - entry_value
                        unrealized_pnl_pct = (unrealized_pnl / entry_value) * 100 if entry_value > 0 else 0
                        
                        # Add time remaining calculation with better warning
                        time_remaining = "N/A"
                        if 'exit_time' in self.active_trade:
                            time_diff = self.active_trade['exit_time'] - current_time
                            if time_diff.total_seconds() > 0:
                                mins, secs = divmod(time_diff.total_seconds(), 60)
                                time_remaining = f"{int(mins)}m{int(secs)}s"
                                # Add warning if approaching 30-minute limit
                                if mins < 2:
                                    logging.warning(f"⚠️ TRADE APPROACHING 30-MIN LIMIT: Only {time_remaining} left until forced exit!")
                            else:
                                time_remaining = "0m0s (EXIT DUE)"
                                logging.warning("⚠️ 30-MINUTE TRADE LIMIT REACHED: Position will exit on next check")
                        
                        # Simple status update with websocket indicator
                        data_source = "WS" if symbol in self.live_prices else "API"
                        logging.info(f"POSITION | {symbol} | Entry: {entry_price:.2f} | Current: {current_price:.2f} [{data_source}] | " +
                                    f"P&L: {unrealized_pnl:.2f} ({unrealized_pnl_pct:.2f}%) | Time left: {time_remaining}")
                
                # Main monitoring loop
                while self.active_trade:
                    try:
                        # Always provide a simple update each second
                        simple_price_update()
                        
                        # Do the full position management (exit checks etc) every 3 seconds
                        # to avoid overwhelming the API
                        if int(time.time()) % 3 == 0:
                            self.manage_position()
                            
                        consecutive_errors = 0  # Reset error counter on success
                        time.sleep(1)  # Wait for one second before checking again
                        
                    except Exception as e:
                        consecutive_errors += 1
                        logging.error(f"Error in continuous position monitoring: {str(e)}")
                        
                        if consecutive_errors >= max_consecutive_errors:
                            logging.warning(f"Multiple consecutive errors ({consecutive_errors}) in position monitoring. Check system stability.")
                            # Try minimal monitoring even when errors occur
                            try:
                                simple_price_update()
                            except:
                                pass
                            
                        time.sleep(1)  # Wait before retrying
                
                logging.info("Position monitoring thread stopped - no active trade")
                        
            # Start monitor in a separate thread to not block the main thread
            thread = threading.Thread(target=monitor_thread, name="PositionMonitor")
            thread.daemon = True  # Thread will exit when main program exits
            thread.start()
            self._start_tick_queue_consumer()
            logging.info("Continuous position monitoring started - updates every second")
            return thread
            
        except Exception as e:
            logging.error(f"Error starting position monitoring: {str(e)}")
            return None

    def generate_daily_report(self):
        """Generate a summary report for today's trading activity"""
        # Get today's date in IST
        today = self.get_ist_datetime().strftime("%Y-%m-%d")
        
        # Filter trades for today
        todays_trades = [trade for trade in self.trade_history 
                         if trade.get('date') == today]
        
        if not todays_trades:
            logging.info("No trades executed today.")
            return
            
        # Calculate daily statistics
        num_trades = len(todays_trades)
        profitable_trades = [t for t in todays_trades 
                            if t.get('status') == 'CLOSED' and t.get('pnl', 0) > 0]
        losing_trades = [t for t in todays_trades 
                        if t.get('status') == 'CLOSED' and t.get('pnl', 0) <= 0]
        open_trades = [t for t in todays_trades if t.get('status') == 'OPEN']
        
        total_pnl = sum(t.get('pnl', 0) for t in todays_trades 
                       if t.get('status') == 'CLOSED')
        
        # Generate report
        report = [
            "=" * 50,
            f"DAILY TRADING REPORT - {today}",
            "=" * 50,
            f"Total Trades: {num_trades}",
            f"Completed Trades: {len(profitable_trades) + len(losing_trades)}",
            f"Profitable Trades: {len(profitable_trades)}",
            f"Losing Trades: {len(losing_trades)}",
            f"Open Trades: {len(open_trades)}",
            f"Total P&L: {total_pnl:.2f}",
            "-" * 50,
            "TRADE DETAILS:",
            "-" * 50
        ]
        
        # Add details for each trade
        for i, trade in enumerate(todays_trades, 1):
            status = trade.get('status', 'UNKNOWN')
            pnl = trade.get('pnl', 0)
            pnl_str = f"{pnl:.2f}" if pnl is not None else "N/A"
            
            trade_info = [
                f"Trade #{i}:",
                f"  Symbol: {trade.get('symbol', 'N/A')}",
                f"  Entry Time: {trade.get('entry_time', 'N/A')}",
                f"  Entry Price: {trade.get('entry_price', 'N/A')}",
                f"  Quantity: {trade.get('quantity', 'N/A')}",
                f"  Status: {status}"
            ]
            
            if status == 'CLOSED':
                trade_info.extend([
                    f"  Exit Time: {trade.get('exit_time', 'N/A')}",
                    f"  Exit Price: {trade.get('exit_price', 'N/A')}",
                    f"  P&L: {pnl_str}",
                    f"  Exit Reason: {trade.get('exit_reason', 'N/A')}"
                ])
                
            report.extend(trade_info)
            report.append("-" * 30)
            
        # Log the report
        for line in report:
            logging.info(line)
            
        # Save report to file
        report_dir = "logs/reports"
        os.makedirs(report_dir, exist_ok=True)
        
        with open(f"{report_dir}/report_{today}.txt", "w") as f:
            f.write("\n".join(report))
            
        logging.info(f"Daily report saved to {report_dir}/report_{today}.txt")
        return True

    def get_ist_datetime(self):
        """Get current time in Indian Standard Time (IST)"""
        # Define the time zones
        ist_tz = pytz.timezone('Asia/Kolkata')
        
        # Get current time in UTC and convert to IST
        utc_now = datetime.datetime.now(pytz.UTC)
        ist_now = utc_now.astimezone(ist_tz)
        
        return ist_now
    
    def update_trailing_stoploss(self, current_price):
        """Update stoploss based on trailing stop percentage to lock in profits"""
        if not self.active_trade:
            return

        # Get the trailing stop percentage from config
        config = load_config()
        trailing_stop_pct = config.get('strategy', {}).get('trailing_stop_pct', 10)

        entry_price = self.active_trade['entry_price']
        symbol = self.active_trade['symbol']
        current_sl = self.active_trade['stoploss']

        # Store the original stoploss if not already stored
        if 'original_stoploss' not in self.active_trade:
            self.active_trade['original_stoploss'] = self.active_trade['stoploss']

        original_stoploss = self.active_trade['original_stoploss']

        # Debug logging for diagnosis
        logging.info(f"TRAILING SL DEBUG | symbol: {symbol} | entry_price: {entry_price} | current_price: {current_price} | trailing_stop_pct: {trailing_stop_pct} | current_sl: {current_sl} | original_stoploss: {original_stoploss}")

        # For both CE and PE (when long), the stoploss should trail upwards as price increases
        potential_stoploss = current_price * (1 - (trailing_stop_pct / 100))
        logging.info(f"TRAILING SL DEBUG | [LONG] potential_stoploss: {potential_stoploss}")
        if potential_stoploss > current_sl and potential_stoploss > original_stoploss:
            old_sl = self.active_trade['stoploss']
            self.active_trade['stoploss'] = potential_stoploss
            profit_locked_pct = ((potential_stoploss - entry_price) / entry_price) * 100
            logging.info(f"TRAILING SL | Updated from {old_sl:.2f} to {potential_stoploss:.2f} | " +
                         f"Current price: {current_price:.2f} | Profit locked: {profit_locked_pct:.2f}%")
        else:
            logging.info(f"TRAILING SL DEBUG | [LONG] No update: potential_stoploss ({potential_stoploss}) <= current_sl ({current_sl}) or original_stoploss ({original_stoploss})")
    
    def check_partial_exit(self, current_time, current_price):
        """Check if we should take partial profit based on time elapsed"""
        if not self.active_trade:
            return False
        
        # Handle entry_time that could be either a string or datetime object
        if isinstance(self.active_trade['entry_time'], str):
            # Try different formats since the entry_time might be in different formats
            try:
                entry_time = datetime.datetime.strptime(self.active_trade['entry_time'], '%Y-%m-%d %H:%M:%S')
            except ValueError:
                # Try just the time format
                try:
                    entry_time = datetime.datetime.strptime(self.active_trade['date'] + ' ' + self.active_trade['entry_time'], '%Y-%m-%d %H:%M:%S')
                except (ValueError, KeyError):
                    # Default to current time if parsing fails
                    logging.warning(f"Couldn't parse entry_time: {self.active_trade['entry_time']}, using current time")
                    entry_time = current_time
        else:
            entry_time = self.active_trade['entry_time']  # Already a datetime object
            
        time_elapsed = (current_time - entry_time).total_seconds() / 60
        
        config = load_config()
        partial_exit_config = config.get('strategy', {}).get('partial_exits', [])
        
        for exit_point in partial_exit_config:
            time_threshold = exit_point.get('time_minutes', 10)
            profit_threshold = exit_point.get('min_profit_pct', 5)
            exit_pct = exit_point.get('exit_percentage', 50)
            
            # Check if this partial exit has already been taken
            exit_key = f"partial_exit_{time_threshold}min"
            if exit_key in self.active_trade and self.active_trade[exit_key]:
                continue
            
            # Check if time and profit conditions are met
            entry_price = self.active_trade['entry_price']
            unrealized_pnl_pct = ((current_price - entry_price) / entry_price) * 100
            
            if time_elapsed >= time_threshold and unrealized_pnl_pct >= profit_threshold:
                # Mark this partial exit as taken
                self.active_trade[exit_key] = True
                
                # Calculate the number of contracts to exit
                total_quantity = self.active_trade['quantity']
                exit_quantity = int(total_quantity * (exit_pct / 100))
                
                # Don't exit if it would leave less than 1 contract
                if total_quantity - exit_quantity < 1:
                    return False
                
                # Update the position size
                self.active_trade['quantity'] = total_quantity - exit_quantity
                
                # Log the partial exit
                logging.info(f"PARTIAL EXIT: Taking {exit_pct}% profit on {self.active_trade['symbol']} ({exit_quantity} of {total_quantity} contracts) at {current_price}")
                
                # If this is paper trading, simulate the exit
                if self.active_trade.get('paper_trade', self.paper_trading):
                    partial_profit = (current_price - entry_price) * exit_quantity
                    partial_profit_pct = unrealized_pnl_pct
                    logging.info(f"Paper trade partial exit: {self.active_trade['symbol']} SELL {exit_quantity}")
                    logging.info(f"=== PAPER PARTIAL EXIT ===")
                    logging.info(f"Symbol: {self.active_trade['symbol']}")
                    logging.info(f"Entry Price: {entry_price}")
                    logging.info(f"Exit Price: {current_price}")
                    logging.info(f"Quantity: {exit_quantity}")
                    logging.info(f"Partial P&L: {partial_profit:.2f} ({partial_profit_pct:.2f}%)")
                    logging.info(f"Remaining Position: {self.active_trade['quantity']} contracts")
                    logging.info(f"========================")
                else:
                    # In live trading, execute the exit order
                    # This would involve calling exit_position with the partial quantity
                    pass
                
                return True
        
        return False
        
    def track_trade_performance(self, trade_data):
        """Record trade data for performance analysis"""
        try:
            # Create a DataFrame with this trade's data
            trade_df = pd.DataFrame([trade_data])
            
            # Create the performance tracking file if it doesn't exist
            file_path = 'logs/trade_performance.csv'
            if not os.path.exists(file_path):
                trade_df.to_csv(file_path, index=False)
                logging.info(f"Created new trade performance log at {file_path}")
            else:
                # Append to existing file
                trade_df.to_csv(file_path, mode='a', header=False, index=False)
                logging.info(f"Trade performance data recorded to {file_path}")
                
            # Calculate and log summary statistics
            all_trades = pd.read_csv(file_path)
            
            # Daily statistics
            today = datetime.datetime.now().strftime('%Y-%m-%d')
            today_trades = all_trades[all_trades['date'] == today]
            
            if len(today_trades) > 0:
                win_count = len(today_trades[today_trades['pnl_pct'] > 0])
                loss_count = len(today_trades) - win_count
                win_rate = win_count / len(today_trades) * 100
                avg_win = today_trades[today_trades['pnl_pct'] > 0]['pnl_pct'].mean() if win_count > 0 else 0
                avg_loss = today_trades[today_trades['pnl_pct'] < 0]['pnl_pct'].mean() if loss_count > 0 else 0
                
                logging.info("=== TODAY'S TRADING SUMMARY ===")
                logging.info(f"Total Trades: {len(today_trades)}")
                logging.info(f"Win Rate: {win_rate:.2f}%")
                logging.info(f"Average Win: {avg_win:.2f}%")
                logging.info(f"Average Loss: {avg_loss:.2f}%")
                logging.info(f"Expectancy: {(win_rate/100 * avg_win) + ((100-win_rate)/100 * avg_loss):.2f}%")
                logging.info("================================")
                
            return True
            
        except Exception as e:
            logging.error(f"Error recording trade performance: {str(e)}")
            return False
        
    def run_strategy(self, force_analysis=False):
        """Main function to run the strategy"""
        try:
            # Get current time in IST
            ist_now = self.get_ist_datetime()
            current_time = ist_now.time()
            
            # Market hours in IST
            market_open_time = datetime.time(9, 15)
            market_close_time = datetime.time(15, 30)
            
            # Log IST time for debugging
            logging.info(f"Current IST time: {ist_now.strftime('%Y-%m-%d %H:%M:%S')}")
            
            # Check if we're running close to market close time (after 15:00)
            if current_time >= datetime.time(15, 0) and current_time < market_close_time:
                logging.warning("⚠️ CAUTION: Running strategy after 15:00 IST. Trades will be force-exited at market close (15:30)!")
                logging.warning("Trades will run for less than the usual 30-minute duration due to market closing soon.")
                logging.warning("Consider waiting for the next trading day for optimal strategy execution.")
                
                # Prompt the user to confirm if they want to continue
                user_input = input("Do you want to continue running the strategy even though market closes soon? (y/n): ")
                if user_input.lower() != 'y':
                    logging.info("Strategy execution cancelled by user. Please run again during market hours.")
                    return
                else:
                    logging.info("User confirmed to run strategy despite approaching market close time.")
            
            # Check if market is open
            if current_time < market_open_time:
                logging.info("Waiting for market to open (IST time)...")
                return
            
            # For market close: generate daily report and exit
            if current_time >= market_close_time:
                # Check if we're within 5 minutes after market close
                if (current_time.hour == market_close_time.hour and
                    current_time.minute < market_close_time.minute + 5):
                    logging.info("Market closed (IST time). Generating daily report...")
                    self.generate_daily_report()
                    
                logging.info("Market closed (IST time). Strategy will resume next trading day.")
                return
            
            # Check if today is a weekday (0=Monday, 4=Friday, 5=Saturday, 6=Sunday)
            today = ist_now.weekday()
            if today > 4:  # Weekend check
                logging.info(f"Today is {'Saturday' if today == 5 else 'Sunday'} in IST. Market closed.")
                return
                
            # Step 1: Around 9:20, identify high OI strikes
            analysis_time = datetime.time(9, 20)
            # Give it a 1-minute window to ensure the job runs (9:20 to 9:21)
            if force_analysis or (
                current_time.hour == analysis_time.hour and 
                current_time.minute >= analysis_time.minute and 
                current_time.minute < analysis_time.minute + 1):
                logging.info("Performing OI analysis (manual trigger or scheduled)...")
                oi_result = self.identify_high_oi_strikes()
                logging.info(f"After OI analysis: put_breakout_level={self.put_breakout_level}, call_breakout_level={self.call_breakout_level}")
                if oi_result is False:
                    logging.error("OI analysis or breakout level calculation failed. Exiting strategy run.")
                    return
                logging.info(f"Breakout levels for monitoring: put={self.put_breakout_level}, call={self.call_breakout_level}")
            # Step 2: After 9:20, monitor for breakouts only if no trade has been taken today
            if self.highest_put_oi_strike and self.highest_call_oi_strike:
                if not self.active_trade and not self.trade_taken_today:
                    self.monitor_for_breakout()
                elif self.trade_taken_today and not self.active_trade:
                    logging.info("Daily trade limit: Trade already taken today. Skipping breakout monitoring.")
                    
            # Position management is handled by continuous_position_monitor thread
            # so we don't need to call manage_position() here anymore
                
        except Exception as e:
            logging.error(f"Error in run_strategy: {str(e)}")
    
    def save_trade_history(self):
        """Append all trades to a single Excel file (logs/trade_history.xlsx) and update CSV as well."""
        try:
            import openpyxl
            # Create DataFrame from trade history
            df = pd.DataFrame(self.trade_history)
            # If there are no trades, just create files with headers
            if len(df) == 0:
                df = pd.DataFrame(columns=[
                    'date', 'symbol', 'entry_time', 'exit_time', 'entry_price', 
                    'exit_price', 'quantity', 'stoploss', 'target', 'paper_trade', 
                    'pnl', 'exit_reason'
                ])
            # Save to CSV (keep for compatibility)
            df.to_csv('logs/trade_history.csv', index=False)
            
            # Prepare enhanced data for Excel with all requested columns
            excel_data = []
            index_value = "NIFTY"  # Default index
            
            # Only include complete trades in Excel export (with exit info) or active trades
            # This prevents duplicate entries with partial information
            for trade in self.trade_history:
                # Skip trades that don't have exit information unless they're active
                is_active_trade = self.active_trade and self.active_trade.get('symbol') == trade['symbol']
                is_complete_trade = 'exit_price' in trade and trade['exit_price'] is not None
                
                # Only include trades that are either complete or currently active
                if not (is_complete_trade or is_active_trade):
                    continue
                    
                direction = "PUT" if "PE" in trade['symbol'] else "CALL"
                entry_datetime = f"{trade['date']} {trade['entry_time']}"
                exit_datetime = f"{trade['date']} {trade.get('exit_time', 'N/A')}" if trade.get('exit_time') else "N/A"
                entry_value = trade['entry_price'] * trade['quantity']
                # Updated brokerage calculation: 20 Rs per trade (fixed) plus taxes
                # We're accounting for both entry and exit as separate trades
                fixed_brokerage = 20 * 2  # 20 Rs per trade (entry + exit)
                # Rough estimate for STT, CTT, GST, etc. - can be refined if specific rates are needed
                taxes = round(entry_value * 0.0002, 2)  # Approx. tax impact
                brokerage = fixed_brokerage + taxes
                # Update: For options, margin = premium * lot size
                margin_required = round(trade['entry_price'] * trade['quantity'], 2)
                pnl = trade.get('pnl', 0) if trade.get('pnl') is not None else 0
                pnl_percent = trade.get('pnl_percent', 0) if trade.get('pnl_percent') is not None else 0
                trailing_sl = trade.get('trailing_stoploss', trade['stoploss'])
                row = {
                    'Entry DateTime': entry_datetime,
                    'Index': index_value,
                    'Symbol': trade['symbol'],
                    'Direction': direction,
                    'Entry Price': trade['entry_price'],
                    'Exit DateTime': exit_datetime,
                    'Exit Price': trade.get('exit_price', 'N/A'),
                    'Stop Loss': trade['stoploss'],
                    'Target': trade['target'],
                    'Trailing SL': trailing_sl,
                    'Quantity': trade['quantity'],
                    'Brokerage': brokerage,
                    'P&L': pnl,
                    'Margin Required': margin_required,
                    '% Gain/Loss': f"{pnl_percent:.2f}%" if isinstance(pnl_percent, (int, float)) else 'N/A'
                }
                excel_data.append(row)
            enhanced_df = pd.DataFrame(excel_data)
            excel_path = 'logs/trade_history.xlsx'
            # For Excel, either create a new file or completely replace the existing one
            # This prevents duplicate entries and formatting issues
            try:
                # Complete rewrite approach to avoid duplicates and ensure clean data
                with pd.ExcelWriter(excel_path, engine='openpyxl', mode='w') as writer:
                    enhanced_df.to_excel(writer, index=False, sheet_name='Trade History')
                logging.info(f"Trade history appended to {excel_path}")
            except Exception as e:
                logging.error(f"Error writing to Excel: {e}")
                # Fallback: try to save with a different filename
                try:
                    backup_path = f'logs/trade_history_{int(time.time())}.xlsx'
                    with pd.ExcelWriter(backup_path, engine='openpyxl') as writer:
                        enhanced_df.to_excel(writer, index=False, sheet_name='Trade History')
                    logging.info(f"Trade history saved to backup file: {backup_path}")
                except Exception as backup_error:
                    logging.error(f"Failed to save trade history to backup Excel: {backup_error}")
            logging.info(f"Trade history appended to {excel_path}")
        except Exception as e:
            logging.error(f"Error saving trade history to Excel: {e}")
            pd.DataFrame(self.trade_history).to_csv('logs/trade_history.csv', index=False)
            logging.info("Trade history saved to CSV only due to Excel error")
    
    def cleanup(self):
        """Clean up resources before exiting"""
        try:
            # Close websocket connection if open
            if self.data_socket:
                logging.info("Closing websocket connection on exit...")
                try:
                    self.data_socket.close_connection()
                    logging.info("Websocket connection closed successfully")
                except Exception as e:
                    logging.error(f"Error closing websocket connection: {str(e)}")
                self.data_socket = None
                
            # Save any pending trade history
            self.save_trade_history()
            
        except Exception as e:
            logging.error(f"Error during cleanup: {str(e)}")
    
    # No duplicate method here - using the implementation at the top of the file
    
    def _find_second_highest_oi_strikes(self, option_chain, spot_price):
        """
        Find the 2nd highest OI strikes in the given option chain
        
        Args:
            option_chain: DataFrame containing the option chain data
            spot_price: Current spot price of Nifty
            
        Returns:
            None (updates instance variables directly)
        """
        if option_chain.empty:
            logging.error("Cannot find 2nd highest OI in empty option chain")
            return
        
        # Process PUT options
        put_data = option_chain[option_chain['option_type'] == 'PE']
        if not put_data.empty:
            try:
                # Filter by max distance
                put_data = put_data[abs(put_data['strikePrice'] - spot_price) <= self.max_strike_distance]
                
                if self.put_premium_at_9_20 < self.min_premium_threshold and len(put_data) > 1:
                    # Sort by openInterest descending
                    sorted_puts = put_data.sort_values('openInterest', ascending=False)
                    
                    # Look through top 5 highest OI strikes for better premiums
                    num_strikes_to_check = min(5, len(sorted_puts))
                    logging.info(f"Checking top {num_strikes_to_check} PUT strikes by OI for acceptable premiums")
                    
                    for i in range(1, num_strikes_to_check):  # Start from second highest (index 1)
                        alt_put_strike = sorted_puts.iloc[i]
                        strike = alt_put_strike['strikePrice']
                        premium = alt_put_strike['lastPrice']
                        symbol = alt_put_strike['symbol']
                        
                        logging.info(f"Alternative PUT OI #{i+1} - Strike: {strike}, Premium: {premium}, OI: {alt_put_strike['openInterest']}")
                        
                        # Update if premium meets threshold or is better than current
                        if premium >= self.min_premium_threshold or premium > self.put_premium_at_9_20:
                            self.highest_put_oi_strike = strike
                            self.put_premium_at_9_20 = premium
                            self.highest_put_oi_symbol = symbol
                            logging.info(f"Updated to alternative PUT strike {strike} because of better premium ({premium})")
                            break  # Found a suitable alternative
            except Exception as e:
                logging.error(f"Error finding alternative PUT strikes: {str(e)}")
        
        # Process CALL options
        call_data = option_chain[option_chain['option_type'] == 'CE']
        if not call_data.empty:
            try:
                # Filter by max distance
                call_data = call_data[abs(call_data['strikePrice'] - spot_price) <= self.max_strike_distance]
                
                if self.call_premium_at_9_20 < self.min_premium_threshold and len(call_data) > 1:
                    # Sort by openInterest descending
                    sorted_calls = call_data.sort_values('openInterest', ascending=False)
                    
                    # Look through top 5 highest OI strikes for better premiums
                    num_strikes_to_check = min(5, len(sorted_calls))
                    logging.info(f"Checking top {num_strikes_to_check} CALL strikes by OI for acceptable premiums")
                    
                    for i in range(1, num_strikes_to_check):  # Start from second highest (index 1)
                        alt_call_strike = sorted_calls.iloc[i]
                        strike = alt_call_strike['strikePrice']
                        premium = alt_call_strike['lastPrice']
                        symbol = alt_call_strike['symbol']
                        
                        logging.info(f"Alternative CALL OI #{i+1} - Strike: {strike}, Premium: {premium}, OI: {alt_call_strike['openInterest']}")
                        
                        # Update if premium meets threshold or is better than current
                        if premium >= self.min_premium_threshold or premium > self.call_premium_at_9_20:
                            self.highest_call_oi_strike = strike
                            self.call_premium_at_9_20 = premium
                            self.highest_call_oi_symbol = symbol
                            logging.info(f"Updated to alternative CALL strike {strike} because of better premium ({premium})")
                            break  # Found a suitable alternative
            except Exception as e:
                logging.error(f"Error finding alternative CALL strikes: {str(e)}")
            
    def get_fallback_option_price(self, symbol):
        """
        Get current option price using a direct Fyers API call
        instead of relying on the option chain data
        
        Args:
            symbol: The option symbol (e.g. 'NSE:NIFTY2570325500CE')
            
        Returns:
            float: Current option price or None if not available
        """
        try:
            # Only try to get real data, no simulation
            if not self.paper_trading:
                # Try to get the price using fyers_api_utils
                from src.fyers_api_utils import get_ltp
                price = get_ltp(self.fyers, symbol)
                
                if price and price > 0:
                    logging.info(f"Got price {price} for {symbol} using direct API call")
                    return price
            
            # For paper trading, use the last known price without simulation
            if self.paper_trading and self.active_trade:
                last_price = self.active_trade.get('last_known_price')
                if last_price:
                    return last_price
                return self.active_trade.get('entry_price')
                
            return None
        except Exception as e:
            logging.error(f"Error in get_fallback_option_price: {str(e)}")
            return None

    def get_nifty_spot_from_websocket(self):
        """
        Get the current Nifty spot price from websocket data if available,
        otherwise fetch using API
        
        Returns:
            float: Current price of Nifty 50 Index
        """
        nifty_symbol = "NSE:NIFTY50-INDEX"
        
        # Try to get from websocket first
        if nifty_symbol in self.live_prices:
            price = self.live_prices[nifty_symbol]
            return float(price)
            
        # Fallback to API call
        from src.fyers_api_utils import get_nifty_spot_price_direct
        return get_nifty_spot_price_direct()

    def record_performance(self, symbol, option_type, position_id, entry_price, exit_price, quantity, pnl, pnl_pct, exit_type, duration_minutes, is_paper_trade):
        """Record trade performance metrics for analysis"""
        try:
            # Create a data record for the trade
            trade_data = {
                'date': self.get_ist_datetime().strftime('%Y-%m-%d'),
                'time': self.get_ist_datetime().strftime('%H:%M:%S'),
                'symbol': symbol,
                'option_type': option_type,
                'position_id': position_id,
                'entry_price': entry_price,
                'exit_price': exit_price,
                'quantity': quantity,
                'pnl': pnl,
                'pnl_pct': pnl_pct,
                'exit_type': exit_type,
                'duration_minutes': duration_minutes,
                'is_paper': is_paper_trade
            }
            
            # Record in performance tracking if needed
            self.track_trade_performance(trade_data)
            return True
            
        except Exception as e:
            logging.error(f"Error recording trade performance: {str(e)}")
            return False
        
    def clear_logs(self):
        """Clear the strategy log file at the start of a new trading day"""
        try:
            log_path = 'logs/strategy.log'
            if os.path.exists(log_path):
                # Create a backup of the current log
                from datetime import datetime
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_path = f'logs/strategy_{timestamp}.log.bak'
                
                # Try to make a backup first
                try:
                    import shutil
                    shutil.copy2(log_path, backup_path)
                    logging.info(f"Created log backup at {backup_path}")
                except Exception as e:
                    logging.warning(f"Could not create log backup: {str(e)}")
                
                # Clear the current log file
                with open(log_path, 'w') as f:
                    f.write(f"Log file cleared on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                    
                logging.info("Log file has been cleared for new trading day")
                return True
            else:
                logging.warning(f"Log file {log_path} not found, nothing to clear")
                return False
        except Exception as e:
            logging.error(f"Error clearing log file: {str(e)}")
            return False







