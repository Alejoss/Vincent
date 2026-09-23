@echo off
setlocal
cd /d "%~dp0\.."
set PYTHONIOENCODING=utf-8
if exist "venv\Scripts\python.exe" (
  "venv\Scripts\python.exe" scripts\report_topic_embedding_status.py %*
) else (
  python scripts\report_topic_embedding_status.py %*
)
endlocal
