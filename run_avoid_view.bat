@echo off
setlocal
cd /d "%~dp0"
set PYTHONPATH=%CD%\Engine;%CD%\Tools
"%CD%\python\python.exe" Tools\avoid_view\run_avoid_view.py
exit /b %ERRORLEVEL%
