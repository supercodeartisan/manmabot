@echo off
rem Build the memory-team module DLLs the bot loads from analysis\dll.
setlocal
cd /d "%~dp0"
if not exist dll mkdir dll
if not exist "%VCINSTALLDIR%" (
  call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
)
set FAIL=0
for %%M in (charread map enttrack bodyact inventory hotbar shop buff uidialogmon party) do (
  echo == %%M
  if not exist dll\%%M mkdir dll\%%M
  cl /nologo /O2 /MD /LD /utf-8 /Icore /D_CRT_SECURE_NO_WARNINGS src\api\%%M_api.c core\lcapi_adapter.c core\signeddrv_client.c /Fodll\%%M\ /Fe:dll\%%M.dll /link user32.lib
  if errorlevel 1 set FAIL=1
)
if "%FAIL%"=="1" (
  echo BUILD FAILED
  exit /b 1
)
echo BUILD OK
exit /b 0
