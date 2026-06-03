@echo off
REM Slack DM -> Obsidian (0_Diario_productividad/Input). Use with Task Scheduler.
REM Requires .env with SLACK_BOT_TOKEN, SLACK_DM_CHANNEL_ID, OBSIDIAN_VAULT_PATH.
REM Optional: SLACK_WORKSPACE_DOMAIN, SLACK_INPUT_OBSIDIAN_REL
REM Logs: ..\logs\slack_inbox_sync.log

cd /d "%~dp0.."
if not exist "%~dp0..\logs" mkdir "%~dp0..\logs"
set "LOG=%~dp0..\logs\slack_inbox_sync.log"
echo. >> "%LOG%"
echo === %date% %time% === >> "%LOG%"
"%~dp0..\venv\Scripts\python.exe" "%~dp0sync_slack_inbox_to_obsidian.py" --days 3 >> "%LOG%" 2>&1
exit /b %ERRORLEVEL%
