@echo off
cd /d "%~dp0"
if exist "C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat" (
  call "C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
) else if exist "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" (
  call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
) else (
  call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul
)
if not exist "..\entities\signeddrv_client.obj" (
  cl /c /O2 /nologo /D_CRT_SECURE_NO_WARNINGS /I..\lc930\core ..\lc930\core\signeddrv_client.c /Fo:..\entities\signeddrv_client.obj
  if errorlevel 1 exit /b 1
)
cl /LD /DSHOP_LISTEN_DLL shop_listen.c ..\entities\signeddrv_client.obj /O2 /Fe:..\..\..\dll\shop_listen.dll /I. /I..\entities /nologo /link user32.lib
if errorlevel 1 exit /b 1
echo BUILD OK shop_listen.dll
