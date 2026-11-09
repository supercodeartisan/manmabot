@echo off
cd /d "%~dp0"
REM Tool — supply drop practice (elevated). Same entry as shopping practice.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Start-Process -FilePath '%~dp0python\pythonw.exe' -ArgumentList '"%~dp0Tools\supply\run_supply_practice.py"' -Verb RunAs"
if errorlevel 1 (
    echo UAC / Start-Process failed.
    pause
    exit /b 1
)
