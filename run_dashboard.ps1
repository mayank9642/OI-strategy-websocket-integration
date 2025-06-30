# PowerShell script to run the OI Strategy dashboard
# filepath: c:\vs code projects\OI-strategy\run_dashboard.ps1

# Ensure the Python environment is activated
if (-not (Test-Path -Path ".venv\Scripts\Activate.ps1")) {
    Write-Host "Python virtual environment not found. Please run setup.py first." -ForegroundColor Red
    Exit 1
}

# Activate the virtual environment
& .\.venv\Scripts\Activate.ps1

# Check if required packages are installed
Write-Host "Checking for required packages..." -ForegroundColor Yellow
pip install -r requirements.txt

# Run the dashboard
Write-Host "Starting OI Strategy Dashboard..." -ForegroundColor Green
Write-Host "Access the dashboard at http://localhost:8050" -ForegroundColor Cyan
python src/dashboard.py

# Keep the window open
Read-Host "Press Enter to exit"
