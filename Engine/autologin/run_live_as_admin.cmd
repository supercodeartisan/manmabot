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
  echo Requesting Administrator ...
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs -WorkingDirectory '%~dp0'"
  exit /b 0
)
call "%~dp0run_live_elevated.cmd"
endlocal
