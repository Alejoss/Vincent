# PowerShell script to run the transcript pipeline
# Alternative to batch script for PowerShell users

# Change to the script's directory
Set-Location $PSScriptRoot

# Activate virtual environment
& ".\venv\Scripts\Activate.ps1"

# Run the pipeline
python main.py

# Deactivate virtual environment
deactivate

# Check exit code
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Pipeline completed with errors. Check logs directory for details." -ForegroundColor Red
    Read-Host "Press Enter to exit"
}

