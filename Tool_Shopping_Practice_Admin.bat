@echo off
cd /d "%~dp0"
REM Tool — shopping practice (elevated)
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Start-Process -FilePath '%~dp0python\pythonw.exe' -ArgumentList '"%~dp0Tools\shopping\run_shopping_practice.py"' -Verb RunAs"
