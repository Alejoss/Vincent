@echo off
setlocal
cd /d "%~dp0\.."
set PYTHONIOENCODING=utf-8
if exist "venv\Scripts\python.exe" (
  "venv\Scripts\python.exe" scripts\sync_topic_embedding_status_to_notion.py %*
) else (
  python scripts\sync_topic_embedding_status_to_notion.py %*
)
endlocal
