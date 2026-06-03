@echo off
REM Archive all rows in the Notion tasks/ideas DB (trash). Requires --yes.
REM Preview: venv\Scripts\python.exe scripts\notion_purge_productivity_database.py --dry-run

cd /d "%~dp0.."
"%~dp0..\venv\Scripts\python.exe" "%~dp0notion_purge_productivity_database.py" --database tasks --yes --clear-reminder-cache
exit /b %ERRORLEVEL%
