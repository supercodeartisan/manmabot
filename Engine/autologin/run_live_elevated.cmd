@echo off
setlocal
cd /d "%~dp0"
where python >nul 2>&1
if errorlevel 1 (
  echo python not found on PATH.
  exit /b 1
)
echo LIVE_ELEVATED_START %DATE% %TIME%> "bot\live_elevated_console.log"
set PYTHONPATH=%CD%\bot
python scripts\live_pipeline_test.py --seconds 480 --cfg bot\purple_login.json >> "bot\live_elevated_console.log" 2>&1
echo EXITCODE=%ERRORLEVEL%>> "bot\live_elevated_console.log"
endlocal
