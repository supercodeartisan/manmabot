@echo off
cd /d "%~dp0"
REM Elevates Shopping Practice so it can use the admin memory named pipe (avoids WinError 5).
if exist "%~dp0python\python.exe" (
    "%~dp0python\python.exe" "%~dp0debug_tools\elevate_shopping_practice.py"
) else if exist "%~dp0python\pythonw.exe" (
    "%~dp0python\pythonw.exe" "%~dp0debug_tools\elevate_shopping_practice.py"
) else (
    echo Bundled Python not found.
    pause
)
