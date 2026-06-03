@echo off
setlocal EnableExtensions

REM On-demand classifier. Uses Ollama only if LLM_PROVIDER resolves to ollama.

cd /d "%~dp0.."

set "PY=%~dp0..\venv\Scripts\python.exe"
if not exist "%PY%" (
  echo [ERROR] Python venv not found: "%PY%"
  pause
  exit /b 1
)

"%PY%" -c "import sys; sys.path.insert(0,'.'); from src.llm_client import needs_local_ollama; sys.exit(1 if needs_local_ollama() else 0)"
if errorlevel 1 (
  echo [1/2] Checking Ollama server...
  "%PY%" -c "import sys, urllib.request; urllib.request.urlopen('http://127.0.0.1:11434/api/tags', timeout=2); print('Ollama OK')"
  if errorlevel 1 (
    echo [ERROR] Ollama is not running on 127.0.0.1:11434
    echo Start Ollama first, or set OPENAI_API_KEY / LLM_PROVIDER=openai
    pause
    exit /b 1
  )
) else (
  echo [1/2] Using cloud/API LLM — skipping Ollama check.
)

echo [2/2] Running classifier...
"%PY%" "%~dp0classify_slack_input_with_ollama.py" --reclassify
set "EXITCODE=%ERRORLEVEL%"

echo.
if "%EXITCODE%"=="0" (
  echo [OK] Classification finished successfully.
) else (
  echo [ERROR] Classification finished with exit code %EXITCODE%.
)
pause
exit /b %EXITCODE%
