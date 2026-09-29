@echo off
cd /d "%~dp0"
if exist "%~dp0python\pythonw.exe" (
    start "" "%~dp0python\pythonw.exe" "%~dp0debug_tools\run_shopping_practice.py"
) else if exist "%~dp0python\python.exe" (
    start "" "%~dp0python\python.exe" "%~dp0debug_tools\run_shopping_practice.py"
) else (
    echo Bundled Python not found. Use: python\python.exe debug_tools\run_shopping_practice.py
    pause
)
