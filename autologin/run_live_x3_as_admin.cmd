@echo off
setlocal
cd /d "%~dp0"
where python >nul 2>&1
if errorlevel 1 (
  echo python not found on PATH.
  exit /b 1
)

net session >nul 2>&1
if errorlevel 1 (
  echo Requesting Administrator for x3 live test ...
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs -WorkingDirectory '%~dp0'"
  exit /b 0
)

set SUMMARY=%~dp0bot\live_x3_summary.log
echo LIVE_X3_START %DATE% %TIME%> "%SUMMARY%"
set PYTHONPATH=%CD%\bot
for /L %%i in (1,1,3) do (
  echo.>> "%SUMMARY%"
  echo ===== RUN %%i/3 %DATE% %TIME% =====>> "%SUMMARY%"
  echo RUN%%i_START %DATE% %TIME%> "%~dp0bot\live_elevated_console.log"
  python scripts\live_pipeline_test.py --seconds 480 --cfg bot\purple_login.json >> "%~dp0bot\live_elevated_console.log" 2>&1
  echo RUN%%i_EXIT=%ERRORLEVEL%>> "%~dp0bot\live_elevated_console.log"
  echo RUN%%i_EXIT=%ERRORLEVEL%>> "%SUMMARY%"
  findstr /C:"TEST end" /C:"PIPELINE FINISHED" /C:"PIPELINE FAILED" /C:"INGAME" /C:"wake_nudge" /C:"boot_shake" /C:"closing+relaunch" /C:"1936" /C:"816x639" "%~dp0bot\live_elevated_console.log" >> "%SUMMARY%"
  copy /Y "%~dp0bot\live_elevated_console.log" "%~dp0bot\live_run%%i.log" >nul
  timeout /t 8 /nobreak >nul
)
echo.>> "%SUMMARY%"
echo LIVE_X3_DONE %DATE% %TIME%>> "%SUMMARY%"
endlocal
