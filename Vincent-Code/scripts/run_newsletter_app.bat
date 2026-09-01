@echo off
cd /d "%~dp0.."
call venv\Scripts\activate.bat 2>nul
if errorlevel 1 (
  echo Activa el venv primero: .\venv\Scripts\Activate.ps1
  exit /b 1
)
set STREAMLIT_BROWSER_GATHER_USAGE_STATS=false
echo Abriendo newsletter en http://localhost:8501 ...
start "" http://localhost:8501
streamlit run scripts\newsletter_app.py
