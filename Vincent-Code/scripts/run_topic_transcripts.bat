@echo off
REM Transcribir VIDEO/AUDIO de un tema Sophia (Digital Ocean).
REM Uso:
REM   run_topic_transcripts.bat 12
REM   run_topic_transcripts.bat 12 --dry-run
REM   run_topic_transcripts.bat 12 --limit 1
REM   run_topic_transcripts.bat 12 --export-only

setlocal
cd /d "%~dp0\.."
set PYTHONIOENCODING=utf-8

if "%~1"=="" (
  echo Uso: %~nx0 TOPIC_ID [args...]
  echo Ejemplo: %~nx0 12 --dry-run
  exit /b 1
)

set TOPIC_ID=%~1
shift

if exist "venv\Scripts\python.exe" (
  "venv\Scripts\python.exe" scripts\process_topic_transcripts.py --topic-id %TOPIC_ID% %*
) else (
  python scripts\process_topic_transcripts.py --topic-id %TOPIC_ID% %*
)

exit /b %ERRORLEVEL%
