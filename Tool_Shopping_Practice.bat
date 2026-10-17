@echo off
cd /d "%~dp0"
REM Tool — NPC behavior practice (buy, sell, warehouse, teleporter)
if exist "%~dp0python\pythonw.exe" (
    start "" "%~dp0python\pythonw.exe" "%~dp0Tools\shopping\run_shopping_practice.py"
) else if exist "%~dp0python\python.exe" (
    start "" "%~dp0python\python.exe" "%~dp0Tools\shopping\run_shopping_practice.py"
) else (
    echo Bundled Python not found.
    pause
)
