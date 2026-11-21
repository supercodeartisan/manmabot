@echo off
cd /d "%~dp0"
if exist "C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat" (
  call "C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
) else if exist "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" (
  call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
) else (
  call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul
)

if not exist "entities\signeddrv_client.obj" (
  echo signeddrv_client.obj missing
  exit /b 1
)

pushd entities
cl /LD /DPRINT_STATE_DLL print_state.c signeddrv_client.obj /O2 /Fe:print_state.new.dll /I. /D_CRT_SECURE_NO_WARNINGS /nologo /link user32.lib
if errorlevel 1 exit /b 1
popd

cl /LD /DREALTIME_MONITOR_DLL realtime_monitor_full.c entities\signeddrv_client.obj /O2 /Fe:realtime_monitor.new.dll /I. /Ientities /D_CRT_SECURE_NO_WARNINGS /nologo /link user32.lib
if errorlevel 1 exit /b 1

pushd inventories
cl /LD /DINVENTORY_LISTEN_DLL inventory_listen.c ..\entities\signeddrv_client.obj /O2 /Fe:inventory_listen.new.dll /I. /I..\entities /nologo /link user32.lib
if errorlevel 1 exit /b 1
popd

pushd Hotbar
cl /LD /DHOTBAR_LISTEN_DLL hotbar_listen.c nametable.c ..\entities\signeddrv_client.obj /O2 /Fe:hotbar_listen.new.dll /I. /I..\entities /nologo /link user32.lib
if errorlevel 1 exit /b 1
popd

pushd NPC_conv
cl /LD /DSHOP_LISTEN_DLL shop_listen.c ..\entities\signeddrv_client.obj /O2 /Fe:shop_listen.new.dll /I. /I..\entities /nologo /link user32.lib
if errorlevel 1 exit /b 1
popd

pushd lc930
call build_new_readers.bat
if errorlevel 1 exit /b 1
popd

echo ALL NEW DLLS BUILT
dir /b entities\print_state.new.dll realtime_monitor.new.dll inventories\inventory_listen.new.dll Hotbar\hotbar_listen.new.dll NPC_conv\shop_listen.new.dll lc930\buff\buff_listen.dll lc930\uidialog\uidialog_listen.dll
