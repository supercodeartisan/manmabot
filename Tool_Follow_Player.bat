@echo off
cd /d "%~dp0"
REM Tool — follow a nearby player, hunt only while close
if exist "%~dp0python\pythonw.exe" (
    start "" "%~dp0python\pythonw.exe" "%~dp0run.py" --follow-player
) else if exist "%~dp0python\python.exe" (
    start "" "%~dp0python\python.exe" "%~dp0run.py" --follow-player
) else (
    echo Bundled Python not found.
    pause
)
