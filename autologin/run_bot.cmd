@echo off
setlocal
cd /d "%~dp0"
where python >nul 2>&1
if errorlevel 1 (
  echo python not found on PATH.
  exit /b 1
)
set PYTHONPATH=%CD%\bot
python bot\bot2.py bot\purple_login.json
echo EXITCODE=%ERRORLEVEL%
endlocal
