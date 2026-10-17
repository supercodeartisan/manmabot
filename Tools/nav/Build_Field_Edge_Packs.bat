@echo off
setlocal
cd /d "%~dp0..\.."
set PYTHONPATH=%CD%\Engine;%CD%\Tools
"%CD%\python\python.exe" Tools\nav\build_field_edge_packs.py %*
exit /b %ERRORLEVEL%
