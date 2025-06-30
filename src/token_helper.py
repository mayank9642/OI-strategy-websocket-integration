import datetime
import sys
import os
import logging

# Add the project root directory to Python path for imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    # Try using package import first (when running as module)
    from src.config import load_config
    from src.auth import generate_access_token
except ModuleNotFoundError:
    # Fall back to relative import (when running as script)
    from config import load_config
    from auth import generate_access_token

def is_token_valid():
    """
    Check if the access token is still valid or needs to be refreshed.
    
    Returns:
        bool: True if token is valid, False otherwise
    """
    try:
        config = load_config()
        token_expiry_str = config.get('fyers', {}).get('token_expiry', '')
        
        if not token_expiry_str:
            logging.warning("No token expiry found in config.")
            return False
        
        expiry_time = datetime.datetime.strptime(token_expiry_str, '%Y-%m-%d %H:%M:%S')
        current_time = datetime.datetime.now()
        
        # Add a buffer of 5 minutes to ensure we don't use a token that's about to expire
        buffer_time = datetime.timedelta(minutes=5)
        
        if current_time + buffer_time < expiry_time:
            return True
        else:
            logging.info("Token expired or about to expire.")
            return False
    
    except Exception as e:
        logging.error(f"Error checking token validity: {str(e)}")
        return False

def ensure_valid_token(use_totp=False):
    """
    Check if token is valid, and if not, generate a new one.
    
    Args:
        use_totp (bool): Whether to use TOTP for authentication
        
    Returns:
        str: Valid access token
    """
    if is_token_valid():
        config = load_config()
        return config['fyers']['access_token']
    else:
        logging.info("Generating new access token...")
        return generate_access_token(use_totp)
