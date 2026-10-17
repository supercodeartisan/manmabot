@echo off
cd /d "%~dp0"
REM Bot — debug player UI
if exist "%~dp0python\pythonw.exe" (
    start "" "%~dp0python\pythonw.exe" "%~dp0run.py" --debug
) else if exist "%~dp0python\python.exe" (
    start "" "%~dp0python\python.exe" "%~dp0run.py" --debug
) else (
    echo Bundled Python not found.
    pause
)
