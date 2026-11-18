@echo off
cd /d "%~dp0"
if exist "C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat" (
  call "C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
) else (
  call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul
)
cl /c signeddrv_client.c /O2 /nologo /I. /D_CRT_SECURE_NO_WARNINGS
if errorlevel 1 exit /b 1
cl /LD /DATTACKS_ME_DLL attacks_me.c signeddrv_client.obj /O2 /Fe:..\..\..\dll\attacks_me.dll /I. /D_CRT_SECURE_NO_WARNINGS /nologo /link user32.lib
if errorlevel 1 exit /b 1
cl attacks_me.c signeddrv_client.obj /O2 /Fe:..\..\..\bin\attacks_me.exe /I. /D_CRT_SECURE_NO_WARNINGS /nologo /link user32.lib
if errorlevel 1 exit /b 1
echo BUILD OK
dir /b ..\..\..\dll\attacks_me.dll ..\..\..\bin\attacks_me.exe
