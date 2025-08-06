"""
Fixed version of the strategy file with proper update_trailing_stoploss implementation
"""
import logging
import time
import pandas as pd
from datetime import datetime, timedelta
import pytz
import os
import json
import numpy as np
import traceback
import sys
import requests
import threading
import websocket
from collections import defaultdict
from src.fyers_api_utils import get_fyers_client
from src.fixed_improved_websocket import enhanced_start_market_data_websocket

class OpenInterestStrategy:
    def __init__(self):
        # Initialize your strategy here
        self.active_trade = {}
        self.live_prices = {}
        self.config = {}
        self.paper_trading = True
        self.market_closed = False
        self.trade_taken_today = False
        self.put_breakout_level = 0
        self.call_breakout_level = 0
        self.highest_put_oi_strike = 0
        self.highest_call_oi_strike = 0
        self.fyers = get_fyers_client()
        self.min_premium_threshold = self.config.get('strategy', {}).get('min_premium_threshold', 50.0)
        self.entry_time = None
        self.max_strike_distance = self.config.get('strategy', {}).get('max_strike_distance', 500)
        self.trade_history = []
        # Load today's trade history if file exists
        today = datetime.now().strftime('%Y%m%d')
        excel_path = f'logs/trade_history_{today}.xlsx'
        csv_path = 'logs/trade_history.csv'
        if os.path.exists(excel_path):
            try:
                df = pd.read_excel(excel_path)
                self.trade_history = df.to_dict('records')
                logging.info(f"Loaded existing trade history from {excel_path}")
            except Exception as e:
                logging.error(f"Error loading trade history from {excel_path}: {e}")
        elif os.path.exists(csv_path):
            try:
                df = pd.read_csv(csv_path)
                self.trade_history = df.to_dict('records')
                logging.info(f"Loaded existing trade history from {csv_path}")
            except Exception as e:
                logging.error(f"Error loading trade history from {csv_path}: {e}")

    def update_trailing_stoploss(self, current_price):
        """
        Update the trailing stoploss based on current price and profit percentage.
        """
        if not self.active_trade:
            return

        symbol = self.active_trade.get('symbol', '')
        entry_price = self.active_trade.get('entry_price', 0)
        current_sl = self.active_trade.get('stoploss', 0)
        original_stoploss = self.active_trade.get('original_stoploss', current_sl)

        # First time trailing SL is called, store the original stoploss
        if 'original_stoploss' not in self.active_trade:
            self.active_trade['original_stoploss'] = current_sl
            original_stoploss = current_sl

        # Get trailing stop percentage from config
        config = self.config or {}
        trailing_stop_pct = config.get('strategy', {}).get('trailing_stop_pct', 8)

        # Calculate new potential stoploss (current price - trailing percentage)
        potential_stoploss = current_price * (1 - (trailing_stop_pct / 100))

        # Log debug info
        logging.info(f"TRAILING SL DEBUG | symbol: {symbol} | entry_price: {entry_price} | current_price: {current_price} | trailing_stop_pct: {trailing_stop_pct} | current_sl: {current_sl} | original_stoploss: {original_stoploss}")

        # For long positions, we want to move the stoploss up as price increases
        logging.info(f"TRAILING SL DEBUG | [LONG] potential_stoploss: {potential_stoploss}")

        # Only update if the new stoploss is higher than both current stoploss and original stoploss
        if potential_stoploss > current_sl and potential_stoploss > original_stoploss:
            old_sl = self.active_trade['stoploss']
            self.active_trade['stoploss'] = round(potential_stoploss, 3)
            self.active_trade['trailing_stoploss'] = round(potential_stoploss, 3)

            logging.info(f"Trailing stoploss updated from {old_sl} to {self.active_trade['stoploss']}")
            return True
        else:
            logging.info(f"TRAILING SL DEBUG | [LONG] No update: potential_stoploss ({potential_stoploss}) <= current_sl ({current_sl}) or original_stoploss ({original_stoploss})")
            return False

    def identify_high_oi_strikes(self):
        """Identify strikes with highest open interest at 9:20 AM using live option chain data"""
        try:
            self.put_breakout_level = None
            self.call_breakout_level = None
            from src.fyers_api_utils import get_nifty_spot_price
            from src.nse_data_new import get_nifty_option_chain
            spot_price = get_nifty_spot_price()
            logging.info(f"Current Nifty spot price: {spot_price}")
            atm_strike = round(spot_price / 100) * 100
            max_distance = self.max_strike_distance
            min_premium = self.min_premium_threshold
            # --- PUT LEG ---
            put_found = False
            for expiry_idx in range(3):
                option_chain = get_nifty_option_chain(expiry_idx)
                if option_chain is None or option_chain.empty:
                    continue
                put_chain = option_chain[(option_chain['option_type'] == 'PE') & (option_chain['strikePrice'] >= atm_strike - max_distance) & (option_chain['strikePrice'] <= atm_strike + max_distance)]
                if not put_chain.empty:
                    put_oi_sorted = put_chain.sort_values('openInterest', ascending=False)
                    for _, row in put_oi_sorted.iterrows():
                        strike_premium = float(row['lastPrice'])
                        if strike_premium >= min_premium:
                            self.highest_put_oi_strike = int(row['strikePrice'])
                            self.put_premium_at_9_20 = strike_premium
                            self.highest_put_oi_symbol = row['symbol']
                            self.put_breakout_level = round(strike_premium * 1.10, 1)
                            self.put_expiry_idx = expiry_idx
                            put_found = True
                            break
                if put_found:
                    break
            # --- CALL LEG ---
            call_found = False
            for expiry_idx in range(3):
                option_chain = get_nifty_option_chain(expiry_idx)
                if option_chain is None or option_chain.empty:
                    continue
                call_chain = option_chain[(option_chain['option_type'] == 'CE') & (option_chain['strikePrice'] >= atm_strike - max_distance) & (option_chain['strikePrice'] <= atm_strike + max_distance)]
                if not call_chain.empty:
                    call_oi_sorted = call_chain.sort_values('openInterest', ascending=False)
                    for _, row in call_oi_sorted.iterrows():
                        strike_premium = float(row['lastPrice'])
                        if strike_premium >= min_premium:
                            self.highest_call_oi_strike = int(row['strikePrice'])
                            self.call_premium_at_9_20 = strike_premium
                            self.highest_call_oi_symbol = row['symbol']
                            self.call_breakout_level = round(strike_premium * 1.10, 1)
                            self.call_expiry_idx = expiry_idx
                            call_found = True
                            break
                if call_found:
                    break
            logging.info(f"Selected strikes - PUT: {self.highest_put_oi_strike} (Premium: {self.put_premium_at_9_20}, Breakout: {self.put_breakout_level}, Expiry: {self.put_expiry_idx})")
            logging.info(f"Selected strikes - CALL: {self.highest_call_oi_strike} (Premium: {self.call_premium_at_9_20}, Breakout: {self.call_breakout_level}, Expiry: {self.call_expiry_idx})")
            return put_found or call_found
        except Exception as e:
            logging.error(f"Error identifying high OI strikes: {str(e)}")
            self.put_breakout_level = None
            self.call_breakout_level = None
            return False

    # Other essential method skeletons
    def process_exit(self, exit_reason="manual", exit_price=None):
        """Process exit consistently for all exit types (stoploss, target, time, market close)"""
        if not self.active_trade:
            logging.warning("No active trade to exit")
            return False
        symbol = self.active_trade.get('symbol')
        entry_price = self.active_trade.get('entry_price')
        exit_time_actual = datetime.now(pytz.timezone('Asia/Kolkata'))
        quantity = self.active_trade.get('quantity')
        # If exit_price is None (e.g., time-based exit), use last known price
        if exit_price is None:
            exit_price = self.live_prices.get(symbol) or self.active_trade.get('last_known_price') or entry_price
            logging.info(f"No explicit exit price provided. Using last known price for exit: {exit_price}")
        # Always define trailing_sl before use
        trailing_sl = self.active_trade.get('stoploss', '')
        # Calculate brokerage/charges
        brokerage, charges_breakdown = self.calculate_fyers_option_charges(entry_price, exit_price, quantity, state='maharashtra')
        gross_pnl = (exit_price - entry_price) * quantity if exit_price is not None else 0
        net_pnl = gross_pnl - brokerage
        # Calculate max up/down
        max_up = self.active_trade.get('max_up', '')
        max_down = self.active_trade.get('max_down', '')
        max_up_pct = self.active_trade.get('max_up_pct', '')
        max_down_pct = self.active_trade.get('max_down_pct', '')
        # Update trade record in history
        idx = self.active_trade.get('trade_record_idx')
        if idx is not None and idx < len(self.trade_history):
            self.trade_history[idx].update({
                'Exit DateTime': exit_time_actual.strftime('%Y-%m-%d %H:%M:%S'),
                'Exit Price': exit_price,
                'P&L': round(net_pnl, 2),
                '% Gain/Loss': round((net_pnl / (entry_price * quantity)) * 100, 2) if entry_price and quantity else '',
                'Trailing SL': trailing_sl,
                'max up': round(max_up, 2) if isinstance(max_up, (int, float)) else '',
                'max down': round(max_down, 2) if isinstance(max_down, (int, float)) else '',
                'max up %': round(max_up_pct, 2) if isinstance(max_up_pct, (int, float)) else '',
                'max down %': round(max_down_pct, 2) if isinstance(max_down_pct, (int, float)) else '',
                'Brokerage': brokerage,
            })
        logging.info(f"Exiting trade: {symbol} | Reason: {exit_reason} | Exit Price: {exit_price}")
        logging.info(f"TRADE_EXIT | Symbol: {symbol} | Entry: {entry_price} | Exit: {exit_price} | Quantity: {quantity} | P&L: {net_pnl:.2f} ({(net_pnl / (entry_price * quantity)) * 100 if entry_price and quantity else 0:.2f}%) | MaxUP: {self.active_trade.get('max_up', 0):.2f} | MaxDN: {self.active_trade.get('max_down', 0):.2f} | Trailing SL: {self.active_trade.get('stoploss', 0)} | Exit Time: {exit_time_actual.strftime('%Y-%m-%d %H:%M:%S')} | Reason: {exit_reason}")
        self.active_trade['exit_reason'] = exit_reason
        self.active_trade['exit_price'] = exit_price
        self.active_trade['exit_time_actual'] = exit_time_actual
        try:
            self.save_trade_history()
            logging.info("Trade history saved to file after exit.")
        except Exception as e:
            logging.error(f"Error saving trade history after exit: {str(e)}")
        self.active_trade = {}
        self.stop_price_monitoring()
        return True

    def run_diagnostic(self):
        """Run a self-diagnostic check to verify key components are functioning"""
        # Implementation would go here
        pass

    def save_trade_history(self):
        """Save trade history to both CSV and Excel files with proper error handling and column order"""
        import pandas as pd
        from datetime import date
        try:
            # Define required columns in order
            columns = [
                'Entry DateTime', 'Index', 'Symbol', 'Direction', 'Entry Price',
                'Exit DateTime', 'Exit Price', 'Stop Loss', 'Target', 'Trailing SL',
                'Quantity', 'Brokerage', 'P&L', 'Margin Required', '% Gain/Loss',
                'max up', 'max down', 'max up %', 'max down %'
            ]
            df = pd.DataFrame(self.trade_history)
            for col in columns:
                if col not in df.columns:
                    df[col] = ''
            df = df[columns]  # Ensure column order
            # Save to CSV
            df.to_csv('logs/trade_history.csv', index=False)
            # Save to Excel with today's date
            today = date.today().strftime('%Y%m%d')
            excel_path = f'logs/trade_history_{today}.xlsx'
            with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
                df.to_excel(writer, index=False)
            logging.info(f"Trade history saved to CSV and Excel: {excel_path}")
        except Exception as e:
            logging.error(f"Error saving trade history: {str(e)}")

    def update_aggregate_stats(self):
        """Update aggregate statistics file with new trade data"""
        # Implementation would go here
        return datetime.now()

    def wait_for_market_open(self):
        """Wait for market to open (09:15) and then for 9:20 before running OI analysis and the rest of the strategy"""
        try:
            ist_now = datetime.now(pytz.timezone('Asia/Kolkata'))
            current_time = ist_now.time()
            market_open_time = datetime.strptime("09:15", "%H:%M").time()
            analysis_time = datetime.strptime("09:20", "%H:%M").time()
            # Wait for market open (09:15)
            while current_time < market_open_time:
                mins, secs = divmod((datetime.combine(ist_now.date(), market_open_time) - datetime.combine(ist_now.date(), current_time)).total_seconds(), 60)
                logging.info(f"Market not open yet. Waiting... Current time: {current_time.strftime('%H:%M:%S')}, Market opens in: {int(mins)}m {int(secs)}s")
                time.sleep(10)
                ist_now = datetime.now(pytz.timezone('Asia/Kolkata'))
                current_time = ist_now.time()
            logging.info("Market is now open. Waiting for 9:20 to perform OI analysis...")
            # Wait for 9:20
            while current_time < analysis_time:
                mins, secs = divmod((datetime.combine(ist_now.date(), analysis_time) - datetime.combine(ist_now.date(), current_time)).total_seconds(), 60)
                logging.info(f"Waiting for 9:20... Current time: {current_time.strftime('%H:%M:%S')}, OI analysis in: {int(mins)}m {int(secs)}s")
                time.sleep(10)
                ist_now = datetime.now(pytz.timezone('Asia/Kolkata'))
                current_time = ist_now.time()
            logging.info("It's 9:20 or later. Running strategy and OI analysis...")
            return self.run_strategy(force_analysis=True)
        except Exception as e:
            logging.error(f"Error in wait_for_market_open: {str(e)}")
            logging.error(traceback.format_exc())
            return {"success": False, "error": str(e)}

    def clear_logs(self):
        """Clear log file for a fresh start to the trading day"""
        try:
            log_file = 'logs/strategy.log'
            if os.path.exists(log_file):
                # Keep existing logs by backing up current log file
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_file = f'logs/strategy_{timestamp}.log.bak'
                
                # Copy to backup before clearing
                if os.path.getsize(log_file) > 0:
                    with open(log_file, 'r') as src, open(backup_file, 'w') as dst:
                        dst.write(src.read())
                    logging.info(f"Log file backed up to {backup_file}")
                    
                # Clear the current log file
                with open(log_file, 'w') as f:
                    f.write(f"Log file cleared on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                logging.info("Log file has been cleared for new trading day")
                return True
            return False
        except Exception as e:
            logging.error(f"Error clearing logs: {str(e)}")
            return False
        
    def initialize_day(self):
        """Initialize strategy for the day including setting up necessary state"""
        try:
            # Clear logs for a fresh start
            self.clear_logs()
            
            logging.info("Initializing strategy for the day")
            # Reset daily state variables
            self.trade_taken_today = False
            self.market_closed = False
            self.put_breakout_level = 0
            self.call_breakout_level = 0
            self.highest_put_oi_strike = 0
            self.highest_call_oi_strike = 0
            
            # Clear any active trades from previous day
            self.active_trade = {}
            
            # --- WebSocket subscription for all relevant symbols ---
            # Remove index subscription: only subscribe to options needed for breakout monitoring
            symbols = []
            if hasattr(self, 'highest_put_oi_symbol') and self.highest_put_oi_symbol:
                symbols.append(self.highest_put_oi_symbol)
            if hasattr(self, 'highest_call_oi_symbol') and self.highest_call_oi_symbol:
                symbols.append(self.highest_call_oi_symbol)
            if self.active_trade and 'symbol' in self.active_trade:
                trade_symbol = self.active_trade['symbol']
                if trade_symbol and trade_symbol not in symbols:
                    symbols.append(trade_symbol)
            logging.info(f"Subscribing to symbols: {symbols}")
            self.data_socket = enhanced_start_market_data_websocket(
                symbols=symbols,
                callback_handler=self.ws_price_update
            )
            logging.info(f"WebSocket subscription started for symbols: {symbols}")
            logging.info("Strategy initialization complete")
            return True
        except Exception as e:
            logging.error(f"Error initializing strategy for the day: {str(e)}")
            logging.error(traceback.format_exc())
            return False

    def generate_daily_report(self):
        """Generate a summary report of the day's trading activity"""
        # Implementation would go here
        pass
        
    def run_strategy(self, force_analysis=False):
        """
        Main method to run the strategy logic
        
        Args:
            force_analysis (bool): Whether to force OI analysis regardless of time constraints
        
        Returns:
            dict: Result of strategy execution with success status and message
        """
        try:
            logging.info("Running Open Interest Option Buying Strategy")
            # Get current time in IST
            ist_now = datetime.now(pytz.timezone('Asia/Kolkata'))
            current_time = ist_now.time()
            market_open_time = datetime.strptime("09:15", "%H:%M").time()
            market_close_time = datetime.strptime("15:30", "%H:%M").time()
            # Check if market is closed
            if self.market_closed or current_time >= market_close_time:
                logging.info("Market is closed. Skipping strategy execution.")
                return {"success": False, "message": "Market closed"}
            # Check if today is a weekday
            if ist_now.weekday() > 4:
                logging.info("Today is weekend. Market closed.")
                return {"success": False, "message": "Weekend"}
            # Check if trade already taken today
            if self.trade_taken_today and not force_analysis:
                logging.info("Trade already taken today. Skipping strategy execution.")
                return {"success": True, "message": "Trade already taken today"}
            # Wait for market open if needed
            if current_time < market_open_time:
                logging.info("Market not open yet. Waiting for market open...")
                return self.wait_for_market_open()
            # Step 1: OI analysis at/after 9:20
            analysis_time = datetime.strptime("09:20", "%H:%M").time()
            if force_analysis or (current_time >= analysis_time):
                logging.info("Performing OI analysis...")
                oi_result = self.identify_high_oi_strikes()
                if not oi_result:
                    logging.error("OI analysis failed. Exiting strategy run.")
                    return {"success": False, "message": "OI analysis failed"}
                logging.info(f"Breakout levels: PUT={self.put_breakout_level}, CALL={self.call_breakout_level}")
            # Step 2: Monitor for breakouts and execute trades
            if self.highest_put_oi_strike or self.highest_call_oi_strike:
                if not self.active_trade and not self.trade_taken_today:
                    self.monitor_for_breakout()
                elif self.trade_taken_today and not self.active_trade:
                    logging.info("Daily trade limit: Trade already taken today. Skipping breakout monitoring.")
            # Position management is handled by continuous_position_monitor thread
            logging.info("Strategy execution completed successfully")
            return {"success": True, "message": "Strategy executed successfully"}
        except Exception as e:
            logging.error(f"Error in run_strategy: {str(e)}")
            logging.error(traceback.format_exc())
            return {"success": False, "error": str(e)}
            
    def unsubscribe_non_triggered_symbol(self, triggered_symbol, all_symbols):
        """Unsubscribe from the symbol(s) where trade was not triggered."""
        non_triggered = [s for s in all_symbols if s != triggered_symbol]
        # Assuming your data_socket has an unsubscribe method
        if hasattr(self.data_socket, 'unsubscribe'):
            for s in non_triggered:
                self.data_socket.unsubscribe(s)
                logging.info(f"Unsubscribed from {s} after trade triggered for {triggered_symbol}")
        else:
            logging.warning("WebSocket unsubscribe method not available. Manual unsubscribe required.")

    def retry_websocket_connection(self, symbols, max_retries=3, delay=5):
        """Retry websocket connection if it fails."""
        for attempt in range(1, max_retries + 1):
            try:
                self.data_socket = enhanced_start_market_data_websocket(
                    symbols=symbols,
                    callback_handler=self.ws_price_update
                )
                logging.info(f"WebSocket connection established on attempt {attempt} for symbols: {symbols}")
                return True
            except Exception as e:
                logging.error(f"WebSocket connection attempt {attempt} failed: {str(e)}")
                time.sleep(delay)
        logging.error(f"All {max_retries} websocket connection attempts failed for symbols: {symbols}")
        return False

    def monitor_for_breakout(self):
        """Continuously monitor both CE and PE option premiums for breakout using websocket for real-time data"""
        try:
            logging.info("Monitoring for breakout on both CE and PE...")
            symbols_to_monitor = []
            breakout_levels = {}
            if self.put_breakout_level and self.highest_put_oi_symbol:
                symbols_to_monitor.append(self.highest_put_oi_symbol)
                breakout_levels[self.highest_put_oi_symbol] = self.put_breakout_level
            if self.call_breakout_level and self.highest_call_oi_symbol:
                symbols_to_monitor.append(self.highest_call_oi_symbol)
                breakout_levels[self.highest_call_oi_symbol] = self.call_breakout_level
            if not symbols_to_monitor:
                logging.info("No valid option symbols to monitor for breakout.")
                return
            logging.info(f"Subscribing to both option symbols for breakout monitoring: {symbols_to_monitor}")
            if not self.retry_websocket_connection(symbols_to_monitor):
                logging.error("Could not establish websocket connection after retries. Aborting breakout monitoring.")
                return
            logging.info(f"WebSocket subscription started for symbols: {symbols_to_monitor}")
            while True:
                for symbol in symbols_to_monitor:
                    price = self.live_prices.get(symbol)
                    breakout_level = breakout_levels[symbol]
                    logging.info(f"MONITOR: {symbol} {price} (Breakout: {breakout_level})")
                    if price is not None:
                        if price >= breakout_level:
                            logging.info(f"BREAKOUT DETECTED: {symbol} at premium {price}")
                            self.execute_trade(symbol, "BUY", price)
                            self.unsubscribe_non_triggered_symbol(symbol, symbols_to_monitor)
                            return
                time.sleep(2)
        except Exception as e:
            logging.error(f"Error monitoring for breakout: {str(e)}")
            return None

    def execute_trade(self, symbol, side, entry_price):
        """Execute the option trade with correct lot size for Nifty options"""
        try:
            qty = 75  # Nifty lot size (update if changed by exchange)
            notional_value = entry_price * qty
            if entry_price < self.min_premium_threshold:
                logging.warning(f"Trade rejected: Premium value ({entry_price}) is below threshold ({self.min_premium_threshold})")
                return None
            if self.paper_trading:
                logging.info(f"PAPER TRADING MODE - Symbol: {symbol}, Price: {entry_price}")
            else:
                logging.info(f"LIVE TRADING - Symbol: {symbol}, Price: {entry_price}")
            logging.info(f"Trade Size: {qty} lots, Notional Value: {notional_value}")
            order_response = None
            if self.paper_trading:
                order_response = {'s': 'ok', 'id': f'PAPER-{int(time.time())}'}
                logging.info(f"Paper trade simulated: {symbol} {side} {qty}")
            else:
                from src.fyers_api_utils import place_market_order
                order_response = place_market_order(self.fyers, symbol, qty, side)
            if order_response and order_response.get('s') == 'ok':
                self.order_id = order_response.get('id')
                if not self.entry_time:
                    self.entry_time = datetime.now(pytz.timezone('Asia/Kolkata'))
                exit_time = self.entry_time + timedelta(minutes=30)
                config = self.config or {}
                stoploss_pct = config.get('strategy', {}).get('stoploss_pct', 20)
                risk_reward_ratio = config.get('strategy', {}).get('risk_reward_ratio', 2)
                stoploss_factor = 1 - (stoploss_pct / 100)
                stoploss_price = round(entry_price * stoploss_factor, 1)
                risk_amount = entry_price - stoploss_price
                target_gain = risk_amount * risk_reward_ratio
                target_price = round(entry_price + target_gain, 1)
                # Determine index and direction
                index = 'NIFTY'  # or derive from symbol if needed
                direction = 'BUY' if side.upper() == 'BUY' else 'SELL'
                margin_required = entry_price * qty
                # Prepare trade record with all required fields
                trade_record = {
                    'Entry DateTime': self.entry_time.strftime('%Y-%m-%d %H:%M:%S'),
                    'Index': index,
                    'Symbol': symbol,
                    'Direction': direction,
                    'Entry Price': entry_price,
                    'Exit DateTime': '',
                    'Exit Price': '',
                    'Stop Loss': stoploss_price,
                    'Target': target_price,
                    'Trailing SL': '',
                    'Quantity': qty,
                    'Brokerage': '',
                    'P&L': '',
                    'Margin Required': margin_required,
                    '% Gain/Loss': '',
                    'max up': '',
                    'max down': '',
                    'max up %': '',
                    'max down %': '',
                }
                self.active_trade = {
                    'symbol': symbol,
                    'quantity': qty,
                    'entry_price': entry_price,
                    'entry_time': self.entry_time,
                    'stoploss': stoploss_price,
                    'target': target_price,
                    'exit_time': exit_time,
                    'paper_trade': self.paper_trading,
                    'trade_record_idx': len(self.trade_history),  # Track index for update on exit
                }
                self.trade_taken_today = True
                logging.info("Daily trade limit: Trade has been taken for today.")
                logging.info(f"=== {'PAPER' if self.paper_trading else 'LIVE'} TRADE EXECUTED ===")
                logging.info(f"Symbol: {symbol}")
                logging.info(f"Entry Price: {entry_price}")
                logging.info(f"Quantity: {qty} lots")
                logging.info(f"Entry Time: {self.entry_time.strftime('%Y-%m-%d %H:%M:%S')}")
                logging.info(f"Stoploss: {self.active_trade['stoploss']}")
                logging.info(f"Target: {self.active_trade['target']}")
                logging.info(f"Exit Time Limit: {self.active_trade['exit_time'].strftime('%Y-%m-%d %H:%M:%S')}")
                logging.info(f"========================")
                logging.info(f"Trade symbol: {symbol}, Expiry index: {self.put_expiry_idx if 'PE' in symbol else self.call_expiry_idx}")
                logging.info(f"Actual premium at trade time: {entry_price}")
                # Append trade record with all required fields
                self.trade_history.append(trade_record)
                try:
                    self.save_trade_history()
                except Exception as e:
                    logging.error(f"Error saving trade history: {str(e)}")
                # --- Ensure traded symbol is subscribed for real-time price updates ---
                symbols_to_subscribe = [symbol]  # Only option symbol, not index
                logging.info(f"(Re)subscribing to traded option symbol for live price updates: {symbols_to_subscribe}")
                self.data_socket = enhanced_start_market_data_websocket(
                    symbols=symbols_to_subscribe,
                    callback_handler=self.ws_price_update
                )
                logging.info(f"WebSocket subscription started for symbol: {symbols_to_subscribe}")
                # After trade execution, close any previous websocket and start a new one for only the traded symbol
                if hasattr(self, 'data_socket') and self.data_socket:
                    if hasattr(self.data_socket, 'close'):
                        self.data_socket.close()
                        logging.info("Closed previous websocket connection after trade execution.")
                    self.data_socket = None
                from src.fyers_api_utils import start_market_data_websocket
                symbols_to_subscribe = [symbol]  # Only option symbol, not index
                logging.info(f"(Re)subscribing to traded option symbol for live price updates: {symbols_to_subscribe}")
                self.data_socket = start_market_data_websocket(
                    symbols=symbols_to_subscribe,
                    callback_handler=self.ws_price_update
                )
                logging.info(f"WebSocket subscription started for symbol: {symbols_to_subscribe}")
                # Start continuous position monitoring
                self.continuous_position_monitor()
            else:
                logging.error(f"Order placement failed: {order_response}")
                return False
        except Exception as e:
            logging.error(f"Error executing trade: {str(e)}")
            return False

    def continuous_position_monitor(self):
        """Continuously monitor the position for adjustments and exits"""
        try:
            if not self.active_trade:
                return
            symbol = self.active_trade.get('symbol')
            qty = self.active_trade.get('quantity')
            entry_price = self.active_trade.get('entry_price')
            target = self.active_trade.get('target')
            paper_trade = self.active_trade.get('paper_trade', True)
            logging.info(f"Starting continuous position monitoring for {symbol}")
            while self.active_trade:
                # Fetch latest price from live_prices
                current_price = self.live_prices.get(symbol) or self.active_trade.get('last_known_price', entry_price)
                if current_price:
                    self.active_trade['last_known_price'] = current_price
                # Always get the latest stoploss value (may be trailed)
                stoploss = self.active_trade.get('stoploss')
                # Log trade update with real price
                self.log_trade_update()
                # Strict exit enforcement: always exit at defined SL/target, not overshot price
                if current_price <= stoploss:
                    logging.info(f"Stoploss hit. Exiting position at defined stoploss: {stoploss}")
                    self.process_exit(exit_reason="stoploss", exit_price=stoploss)
                    break
                elif current_price >= target:
                    logging.info(f"Target hit. Exiting position at defined target: {target}")
                    self.process_exit(exit_reason="target", exit_price=target)
                    break
                # Example exit condition: if current time is past exit time, trigger exit
                if datetime.now(pytz.timezone('Asia/Kolkata')) >= self.active_trade.get('exit_time'):
                    logging.info("Exit time reached. Exiting position.")
                    self.process_exit(exit_reason="time")
                    break
                time.sleep(5)  # Check every 5 seconds
            logging.info(f"Stopped monitoring for {symbol}. Trade exited.")
            # Optionally: Unsubscribe from websockets here if implemented
        except Exception as e:
            logging.error(f"Error in continuous_position_monitor: {str(e)}")
            return False

    def log_trade_update(self):
        """Log trade update and monitoring info after entry, including P&L, max up/down, trailing SL"""
        if not self.active_trade:
            return
        symbol = self.active_trade.get('symbol')
        entry_price = self.active_trade.get('entry_price')
        stoploss = self.active_trade.get('stoploss')
        target = self.active_trade.get('target')
        quantity = self.active_trade.get('quantity')
        entry_time = self.active_trade.get('entry_time')
        # Fetch live price if available
        current_price = self.live_prices.get(symbol) or self.active_trade.get('last_known_price', entry_price)
        # Calculate P&L
        pnl = (current_price - entry_price) * quantity
        pnl_pct = ((current_price - entry_price) / entry_price * 100) if entry_price else 0
        # Track max up/down
        # max_up: max profit observed (largest positive P&L)
        # max_down: max unrealized loss observed (more negative P&L)
        max_up = self.active_trade.get('max_up', None)
        max_up_pct = self.active_trade.get('max_up_pct', None)
        max_down = self.active_trade.get('max_down', None)
        max_down_pct = self.active_trade.get('max_down_pct', None)
        trailing_sl = stoploss
        # Update max up only if unrealized profit increases
        if pnl > 0 and (max_up is None or pnl > max_up):
            self.active_trade['max_up'] = pnl
            self.active_trade['max_up_pct'] = pnl_pct
        # Update max down only if unrealized loss increases (more negative)
        if pnl < 0 and (max_down is None or pnl < max_down):
            self.active_trade['max_down'] = pnl
            self.active_trade['max_down_pct'] = pnl_pct
        # Trailing SL logic: only trail if profit exceeds 20%
        profit_threshold = 20
        if pnl_pct >= profit_threshold:
            profit_above_20 = current_price - (entry_price * 1.2)
            if profit_above_20 > 0:
                new_sl = entry_price + 0.5 * (current_price - entry_price)
                if new_sl > stoploss:
                    self.active_trade['stoploss'] = round(new_sl, 2)
                    trailing_sl = self.active_trade['stoploss']
                    logging.info(f"Trailing SL updated to {trailing_sl} after exceeding {profit_threshold}% profit.")
        logging.info(f"TRADE_UPDATE | Symbol: {symbol} | Entry: {entry_price} | LTP: {current_price} | SL: {self.active_trade['stoploss']} | Target: {target} | P&L: {pnl:.2f} ({pnl_pct:.2f}%) | MaxUP: {self.active_trade.get('max_up', 0):.2f} ({self.active_trade.get('max_up_pct', 0):.2f}%) | MaxDN: {self.active_trade.get('max_down', 0):.2f} ({self.active_trade.get('max_down_pct', 0):.2f}%) | Trailing SL: {self.active_trade['stoploss']}")
        logging.info(f"TRADE_MONITOR | Monitoring {symbol} for SL/Target/Exit conditions...")
        
    def cleanup(self):
        """Cleanup resources before exiting"""
        try:
            logging.info("Cleaning up strategy resources")
            
            # Save any pending data
            self.save_trade_history()
            
            # Close any connections
            if self.fyers:
                # Close any active websocket connections, etc.
                pass
                
            logging.info("Cleanup completed")
        except Exception as e:
            logging.error(f"Error during cleanup: {str(e)}")
            return False
        return True

    def get_ist_datetime(self):
        """Return current datetime in IST timezone"""
        return datetime.now(pytz.timezone('Asia/Kolkata'))

    def ws_price_update(self, symbol, key, tick_data, *args):
        # DIAGNOSTIC: Log the raw tick_data received from the websocket
        logging.debug(f"WS_PRICE_UPDATE RAW: symbol={symbol}, key={key}, tick_data={tick_data}")
        actual_symbol = tick_data.get('symbol')
        ltp = tick_data.get('ltp')
        if actual_symbol and ltp is not None:
            # Sanity check: For option symbols, ignore LTPs that are clearly index values
            if actual_symbol.endswith(('CE', 'PE')):
                if 0 < ltp < 2000:  # Acceptable range for option prices
                    self.live_prices[actual_symbol] = float(ltp)
                    logging.info(f"LTP UPDATE: {actual_symbol} {ltp}")
                else:
                    logging.warning(f"IGNORED LTP for {actual_symbol}: {ltp} (out of option price range)")
            else:
                self.live_prices[actual_symbol] = float(ltp)
                logging.info(f"LTP UPDATE: {actual_symbol} {ltp}")

    def stop_price_monitoring(self):
        """Stop all price monitoring and unsubscribe from all symbols after trade exit."""
        if hasattr(self, 'data_socket') and self.data_socket:
            if hasattr(self.data_socket, 'unsubscribe_all'):
                self.data_socket.unsubscribe_all()
                logging.info("Unsubscribed from all symbols after trade exit.")
            elif hasattr(self.data_socket, 'unsubscribe') and hasattr(self, 'active_trade'):
                # Unsubscribe from the active trade symbol
                symbol = self.active_trade.get('symbol') if self.active_trade else None
                if symbol:
                    self.data_socket.unsubscribe(symbol)
                    logging.info(f"Unsubscribed from {symbol} after trade exit.")
            self.data_socket = None
        logging.info("Stopped all price monitoring after trade exit.")

    def calculate_fyers_option_charges(self, entry_price, exit_price, quantity, state='maharashtra'):
        """
        Calculate total brokerage and all statutory charges for a round-trip options trade (buy+sell) on Fyers.
        Returns (total_charges, breakdown_dict)
        """
        # Turnover for each leg
        buy_turnover = entry_price * quantity
        sell_turnover = exit_price * quantity
        # Brokerage per leg
        buy_brokerage = min(20, 0.0003 * buy_turnover)
        sell_brokerage = min(20, 0.0003 * sell_turnover)
        # Exchange Transaction Charges (NSE Options): 0.053% on premium turnover (both legs)
        buy_exch_txn = 0.00053 * buy_turnover
        sell_exch_txn = 0.00053 * sell_turnover
        # SEBI Charges: 0.0001% on turnover (both legs)
        buy_sebi = 0.000001 * buy_turnover
        sell_sebi = 0.000001 * sell_turnover
        # GST: 18% on (Brokerage + Exchange Transaction Charges) (both legs)
        buy_gst = 0.18 * (buy_brokerage + buy_exch_txn)
        sell_gst = 0.18 * (sell_brokerage + sell_exch_txn)
        # Stamp Duty (Maharashtra): 0.003% on buy-side turnover only (max ₹300/day)
        stamp_duty = 0.00003 * buy_turnover
        if state.lower() == 'maharashtra':
            stamp_duty = min(stamp_duty, 300)
        # STT: 0.0625% on sell-side turnover (on premium)
        stt = 0.000625 * sell_turnover
        # Round all charges to 2 decimals for reporting
        breakdown = {
            'buy_brokerage': round(buy_brokerage, 2),
            'sell_brokerage': round(sell_brokerage, 2),
            'buy_exch_txn': round(buy_exch_txn, 2),
            'sell_exch_txn': round(sell_exch_txn, 2),
            'buy_sebi': round(buy_sebi, 2),
            'sell_sebi': round(sell_sebi, 2),
            'buy_gst': round(buy_gst, 2),
            'sell_gst': round(sell_gst, 2),
            'stamp_duty': round(stamp_duty, 2),
            'stt': round(stt, 2),
        }
        total = sum(breakdown.values())
        return round(total, 2), breakdown
