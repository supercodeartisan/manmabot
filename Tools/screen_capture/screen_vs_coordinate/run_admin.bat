@echo off
setlocal
cd /d "%~dp0"
set "HERE=%~dp0"
set "PY="

if exist "%HERE%python.exe" set "PY=%HERE%python.exe"
if not defined PY if exist "%HERE%pythonw.exe" set "PY=%HERE%pythonw.exe"
if not defined PY if exist "%HERE%python\python.exe" set "PY=%HERE%python\python.exe"
if not defined PY if exist "%HERE%python\pythonw.exe" set "PY=%HERE%python\pythonw.exe"
if not defined PY if exist "%HERE%..\python\python.exe" set "PY=%HERE%..\python\python.exe"
if not defined PY if exist "%HERE%..\..\python\python.exe" set "PY=%HERE%..\..\python\python.exe"
if not defined PY if exist "%HERE%..\..\..\python\python.exe" set "PY=%HERE%..\..\..\python\python.exe"

if not defined PY (
    where python >nul 2>&1
    if not errorlevel 1 set "PY=python"
)
if not defined PY (
    echo Python not found.
    pause
    exit /b 1
)

"%PY%" "%HERE%elevate.py"
