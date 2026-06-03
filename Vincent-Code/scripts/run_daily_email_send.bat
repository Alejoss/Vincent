@echo off
REM Run daily email compose + send. Use with Task Scheduler or copy to Startup folder.
REM Requires .env with NOTION_* and SMTP/EMAIL_* set. Sends at most once per day.
REM Logs: ..\logs\email_daily.log

cd /d "%~dp0.."
if not exist "%~dp0..\logs" mkdir "%~dp0..\logs"
set "LOG=%~dp0..\logs\email_daily.log"
echo. >> "%LOG%"
echo === %date% %time% === >> "%LOG%"
"%~dp0..\venv\Scripts\python.exe" "%~dp0compose_daily_email.py" --send >> "%LOG%" 2>&1
exit /b %ERRORLEVEL%
