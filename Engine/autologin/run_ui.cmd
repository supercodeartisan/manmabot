@echo off
setlocal
cd /d "%~dp0"
REM System Python (already installed with deps). No local .venv.
where python >nul 2>&1
if errorlevel 1 (
  echo python not found on PATH. Install Python 3.10+ with required packages.
  exit /b 1
)
set PYTHONPATH=%CD%;%CD%\bot
python main.py %*
endlocal
