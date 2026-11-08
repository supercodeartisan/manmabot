@echo off
cd /d "%~dp0"
REM Click the 8x4 bag slots and scroll arrows on a client screenshot.
if exist "%~dp0python\pythonw.exe" (
    start "" "%~dp0python\pythonw.exe" "%~dp0Tools\supply_grid\run_grid_calibrator.py"
) else if exist "%~dp0python\python.exe" (
    start "" "%~dp0python\python.exe" "%~dp0Tools\supply_grid\run_grid_calibrator.py"
) else (
    echo Bundled Python not found.
    pause
)
