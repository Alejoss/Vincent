@echo off
setlocal EnableExtensions

cd /d "%~dp0.."
if not exist "logs" mkdir "logs"

set "PY=%~dp0..\venv\Scripts\python.exe"
if not exist "%PY%" (
  echo [ERROR] Python venv not found: "%PY%"
  exit /b 1
)

"%PY%" "%~dp0extract_podcast_mp3.py" %*
exit /b %ERRORLEVEL%
