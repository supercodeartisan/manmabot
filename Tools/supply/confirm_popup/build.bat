@echo off
setlocal
cd /d "%~dp0"

if exist "C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat" (
  call "C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
) else if exist "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" (
  call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul
) else (
  echo ERROR: vcvars64.bat not found.
  exit /b 1
)

set CORE=%~dp0..\..\..\Engine\analysis\src\listen\lc930\core
if not exist "%CORE%\lcore.h" (
  echo ERROR: Engine lc930 core not found at %CORE%
  exit /b 1
)

if not exist "%CORE%\signeddrv_client.obj" (
  cl /c "%CORE%\signeddrv_client.c" /O2 /Fo:"%CORE%\signeddrv_client.obj" /I"%CORE%" /D_CRT_SECURE_NO_WARNINGS /nologo
  if errorlevel 1 exit /b 1
)

cl /LD confirm_listen.c "%CORE%\signeddrv_client.obj" /O2 /Fe:confirm_listen.dll /I"%CORE%" /D_CRT_SECURE_NO_WARNINGS /nologo /link user32.lib
if errorlevel 1 (
  echo LIVE locked — building confirm_listen_build.dll
  cl /LD confirm_listen.c "%CORE%\signeddrv_client.obj" /O2 /Fe:confirm_listen_build.dll /I"%CORE%" /D_CRT_SECURE_NO_WARNINGS /nologo /link user32.lib
  if errorlevel 1 exit /b 1
)

del /q *.obj 2>nul
del /q *.exp 2>nul
echo BUILD_OK
dir /b confirm_listen*.dll
