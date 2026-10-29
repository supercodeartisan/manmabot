@echo off
cd /d "%~dp0"
if exist "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" (
  call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul
) else if exist "C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat" (
  call "C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
) else if exist "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" (
  call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
) else (
  echo ERROR: vcvars64.bat not found. Install VS 2022 Build Tools with VCTools.
  exit /b 1
)

cl /c core\signeddrv_client.c /O2 /Fo:core\signeddrv_client.obj /Icore /D_CRT_SECURE_NO_WARNINGS /nologo
if errorlevel 1 exit /b 1

cl /LD /DPARTY_LISTEN_DLL party_listen.c core\signeddrv_client.obj /O2 /Fe:party_listen.dll /Icore /D_CRT_SECURE_NO_WARNINGS /nologo /link user32.lib
if errorlevel 1 (
  echo LIVE party_listen.dll locked — building party_listen_build.dll
  cl /LD /DPARTY_LISTEN_DLL party_listen.c core\signeddrv_client.obj /O2 /Fe:party_listen_build.dll /Icore /D_CRT_SECURE_NO_WARNINGS /nologo /link user32.lib
  if errorlevel 1 exit /b 1
)

echo BUILD OK
