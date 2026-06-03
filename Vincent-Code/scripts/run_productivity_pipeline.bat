@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM One-click pipeline:
REM 1) Slack -> Obsidian
REM 2) Classify with Ollama
REM 3) Obsidian -> Notion
REM If this script starts Ollama, it stops that server at the end to free resources.

cd /d "%~dp0.."
if not exist "%~dp0..\logs" mkdir "%~dp0..\logs"
set "LOG=%~dp0..\logs\productivity_pipeline.log"
set "OLLAMA_PID_FILE=%~dp0..\logs\ollama_pipeline_serve.pid"
set "STARTED_OLLAMA=0"
set "EXITCODE=0"

echo.>>"%LOG%"
echo ==================================================>>"%LOG%"
echo Pipeline started: %date% %time%>>"%LOG%"
echo ==================================================>>"%LOG%"

set "PY=%~dp0..\venv\Scripts\python.exe"
if not exist "%PY%" (
  echo [ERROR] Python venv not found: "%PY%"
  echo [ERROR] Python venv not found: "%PY%">>"%LOG%"
  exit /b 1
)

set "MODEL=%OLLAMA_MODEL%"
if "%MODEL%"=="" set "MODEL=dolphin-llama3:8b"

echo [1/4] Checking Ollama server...>>"%LOG%"
"%PY%" -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:11434/api/tags', timeout=2).status==200 else 1)" >nul 2>&1
if errorlevel 1 goto :need_ollama
goto :ollama_ready

:need_ollama
echo Ollama not running. Starting ollama serve...
echo [INFO] Ollama not running. Starting ollama serve...>>"%LOG%"
set "STARTED_OLLAMA=1"
"%PY%" -c "import subprocess,pathlib,sys; p=subprocess.Popen(['ollama','serve'], creationflags=0x08000000, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); pathlib.Path(sys.argv[1]).write_text(str(p.pid), encoding='utf-8')" "%OLLAMA_PID_FILE%"
set /a WAIT_COUNT=0

:wait_ollama
set /a WAIT_COUNT+=1
"%PY%" -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:11434/api/tags', timeout=2).status==200 else 1)" >nul 2>&1
if not errorlevel 1 goto :ollama_ready
if !WAIT_COUNT! GEQ 30 (
  echo [ERROR] Ollama server did not become ready in time.
  echo [ERROR] Ollama server did not become ready in time.>>"%LOG%"
  set "EXITCODE=1"
  goto :cleanup
)
timeout /t 2 /nobreak >nul
goto :wait_ollama

:ollama_ready
echo [OK] Ollama is available.>>"%LOG%"

echo [2/4] Sync Slack -> Obsidian...
echo [2/4] Sync Slack -> Obsidian...>>"%LOG%"
"%PY%" "%~dp0sync_slack_inbox_to_obsidian.py" --days 3 >>"%LOG%" 2>&1
if errorlevel 1 (
  echo [ERROR] Step 2 failed. See log: %LOG%
  echo [ERROR] Step 2 failed.>>"%LOG%"
  set "EXITCODE=1"
  goto :cleanup
)

echo [3/4] Classify with Ollama (model=%MODEL%)...
echo [3/4] Classify with Ollama (model=%MODEL%)...>>"%LOG%"
"%PY%" "%~dp0classify_slack_input_with_ollama.py" --model "%MODEL%" --reclassify >>"%LOG%" 2>&1
if errorlevel 1 (
  echo [ERROR] Step 3 failed. See log: %LOG%
  echo [ERROR] Step 3 failed.>>"%LOG%"
  set "EXITCODE=1"
  goto :cleanup
)

echo [4/4] Sync Obsidian -> Notion...
echo [4/4] Sync Obsidian -> Notion...>>"%LOG%"
"%PY%" "%~dp0sync_productivity_obsidian_to_notion.py" >>"%LOG%" 2>&1
if errorlevel 1 (
  echo [ERROR] Step 4 failed. See log: %LOG%
  echo [ERROR] Step 4 failed.>>"%LOG%"
  set "EXITCODE=1"
  goto :cleanup
)

echo Pipeline completed successfully.
echo [OK] Pipeline completed successfully.>>"%LOG%"
echo Log: %LOG%

:cleanup
if "!STARTED_OLLAMA!"=="1" (
  if exist "!OLLAMA_PID_FILE!" (
    for /f "usebackq delims=" %%p in ("!OLLAMA_PID_FILE!") do (
      echo Stopping Ollama PID %%p started by this pipeline...
      echo [INFO] Stopping Ollama PID %%p>>"%LOG%"
      taskkill /PID %%p /F >>"%LOG%" 2>&1
    )
    del "!OLLAMA_PID_FILE!" >nul 2>&1
  )
)
exit /b !EXITCODE!
