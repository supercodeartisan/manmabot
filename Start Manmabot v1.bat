@echo off
cd /d "%~dp0"
REM The app self-elevates (one UAC), then starts signeddrv / WinNotify.
if exist "%~dp0python\pythonw.exe" (
    start "" "%~dp0python\pythonw.exe" "%~dp0run.py"
) else (
    start "" "%~dp0ManmabotV1.exe"
)
