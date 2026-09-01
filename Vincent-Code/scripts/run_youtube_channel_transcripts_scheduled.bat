@echo off
setlocal EnableExtensions

REM Wrapper para Task Scheduler / ejecución desatendida.
REM Escribe log propio además del latest.log del pipeline.

set "ROOT=%~dp0.."
cd /d "%ROOT%"

set "PY=%ROOT%\venv\Scripts\python.exe"
set "SCRIPT=%ROOT%\scripts\process_youtube_channel.py"
set "REPAIR=%ROOT%\scripts\repair_youtube_transcript_markdown.py"
set "LOGDIR=%ROOT%\logs"

if not exist "%LOGDIR%" mkdir "%LOGDIR%"

set "SCHEDLOG=%LOGDIR%\youtube_scheduler_task.log"

if not exist "%PY%" (
  echo [%date% %time%] ERROR venv no encontrado: %PY%>>"%SCHEDLOG%"
  exit /b 1
)

echo [%date% %time%] START youtube channel transcripts>>"%SCHEDLOG%"
echo ROOT=%ROOT%>>"%SCHEDLOG%"

set "PYTHONIOENCODING=utf-8"

echo [%date% %time%] REPAIR broken markdown (if any)>>"%SCHEDLOG%"
"%PY%" "%REPAIR%" >>"%SCHEDLOG%" 2>&1

echo [%date% %time%] PIPELINE new/pending videos>>"%SCHEDLOG%"
"%PY%" "%SCRIPT%" %* >>"%SCHEDLOG%" 2>&1
set "RC=%ERRORLEVEL%"

echo [%date% %time%] END exit_code=%RC%>>"%SCHEDLOG%"
exit /b %RC%
