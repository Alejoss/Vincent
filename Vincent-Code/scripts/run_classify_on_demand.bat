@echo off
setlocal EnableExtensions

REM On-demand classifier runner (manual double-click).
REM Requires Ollama already running at 127.0.0.1:11434.

cd /d "%~dp0.."

set "PY=%~dp0..\venv\Scripts\python.exe"
if not exist "%PY%" (
  echo [ERROR] Python venv not found: "%PY%"
  pause
  exit /b 1
)

set "MODEL=%OLLAMA_MODEL%"
if "%MODEL%"=="" set "MODEL=dolphin-llama3:8b"

echo [1/2] Checking Ollama server...
"%PY%" -c "import sys, urllib.request; urllib.request.urlopen('http://127.0.0.1:11434/api/tags', timeout=2); print('Ollama OK')"
if errorlevel 1 (
  echo [ERROR] Ollama is not running on 127.0.0.1:11434
  echo Start Ollama first, then run this launcher again.
  pause
  exit /b 1
)

echo [2/2] Running classifier with model "%MODEL%"...
"%PY%" "%~dp0classify_slack_input_with_ollama.py" --model "%MODEL%" --reclassify
set "EXITCODE=%ERRORLEVEL%"

echo.
if "%EXITCODE%"=="0" (
  echo [OK] Classification finished successfully.
) else (
  echo [ERROR] Classification finished with exit code %EXITCODE%.
)
pause
exit /b %EXITCODE%
