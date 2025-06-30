from fyers_apiv3 import fyersModel
from fyers_apiv3.FyersWebsocket import data_ws, order_ws
import logging
import datetime
import time
import pandas as pd
from src.config import load_config
from src.token_helper import ensure_valid_token

def get_fyers_client(check_token=True):
    """
    Create and return authenticated Fyers API client
    
    Args:
        check_token (bool): If True, verify and refresh token if needed
        
    Returns:
        FyersModel: Authenticated Fyers client
    """
    try:
        if check_token:
            access_token = ensure_valid_token()
        else:
            config = load_config()
            access_token = config['fyers']['access_token']
        
        client_id = load_config()['fyers']['client_id']
        
        fyers = fyersModel.FyersModel(client_id=client_id, token=access_token, log_path="logs/")
        
        # Test connection with profile API
        profile_response = fyers.get_profile()
        if profile_response.get('s') == 'ok':
            logging.info(f"Successfully authenticated with Fyers API for user: {profile_response.get('data', {}).get('name')}")
            return fyers
        else:
            logging.error(f"Fyers authentication failed: {profile_response}")
            return None
    except Exception as e:
        logging.error(f"Error creating Fyers client: {str(e)}")
        return None

def place_market_order(fyers, symbol, qty, side):
    """
    Place a market order using Fyers API
    
    Args:
        fyers: Authenticated Fyers client
        symbol: Trading symbol (e.g., "NSE:NIFTY2560619500CE")
        qty: Quantity to trade
        side: "BUY" or "SELL"
        
    Returns:
        Order response from Fyers API
    """
    try:
        order_data = {
            "symbol": symbol,
            "qty": qty,
            "type": 2,  # 2 = Market order
            "side": 1 if side == "BUY" else -1,  # 1 = Buy, -1 = Sell
            "productType": "INTRADAY",
            "validity": "DAY",
            "offlineOrder": False,
            "stopPrice": 0,
            "limitPrice": 0
        }
        
        response = fyers.place_order(data=order_data)
        logging.info(f"Order placed: {symbol} {side} {qty} - Response: {response}")
        return response
    except Exception as e:
        logging.error(f"Error placing order: {str(e)}")
        return None

def modify_order(fyers, order_id, price=None, stop_price=None):
    """Modify an existing order (for SL/target modifications)"""
    try:
        modify_data = {
            "id": order_id
        }
        
        if price is not None:
            modify_data["limitPrice"] = price
            
        if stop_price is not None:
            modify_data["stopPrice"] = stop_price
            
        response = fyers.modify_order(data=modify_data)
        logging.info(f"Order modified: {order_id} - Response: {response}")
        return response
    except Exception as e:
        logging.error(f"Error modifying order: {str(e)}")
        return None

def exit_position(fyers, symbol, qty, side):
    """Exit an existing position"""
    try:
        return place_market_order(fyers, symbol, qty, side)
    except Exception as e:
        logging.error(f"Error exiting position: {str(e)}")
        return None

def get_current_positions(fyers):
    """Get current positions"""
    try:
        positions = fyers.positions()
        return positions
    except Exception as e:
        logging.error(f"Error getting positions: {str(e)}")
        return None

def place_limit_order(fyers, symbol, qty, side, limit_price):
    """
    Place a limit order using Fyers API
    
    Args:
        fyers: Authenticated Fyers client
        symbol: Trading symbol (e.g., "NSE:NIFTY2560619500CE")
        qty: Quantity to trade
        side: "BUY" or "SELL"
        limit_price: Limit price for the order
        
    Returns:
        Order response from Fyers API
    """
    try:
        order_data = {
            "symbol": symbol,
            "qty": qty,
            "type": 1,  # 1 = Limit order
            "side": 1 if side == "BUY" else -1,  # 1 = Buy, -1 = Sell
            "productType": "INTRADAY",
            "validity": "DAY",
            "offlineOrder": False,
            "stopPrice": 0,
            "limitPrice": limit_price
        }
        
        response = fyers.place_order(data=order_data)
        logging.info(f"Limit order placed: {symbol} {side} {qty} @ {limit_price} - Response: {response}")
        return response
    except Exception as e:
        logging.error(f"Error placing limit order: {str(e)}")
        return None

def place_sl_order(fyers, symbol, qty, side, trigger_price):
    """
    Place a stop-loss order using Fyers API
    
    Args:
        fyers: Authenticated Fyers client
        symbol: Trading symbol (e.g., "NSE:NIFTY2560619500CE")
        qty: Quantity to trade
        side: "BUY" or "SELL"
        trigger_price: Stop-loss trigger price
        
    Returns:
        Order response from Fyers API
    """
    try:
        order_data = {
            "symbol": symbol,
            "qty": qty,
            "type": 3,  # 3 = Stop order (SL-M)
            "side": 1 if side == "BUY" else -1,
            "productType": "INTRADAY",
            "validity": "DAY",
            "offlineOrder": False, 
            "stopPrice": trigger_price,
            "limitPrice": 0
        }
        
        response = fyers.place_order(data=order_data)
        logging.info(f"SL order placed: {symbol} {side} {qty} @ trigger {trigger_price} - Response: {response}")
        return response
    except Exception as e:
        logging.error(f"Error placing SL order: {str(e)}")
        return None

def place_sl_limit_order(fyers, symbol, qty, side, trigger_price, limit_price):
    """
    Place a stop-loss limit order using Fyers API
    
    Args:
        fyers: Authenticated Fyers client
        symbol: Trading symbol (e.g., "NSE:NIFTY2560619500CE")
        qty: Quantity to trade
        side: "BUY" or "SELL"
        trigger_price: Stop-loss trigger price
        limit_price: Limit price for order execution
        
    Returns:
        Order response from Fyers API
    """
    try:
        order_data = {
            "symbol": symbol,
            "qty": qty,
            "type": 4,  # 4 = Stop limit order (SL-L)
            "side": 1 if side == "BUY" else -1,
            "productType": "INTRADAY",
            "validity": "DAY",
            "offlineOrder": False,
            "stopPrice": trigger_price,
            "limitPrice": limit_price
        }
        
        response = fyers.place_order(data=order_data)
        logging.info(f"SL-L order placed: {symbol} {side} {qty} @ trigger {trigger_price}, limit {limit_price} - Response: {response}")
        return response
    except Exception as e:
        logging.error(f"Error placing SL-L order: {str(e)}")
        return None

def get_order_status(fyers, order_id):
    """Get status of an existing order"""
    try:
        data = {
            "id": order_id
        }
        response = fyers.get_orders(data=data)
        logging.info(f"Order status for {order_id}: {response}")
        return response
    except Exception as e:
        logging.error(f"Error getting order status: {str(e)}")
        return None

def get_historical_data(fyers, symbol, resolution, date_format, range_from, range_to):
    """
    Get historical data for a symbol
    
    Args:
        fyers: Authenticated Fyers client
        symbol: Trading symbol (e.g., "NSE:NIFTY-INDEX")
        resolution: Timeframe resolution (1, 5, 15, 60, 1D, etc.)
        date_format: Date format (1 for epoch)
        range_from: Start date (epoch or datetime format)
        range_to: End date (epoch or datetime format)
        
    Returns:
        DataFrame: Historical data in pandas DataFrame
    """
    try:
        data = {
            "symbol": symbol,
            "resolution": resolution,
            "date_format": date_format,
            "range_from": range_from,
            "range_to": range_to,
            "cont_flag": "1"
        }
        
        response = fyers.get_historical_data(data)
        
        if isinstance(response, dict) and 'candles' in response:
            df = pd.DataFrame(response['candles'], columns=['datetime', 'open', 'high', 'low', 'close', 'volume'])
            if date_format == 1:  # If date is in epoch format
                df['datetime'] = pd.to_datetime(df['datetime'], unit='s')
            return df
        else:
            logging.error(f"Invalid response format: {response}")
            return None
    except Exception as e:
        logging.error(f"Error getting historical data: {str(e)}")
        return None

def get_option_chain(fyers, underlying):
    """
    Get option chain data for an underlying
    
    Args:
        fyers: Authenticated Fyers client
        underlying: Underlying symbol (e.g., "NSE:NIFTY-INDEX")
        
    Returns:
        dict: Option chain data
    """
    try:
        response = fyers.get_option_chain({"symbol": underlying})
        logging.info(f"Option chain fetched for {underlying}")
        return response
    except Exception as e:
        logging.error(f"Error getting option chain: {str(e)}")
        return None

def start_market_data_websocket(symbols, callback_handler=None, data_type="SymbolUpdate", 
                        on_success=None, on_failure=None):
    """
    Start a websocket connection for market data with tick-by-tick updates
    
    Args:
        symbols: List of symbols to subscribe to
        callback_handler: Function to handle data updates (receives symbol, key, value)
        data_type: Type of data to receive (SymbolUpdate, DepthUpdate)
        on_success: Callback function when subscription succeeds
        on_failure: Callback function when subscription fails
        
    Returns:
        WebSocket connection object
    """
    try:
        config = load_config()
        client_id = config['fyers']['client_id']
        access_token = ensure_valid_token()
        
        # Initialize DataFrame with columns for tracking live market data
        # Define expected columns from Fyers API response
        expected_columns = [
            'ltp', 'vol_traded_today', 'last_traded_time', 'exch_feed_time',
            'bid_size', 'ask_size', 'bid_price', 'ask_price', 
            'last_traded_qty', 'tot_buy_qty', 'tot_sell_qty', 'avg_trade_price',
            'low_price', 'high_price', 'open_price', 'prev_close_price', 'symbol'
        ]
        market_data_df = pd.DataFrame(columns=expected_columns)
        market_data_df.set_index('symbol', inplace=True)
        
        # Pre-populate the DataFrame with the symbols we'll be tracking
        for symbol in symbols:
            market_data_df.loc[symbol] = [None] * (len(expected_columns) - 1)
        
        def on_message(ticks):
            # Process tick data and update the DataFrame
            if ticks.get('symbol'):
                symbol = ticks.get('symbol')
                
                # Better logging for option symbol identification
                is_option = "CE" in symbol or "PE" in symbol
                
                # Update all key-value pairs in the DataFrame
                for key, value in ticks.items():
                    if key != 'symbol':  # Skip symbol as it's the index
                        try:
                            market_data_df.loc[symbol, key] = value
                        except Exception as e:
                            logging.warning(f"Failed to update DataFrame for {symbol} - {key}: {e}")
                    
                    # Call the callback function if provided
                    if callback_handler:
                        callback_handler(symbol, key, value, ticks)
                        
                # Log the LTP (Last Traded Price) if available
                if 'ltp' in ticks:
                    if is_option:
                        logging.info(f"WebSocket option tick: {symbol} LTP: {ticks['ltp']}")
                    else:
                        logging.info(f"WebSocket tick: {symbol} LTP: {ticks['ltp']}")
            
        def on_error(error):
            logging.error(f"WebSocket error: {error}")
            
        def on_close(message):
            logging.info(f"WebSocket connection closed: {message}")
            
        def on_subscribe_success(response):
            logging.info(f"WebSocket subscription success: {response}")
            if callable(on_success):
                on_success(response)
        
        def on_subscribe_failure(error_code, message):
            logging.error(f"WebSocket subscription failed: {error_code} - {message}")
            if callable(on_failure):
                on_failure(error_code, message)
        
        def on_open():
            logging.info(f"WebSocket connection opened for {len(symbols)} symbols")
            # Subscribe to symbols (without success/failure callbacks - Fyers API doesn't support these)
            try:
                # Don't pass the on_success/on_failure callbacks - Fyers API doesn't support them
                ws_client.subscribe(symbols=symbols, data_type=data_type)
                logging.info(f"Subscription requested for symbols: {symbols}")
                # Call our success callback manually if provided
                if callable(on_success):
                    on_success({"status": "Subscription requested", "symbols": symbols})
            except Exception as e:
                logging.error(f"Error subscribing to symbols: {str(e)}")
                # Call our failure callback manually if provided
                if callable(on_failure):
                    on_failure("ERROR", str(e))
        
        # Initialize WebSocket with improved reconnection logic
        ws_client = data_ws.FyersDataSocket(
            access_token=f"{client_id}:{access_token}",
            log_path="logs/",
            litemode=False,
            write_to_file=False,
            reconnect=True,
            on_connect=on_open,
            on_close=on_close,
            on_error=on_error,
            on_message=on_message
        )
        
        # Connect to the WebSocket server
        ws_client.connect()
        
        # Attach the DataFrame to the client for access from outside
        ws_client.market_data = market_data_df
        
        # Add a proper close method if not present
        if not hasattr(ws_client, 'close_connection'):
            def close_connection():
                try:
                    logging.info("Closing websocket connection...")
                    ws_client.terminate()
                    logging.info("Websocket connection terminated")
                except Exception as e:
                    logging.error(f"Error terminating websocket: {str(e)}")
            
            ws_client.close_connection = close_connection
        
        return ws_client
    except Exception as e:
        logging.error(f"Error starting market data WebSocket: {str(e)}")
        return None

def get_nifty_spot_price():
    """
    Fetch the current Nifty spot price using the Fyers quotes API.
    
    Returns:
        float: The current Nifty spot price, or 0 if unavailable.
    """
    try:
        fyers = get_fyers_client()
        if not fyers:
            logging.error("Fyers client not available for spot price fetch.")
            return 0
        data = {"symbols": "NSE:NIFTY50-INDEX"}
        response = fyers.quotes(data=data)
        if response.get('s') == 'ok' and 'd' in response and len(response['d']) > 0:
            spot = response['d'][0].get('v', {}).get('lp', 0)
            logging.info(f"Fetched Nifty spot price from quotes API: {spot}")
            return spot
        else:
            logging.error(f"Failed to fetch Nifty spot price from quotes API: {response}")
            return 0
    except Exception as e:
        logging.error(f"Error fetching Nifty spot price: {str(e)}")
        return 0

def get_nifty_spot_price_direct(fyers):
    """
    Get the current Nifty spot price using direct quotes API
    
    Args:
        fyers: Authenticated Fyers client
        
    Returns:
        float: Nifty spot price or 0 if unavailable
    """
    try:
        if not fyers:
            logging.error("Fyers client is not initialized")
            return 0
            
        # Use Fyers quotes API to get Nifty spot price
        nifty_symbol = "NSE:NIFTY50-INDEX"  # Nifty index symbol
        quotes_response = fyers.quotes({"symbols": nifty_symbol})
        
        if quotes_response.get('s') == 'ok' and 'd' in quotes_response:
            data = quotes_response['d']
            if data and len(data) > 0 and 'v' in data[0]:
                # Extract the last price from the response
                ltp = data[0]['v'].get('lp', 0)
                return float(ltp)
                
        logging.warning(f"Failed to get Nifty spot price: {quotes_response}")
        return 0
    except Exception as e:
        logging.error(f"Error getting Nifty spot price: {str(e)}")
        return 0
    except Exception as e:
        logging.error(f"Error getting Nifty spot price: {str(e)}")
        return 0

def get_ltp(fyers, symbol, websocket_client=None):
    """
    Get the Last Traded Price (LTP) for a symbol
    First tries from websocket data if available, otherwise uses quotes API
    
    Args:
        fyers: Authenticated Fyers client
        symbol: Trading symbol (e.g., "NSE:NIFTY2560619500CE")
        websocket_client: Optional websocket client with market data
        
    Returns:
        float: LTP if available, None otherwise
    """
    try:
        # Try to get price from WebSocket first if available
        if websocket_client and hasattr(websocket_client, 'market_data'):
            if symbol in websocket_client.market_data.index:
                ltp = websocket_client.market_data.loc[symbol, 'ltp']
                if pd.notna(ltp):
                    logging.info(f"LTP from WebSocket for {symbol}: {ltp}")
                    return float(ltp)
        
        # If websocket data is not available or the symbol isn't there, fall back to API
        if not fyers:
            logging.error("Fyers client is not initialized")
            return None
            
        # Use Fyers quotes API to get LTP
        quotes_response = fyers.quotes({"symbols": symbol})
        
        if quotes_response.get('s') == 'ok' and 'd' in quotes_response:
            data = quotes_response['d']
            if data and len(data) > 0 and 'v' in data[0]:
                # Extract the last price from the response
                ltp = data[0]['v'].get('lp', 0)
                logging.info(f"LTP from API for {symbol}: {ltp}")
                return float(ltp)
                
        logging.warning(f"Failed to get LTP for {symbol}: {quotes_response}")
        return None
    except Exception as e:
        logging.error(f"Error getting LTP for {symbol}: {str(e)}")
        return None