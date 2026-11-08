@echo off
setlocal
cd /d "%~dp0"
if not exist ".env" (
  echo Owner configuration is missing. Prepare the AZT installation first.
  exit /b 1
)
if not exist "server\gold_ai_server.db" (
  echo Owner database is missing. Prepare the AZT installation first.
  exit /b 1
)
if not exist "AZT_Admin.exe" (
  echo AZT_Admin.exe is missing from the owner installation.
  exit /b 1
)
set "GOLD_AI_HOME=%CD%"
set "GOLD_AI_PROJECT_ROOT=%CD%"
set "GOLD_AI_STATE_DIR=%CD%\server"
set "GOLD_AI_DB_PATH=%CD%\server\gold_ai_server.db"
set "AZT_TELEGRAM_SOURCE_ROOT=%CD%"
if exist ".venv\Scripts\python.exe" set "AZT_EXTERNAL_TELEGRAM=true"
start "" "%CD%\AZT_Admin.exe"
