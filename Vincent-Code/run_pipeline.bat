@echo off
REM Batch script to run the transcript pipeline
REM This script activates the virtual environment and runs main.py

REM Change to the script's directory
cd /d "%~dp0"

REM Activate virtual environment
call venv\Scripts\activate.bat

REM Run the pipeline
python main.py

REM Deactivate virtual environment (optional, but clean)
call venv\Scripts\deactivate.bat

REM Keep window open if there was an error (for debugging)
if errorlevel 1 (
    echo.
    echo Pipeline completed with errors. Check logs directory for details.
    pause
)

