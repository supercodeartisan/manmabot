@echo off
cd /d "%~dp0"
REM Tool — memory read bench (sensor timing; no bot control)
if exist "%~dp0python\pythonw.exe" (
    start "" "%~dp0python\pythonw.exe" "%~dp0Tools\memory_bench\run_memory_bench.py"
) else if exist "%~dp0python\python.exe" (
    start "" "%~dp0python\python.exe" "%~dp0Tools\memory_bench\run_memory_bench.py"
) else (
    echo Bundled Python not found.
    pause
)
