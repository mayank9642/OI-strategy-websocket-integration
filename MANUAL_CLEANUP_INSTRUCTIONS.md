# Manual Cleanup Instructions (September 27, 2025)

Since we've successfully fixed the max up/down value tracking issue and updated our documentation, let's clean up the project manually by removing unnecessary files.

## Step 1: Create a Backup Directory

First, create a backup directory to store copies of the files you'll be removing, in case you need them later:

```powershell
# Create a backup directory with timestamp
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backupDir = "cleanup_backups_$timestamp"
New-Item -ItemType Directory -Path $backupDir -Force
```

## Step 2: Files to Remove from Root Directory

Remove these unnecessary test files:

- `test_ce_pe_separation.py`
- `test_data_manager.py`
- `test_fixed_strategy.py`
- `test_fixed_trailing_stoploss.py`
- `test_logging.py`
- `test_logging_fix.py`
- `test_logging_fresh.py`
- `test_logging_now.py`
- `test_multiple_streams.py`
- `test_order_manager.py`
- `test_original_trailing_stoploss.py`
- `test_stoploss_fix.py`
- `test_utility_logging.py`

Remove these utility/fix scripts that are no longer needed:

- `debug_syntax.py`
- `direct_run_strategy.py`
- `enhanced_run_strategy.py`
- `extract_reset_state.py`
- `file_output_test.py`
- `filter_logs.bat`
- `filter_logs.ps1`
- `filter_logs_ps.ps1`
- `filter_now.py`
- `fix_docstring_issue.py`
- `fix_docstring_mixed_issues.py`
- `fix_line_103_specific.py`
- `fix_syntax_line_103_v2.py`
- `fyers_ws_test.py`
- `sanitize_logs.bat`
- `sanitize_logs.ps1`
- `simple_run.py`
- `simple_run_output.txt`
- `update_logging.py`
- `your_strategy_code.py`

Remove these cleanup scripts once the cleanup is complete:

- `cleanup_plan.md`
- `cleanup_plan_updated.md`
- `cleanup_project.ps1`
- `CLEANUP_REPORT.md`
- `cleanup_script.bat`
- `cleanup_script.ps1`
- `REMOVE_THESE_FILES.txt`
- `cleanup_plan_new.md` (this file)
- `new_cleanup_script.ps1`
- `run_new_cleanup.bat`

## Step 3: Files to Remove from src Directory

Remove these backup and temporary files:

- `src\strategy.py.backup_20250730_062107`
- `src\strategy.py.before_trailing_sl_fix`
- `src\strategy.py.complete_fix`
- `src\strategy.py.complete_syntax_fix_1753807474`
- `src\strategy.py.fixed`
- `src\strategy_fixed.py`
- `src\websocket_data_manager.py.bak`

Remove these redundant/duplicate files:

- `src\fixed_strategy.py`
- `src\fixed_strategy_updated.py`
- `src\fyers_api_utils_fixed.py`
- `src\fyers_api_utils_updated.py`
- `src\nse_data_new_fixed.py`
- `src\nse_data_new_updated.py`
- `src\hybrid_market_data.py`

## Step 4: Clean Up __pycache__ Directories

Remove all `__pycache__` directories:

```powershell
Get-ChildItem -Path . -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
```

## Step 5: Log Files Cleanup

Consider removing older log files in the logs directory, especially `.log.bak` files, keeping only recent logs for reference.

## Files to Keep

### Core Implementation
- `src/strategy.py` - Core strategy implementation (now fixed)
- `src/fyers_api_utils.py` - Fyers API utilities
- `src/nse_data_new.py` - NSE data fetching utilities
- `src/order_manager.py` - Order management functionality
- `src/websocket_data_manager.py` - WebSocket data management
- `src/fixed_improved_websocket.py` - Enhanced WebSocket implementation
- `src/symbol_formatter.py` - Option symbol formatting utilities
- `src/main.py` - Main entry point for scheduled running
- `src/dashboard.py` - Dashboard for monitoring trades
- `src/market_utils.py` - Market utilities

### Configuration and Documentation
- `config/` - Directory with configuration files
- `README.md` - Main documentation
- `requirements.txt` - Dependencies
- `docs/` - Documentation directory including our new MAX_UP_DOWN_FIX.md
- `VERSION` - Version tracking file

### Run Scripts
- `run_strategy.py` - Main script to run the strategy
- `run_trade.bat` - Script to run trading strategy
- `wait_for_market_open.bat` - Script to wait for market open
- `wait_for_market_open.ps1` - Script to wait for market open

## Verification Steps

After removing files:

1. Run the main strategy to verify it still works
2. Check that all necessary functionality is still available
3. Update GitHub repository with the cleaned-up version
4. Update documentation if needed

## Note

All removed files should be backed up to the backup directory. If you need to restore any file, you can find it there.
