@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
set "PY=%~dp0..\venv\Scripts\python.exe"
if not exist "%PY%" (
  echo [ERROR] Python venv not found: "%PY%"
  exit /b 1
)
"%PY%" "%~dp0youtube_oauth_login.py" %*
exit /b %ERRORLEVEL%
