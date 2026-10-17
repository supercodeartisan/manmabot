@echo off
setlocal
cd /d "%~dp0"
set PYTHONPATH=%CD%\Engine;%CD%\Tools
"%CD%\python\python.exe" Tools\ti_edge_nav\run_ti_edge_nav.py
exit /b %ERRORLEVEL%
