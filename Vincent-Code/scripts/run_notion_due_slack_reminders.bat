@echo off
REM Notion tareas (vencimiento cercano) -> Slack DM. Programador de tareas recomendado (1-2 veces al día).
REM Requiere .env: NOTION_API_TOKEN, SLACK_BOT_TOKEN, SLACK_DM_CHANNEL_ID
REM Requiere: NOTION_TASKS_DATABASE_ID, SLACK_REMINDER_EXCLUDE_STATUS (opcional)
REM Estado dedup: state\notion_slack_reminders_sent.json
REM Logs: ..\logs\notion_due_slack_reminders.log

cd /d "%~dp0.."
if not exist "%~dp0..\logs" mkdir "%~dp0..\logs"
set "LOG=%~dp0..\logs\notion_due_slack_reminders.log"
echo. >> "%LOG%"
echo === %date% %time% === >> "%LOG%"
"%~dp0..\venv\Scripts\python.exe" "%~dp0notion_tasks_due_slack_reminders.py" >> "%LOG%" 2>&1
exit /b %ERRORLEVEL%
