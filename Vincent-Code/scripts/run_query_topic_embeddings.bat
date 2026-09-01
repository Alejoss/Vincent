@echo off
setlocal
cd /d "%~dp0\.."
set PYTHONIOENCODING=utf-8
if exist "venv\Scripts\python.exe" (
  "venv\Scripts\python.exe" scripts\query_topic_embeddings.py %*
) else (
  python scripts\query_topic_embeddings.py %*
)
endlocal
