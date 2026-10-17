@echo off
setlocal
cd /d "%~dp0.."
set PYTHONPATH=%CD%\Engine;%CD%
python Tools\nav\build_nav_prebuild.py %*
exit /b %ERRORLEVEL%
