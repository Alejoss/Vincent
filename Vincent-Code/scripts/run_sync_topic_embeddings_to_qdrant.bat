@echo off
setlocal
cd /d "%~dp0\.."
set PYTHONIOENCODING=utf-8
if exist "venv\Scripts\python.exe" (
  "venv\Scripts\python.exe" scripts\sync_topic_embeddings_to_qdrant.py %*
) else (
  python scripts\sync_topic_embeddings_to_qdrant.py %*
)
endlocal
