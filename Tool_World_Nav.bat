@echo off
cd /d "%~dp0"
REM Tool — plan world-nav routes (maps, scroll hubs, NPC teleporters; no movement)
if exist "%~dp0python\pythonw.exe" (
    start "" "%~dp0python\pythonw.exe" "%~dp0Tools\world_nav_probe\run_world_nav.py"
) else if exist "%~dp0python\python.exe" (
    start "" "%~dp0python\python.exe" "%~dp0Tools\world_nav_probe\run_world_nav.py"
) else (
    echo Bundled Python not found.
    pause
)
