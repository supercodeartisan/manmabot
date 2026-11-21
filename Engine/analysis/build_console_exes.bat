@echo off
cd /d "%~dp0"
if exist "C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat" (
  call "C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
) else if exist "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" (
  call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
) else (
  call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul
)

echo === signeddrv_client.obj ===
pushd entities
cl /c /O2 /nologo /D_CRT_SECURE_NO_WARNINGS /I. /I..\live_tracking ..\live_tracking\signeddrv_client.c /Fo:signeddrv_client.obj
if errorlevel 1 exit /b 1

echo === print_state.exe ===
cl print_state.c signeddrv_client.obj /O2 /Fe:print_state.exe /I. /D_CRT_SECURE_NO_WARNINGS /nologo /link user32.lib
if errorlevel 1 exit /b 1
popd

echo === inventory_listen.exe ===
pushd inventories
cl inventory_listen.c ..\entities\signeddrv_client.obj /O2 /Fe:inventory_listen.exe /I. /I..\entities /D_CRT_SECURE_NO_WARNINGS /nologo /link user32.lib
if errorlevel 1 exit /b 1
popd

echo === hotbar_listen.exe ===
pushd Hotbar
cl hotbar_listen.c nametable.c ..\entities\signeddrv_client.obj /O2 /Fe:hotbar_listen.exe /I. /I..\entities /D_CRT_SECURE_NO_WARNINGS /nologo /link user32.lib
if errorlevel 1 exit /b 1
popd

echo === shop_listen.exe ===
pushd NPC_conv
cl shop_listen.c ..\entities\signeddrv_client.obj /O2 /Fe:shop_listen.exe /I. /I..\entities /D_CRT_SECURE_NO_WARNINGS /nologo /link user32.lib
if errorlevel 1 exit /b 1
popd

echo ALL CONSOLE EXES BUILT
dir /b entities\print_state.exe inventories\inventory_listen.exe Hotbar\hotbar_listen.exe NPC_conv\shop_listen.exe
