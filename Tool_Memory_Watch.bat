@echo off
cd /d "%~dp0"
REM Tool — live memory watch (first read + on-change; no bot control)
if exist "%~dp0python\pythonw.exe" (
    start "" "%~dp0python\pythonw.exe" "%~dp0Tools\memory_watch\run_memory_watch.py"
) else if exist "%~dp0python\python.exe" (
    start "" "%~dp0python\python.exe" "%~dp0Tools\memory_watch\run_memory_watch.py"
) else (
    echo Bundled Python not found.
    pause
)
