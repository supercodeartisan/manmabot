@echo off
cd /d "%~dp0"
REM Bot — main operator console (schedule / farm)
if exist "%~dp0python\pythonw.exe" (
    start "" "%~dp0python\pythonw.exe" "%~dp0run.py"
) else if exist "%~dp0ZF.exe" (
    start "" "%~dp0ZF.exe"
) else if exist "%~dp0ManmabotV1.exe" (
    start "" "%~dp0ManmabotV1.exe"
) else (
    echo Bundled Python / ZF.exe not found.
    pause
)
