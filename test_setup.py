# Test script to verify OI-Strategy setup and configuration
import os
import sys
import logging
import traceback

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def test_imports():
    """Test that all required packages are installed and importable"""
    print("\n===== Testing Imports =====")
    required_packages = [
        "fyers_apiv3",
        "pandas",
        "numpy",
        "yaml",
        "requests",
        "schedule"
    ]
    
    all_successful = True
    for package in required_packages:
        try:
            __import__(package)
            print(f"✓ {package} imported successfully")
        except ImportError as e:
            print(f"✗ Failed to import {package}: {str(e)}")
            all_successful = False
    
    return all_successful

def test_directory_structure():
    """Test that all required directories exist"""
    print("\n===== Testing Directory Structure =====")
    required_dirs = [
        "config",
        "logs",
        "src"
    ]
    
    all_exist = True
    for directory in required_dirs:
        if os.path.exists(directory) and os.path.isdir(directory):
            print(f"✓ {directory} directory exists")
        else:
            print(f"✗ {directory} directory does not exist")
            all_exist = False
            
            # Create missing directories
            try:
                os.makedirs(directory, exist_ok=True)
                print(f"  Created {directory} directory")
            except Exception as e:
                print(f"  Failed to create {directory}: {str(e)}")
    
    return all_exist

def test_config():
    """Test that the config file exists and has required fields"""
    print("\n===== Testing Configuration =====")
    config_path = os.path.join("config", "config.yaml")
    
    if not os.path.exists(config_path):
        print(f"✗ Config file does not exist: {config_path}")
        return False
    
    try:
        import yaml
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        required_sections = ["fyers", "strategy", "logging"]
        all_sections_exist = True
        
        for section in required_sections:
            if section in config:
                print(f"✓ Config section exists: {section}")
            else:
                print(f"✗ Missing config section: {section}")
                all_sections_exist = False
        
        # Check for Fyers API credentials
        if "fyers" in config:
            if config["fyers"].get("access_token") and config["fyers"]["access_token"] != "YOUR_ACCESS_TOKEN":
                print("✓ Fyers access token is configured")
            else:
                print("✗ Fyers access token is missing or is placeholder")
        
        return all_sections_exist
    except Exception as e:
        print(f"✗ Error reading config: {str(e)}")
        return False

def test_fyers_connection():
    """Test connection to Fyers API"""
    print("\n===== Testing Fyers API Connection =====")
    try:
        # Import locally to avoid errors if missing
        sys.path.append('.')
        from src.fyers_api_utils import get_fyers_client
        
        fyers = get_fyers_client(check_token=False)  # Don't refresh token
        
        if fyers:
            # Test a simple API call
            profile = fyers.get_profile()
            if profile.get('s') == 'ok':
                print(f"✓ Successfully connected to Fyers API")
                print(f"  User: {profile.get('data', {}).get('name', 'Unknown')}")
                print(f"  Email: {profile.get('data', {}).get('email', 'Unknown')}")
                return True
            else:
                print(f"✗ Fyers API connection failed: {profile}")
                return False
        else:
            print(f"✗ Failed to create Fyers client")
            return False
    except Exception as e:
        print(f"✗ Error testing Fyers connection: {str(e)}")
        traceback.print_exc()
        return False

def main():
    print("Starting OI-Strategy Diagnostic Test")
    print("==================================")
    
    # Run all tests
    imports_ok = test_imports()
    dirs_ok = test_directory_structure()
    config_ok = test_config()
    fyers_ok = test_fyers_connection()
    
    # Summary
    print("\n===== Test Summary =====")
    print(f"Imports: {'✓ PASSED' if imports_ok else '✗ FAILED'}")
    print(f"Directories: {'✓ PASSED' if dirs_ok else '✗ FAILED'}")
    print(f"Configuration: {'✓ PASSED' if config_ok else '✗ FAILED'}")
    print(f"Fyers API: {'✓ PASSED' if fyers_ok else '✗ FAILED'}")
    
    if all([imports_ok, dirs_ok, config_ok, fyers_ok]):
        print("\n✅ All tests passed! The system is ready to run.")
        print("Run the strategy with: python -m src.main")
    else:
        print("\n❌ Some tests failed. Please fix the issues above before running the strategy.")

if __name__ == "__main__":
    main()
