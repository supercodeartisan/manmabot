@echo off
cd /d "%~dp0"
REM Loads Engine\data\world_nav\providers\20_hubs_talking_scroll.json by default.
REM Save to project writes click + scroll_times back into that file.
python plan_editor.py
if errorlevel 1 pause
