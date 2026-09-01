@echo off
setlocal
cd /d "%~dp0\.."
set PYTHONIOENCODING=utf-8
if exist "venv\Scripts\python.exe" (
  "venv\Scripts\python.exe" scripts\embed_topic.py %*
) else (
  python scripts\embed_topic.py %*
)
endlocal
