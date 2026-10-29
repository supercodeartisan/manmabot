@echo off
REM Run AFTER closing ManmabotV1 / pythonw (DLL files are locked while loaded).
cd /d "%~dp0"
copy /Y entities\print_state.new.dll entities\print_state.dll || goto :fail
copy /Y realtime_monitor.new.dll realtime_monitor.dll || goto :fail
copy /Y inventories\inventory_listen.new.dll inventories\inventory_listen.dll || goto :fail
copy /Y Hotbar\hotbar_listen.new.dll Hotbar\hotbar_listen.dll || goto :fail
copy /Y NPC_conv\shop_listen.new.dll NPC_conv\shop_listen.dll || goto :fail
echo INSTALLED 9.30 DLLs
exit /b 0
:fail
echo FAILED — close ManmabotV1.exe / pythonw.exe and re-run this bat.
exit /b 1
