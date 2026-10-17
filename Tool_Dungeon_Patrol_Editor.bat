@echo off
cd /d "%~dp0"
REM Tool — dungeon patrol editor
if exist "%~dp0python\pythonw.exe" (
    start "" "%~dp0python\pythonw.exe" "%~dp0run.py" --dungeon-patrol
) else if exist "%~dp0python\python.exe" (
    start "" "%~dp0python\python.exe" "%~dp0run.py" --dungeon-patrol
) else (
    echo Bundled Python not found.
    pause
)
