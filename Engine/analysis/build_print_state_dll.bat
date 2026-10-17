@echo off
cd /d "%~dp0"
if exist "C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat" (
  call "C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
) else if exist "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" (
  call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
) else (
  call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul
)

pushd entities
if not exist signeddrv_client.obj (
  cl /c /O2 /nologo /D_CRT_SECURE_NO_WARNINGS /I. /I..\live_tracking ..\live_tracking\signeddrv_client.c /Fo:signeddrv_client.obj
  if errorlevel 1 exit /b 1
)
cl /LD /DPRINT_STATE_DLL print_state.c signeddrv_client.obj /O2 /Fe:print_state.new.dll /I. /D_CRT_SECURE_NO_WARNINGS /nologo /link user32.lib
if errorlevel 1 exit /b 1
copy /Y print_state.new.dll print_state.dll
if errorlevel 1 (
  echo LOCKED — close Manmabot then: copy /Y entities\print_state.new.dll entities\print_state.dll
  popd
  exit /b 1
)
popd
echo print_state.dll installed
dir /b entities\print_state.dll entities\print_state.new.dll entities\print_state.exe
