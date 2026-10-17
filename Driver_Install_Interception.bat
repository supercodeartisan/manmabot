@echo off
cd /d "%~dp0"
REM Driver — install Interception input filter (admin)
call "%~dp0Drivers\install-interception.bat" %*
