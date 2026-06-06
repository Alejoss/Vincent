@echo off
REM Slack DM -> Notion task updates. Use with Task Scheduler.
REM Requires .env with SLACK_BOT_TOKEN, SLACK_DM_CHANNEL_ID, NOTION_API_TOKEN.
REM Optional: NOTION_TASKS_DATABASE_ID, OBSIDIAN_VAULT_PATH, LLM_PROVIDER, OPENAI_API_KEY.
REM Logs: ..\logs\slack_task_updates.log

cd /d "%~dp0.."
if not exist "%~dp0..\logs" mkdir "%~dp0..\logs"
set "LOG=%~dp0..\logs\slack_task_updates.log"
set "DAYS=%SLACK_TASK_UPDATE_DAYS%"
if "%DAYS%"=="" set "DAYS=3"
echo. >> "%LOG%"
echo === %date% %time% === >> "%LOG%"
"%~dp0..\venv\Scripts\python.exe" "%~dp0update_notion_tasks_from_slack_messages.py" --days %DAYS% %* >> "%LOG%" 2>&1
exit /b %ERRORLEVEL%
