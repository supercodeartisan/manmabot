@echo off
cd /d "%~dp0"
if exist "C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat" (
  call "C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
) else if exist "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" (
  call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
) else (
  call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul
)
cl /c signeddrv_client.c /O2 /nologo /I. /D_CRT_SECURE_NO_WARNINGS
if errorlevel 1 exit /b 1
cl probe_my_anim.c signeddrv_client.obj /O2 /Fe:probe_my_anim.exe /I. /D_CRT_SECURE_NO_WARNINGS /nologo /link user32.lib
if errorlevel 1 exit /b 1
echo BUILD OK
dir /b probe_my_anim.exe
