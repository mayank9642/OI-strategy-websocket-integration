@echo off
REM Batch file to run the OI Strategy dashboard
REM filepath: c:\vs code projects\OI-strategy\run_dashboard.bat

echo Checking for Python environment...

IF NOT EXIST .venv\Scripts\activate.bat (
    echo Python virtual environment not found. Please run setup.py first.
    pause
    exit /b 1
)

echo Activating Python environment...
call .venv\Scripts\activate.bat

echo Installing required packages...
pip install -r requirements.txt

echo Starting OI Strategy Dashboard...
echo Access the dashboard at http://localhost:8050
python src/dashboard.py

pause
