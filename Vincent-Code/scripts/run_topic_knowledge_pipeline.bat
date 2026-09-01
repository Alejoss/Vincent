@echo off
setlocal
cd /d "%~dp0\.."
set PYTHONIOENCODING=utf-8
if exist "venv\Scripts\python.exe" (
  "venv\Scripts\python.exe" scripts\run_topic_knowledge_pipeline.py %*
) else (
  python scripts\run_topic_knowledge_pipeline.py %*
)
endlocal
