@echo off
cd /d "%~dp0"
REM Bot data editor — NPC click_offset_uv → Engine/data/npc_behaviors.yaml
if exist "%~dp0python\pythonw.exe" (
    start "" "%~dp0python\pythonw.exe" "%~dp0Tools\bot_data_editors\run_npc_click_offset.py"
) else if exist "%~dp0python\python.exe" (
    start "" "%~dp0python\python.exe" "%~dp0Tools\bot_data_editors\run_npc_click_offset.py"
) else (
    echo Bundled Python not found.
    pause
)
