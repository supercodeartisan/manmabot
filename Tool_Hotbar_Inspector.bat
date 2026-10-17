@echo off
cd /d "%~dp0"
REM Tool — hotbar icon / slot inspector
if exist "%~dp0python\pythonw.exe" (
    start "" "%~dp0python\pythonw.exe" "%~dp0Tools\hotbar_tool\run_hotbar_inspector.py"
) else if exist "%~dp0python\python.exe" (
    start "" "%~dp0python\python.exe" "%~dp0Tools\hotbar_tool\run_hotbar_inspector.py"
) else (
    echo Bundled Python not found.
    pause
)
