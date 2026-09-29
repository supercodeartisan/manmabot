@echo off
setlocal
cd /d "%~dp0"
set "HERE=%~dp0"
set "PY="

if exist "%HERE%pythonw.exe" set "PY=%HERE%pythonw.exe"
if not defined PY if exist "%HERE%python.exe" set "PY=%HERE%python.exe"
if not defined PY if exist "%HERE%python\pythonw.exe" set "PY=%HERE%python\pythonw.exe"
if not defined PY if exist "%HERE%python\python.exe" set "PY=%HERE%python\python.exe"
if not defined PY if exist "%HERE%..\python\pythonw.exe" set "PY=%HERE%..\python\pythonw.exe"
if not defined PY if exist "%HERE%..\python\python.exe" set "PY=%HERE%..\python\python.exe"
if not defined PY if exist "%HERE%..\..\python\pythonw.exe" set "PY=%HERE%..\..\python\pythonw.exe"
if not defined PY if exist "%HERE%..\..\python\python.exe" set "PY=%HERE%..\..\python\python.exe"
if not defined PY if exist "%HERE%..\..\..\python\pythonw.exe" set "PY=%HERE%..\..\..\python\pythonw.exe"
if not defined PY if exist "%HERE%..\..\..\python\python.exe" set "PY=%HERE%..\..\..\python\python.exe"

if defined PY (
    start "" "%PY%" "%HERE%run.py"
    exit /b 0
)

where pythonw >nul 2>&1
if not errorlevel 1 (
    start "" pythonw "%HERE%run.py"
    exit /b 0
)
where python >nul 2>&1
if not errorlevel 1 (
    start "" python "%HERE%run.py"
    exit /b 0
)

echo Python not found.
echo Install Python 3 with tkinter, then:
echo   pip install -r "%HERE%requirements.txt"
echo   python "%HERE%run.py"
pause
