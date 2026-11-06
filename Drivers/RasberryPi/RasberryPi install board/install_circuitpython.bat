@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set "SCRIPT=%~dp0install_circuitpython.py"
if not exist "%SCRIPT%" (
    echo [ERROR] install_circuitpython.py not found.
    pause
    exit /b 1
)

set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY (
    where py >nul 2>nul && set "PY=py"
)
if not defined PY (
    echo [ERROR] Python not found. https://www.python.org/downloads/
    pause
    exit /b 1
)

if "%~1"=="" (
    %PY% "%SCRIPT%" --ui
) else (
    %PY% "%SCRIPT%" %*
)

echo.
pause
