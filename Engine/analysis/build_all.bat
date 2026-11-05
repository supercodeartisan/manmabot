@echo off
REM ============================================================================
REM  build_all.bat - rebuild all 10_7_modify tools (module + probes)
REM  Use when shared core (lcore.h / lcreg.h / signeddrv_client.*) changes,
REM  to keep src/exe/registry/docs consistent (avoid STALE exe).
REM  NOTE: ASCII only. Do NOT put non-ASCII here (cmd codepage 936 breaks it).
REM
REM  MODES
REM    build_all.bat          -> write bin\*.exe (release build; changes exe hashes)
REM    build_all.bat scratch  -> write %TEMP%\lc_build_scratch\*.exe and leave bin\
REM                              alone, so check_4way.ps1 keeps its CHANGELOG hash
REM                              match. Use this to verify the toolchain.
REM ============================================================================
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul
cd /d %~dp0

REM --- output directory: bin (default) or scratch (non-destructive check) ---
REM   NOTE: no ( ) block here. %VAR% inside a block expands at parse time,
REM   which would test the OLD value and could delete bin\ by mistake.
set "OUTDIR=bin"
if /I "%~1"=="scratch" set "OUTDIR=%TEMP%\lc_build_scratch"
if /I "%~1"=="scratch" if exist "%TEMP%\lc_build_scratch" rmdir /s /q "%TEMP%\lc_build_scratch"
if not exist "%OUTDIR%" mkdir "%OUTDIR%"
echo [mode] output = %OUTDIR%

echo ============================================================
echo  10_7_modify build all
echo ============================================================

echo [1/5] charread
cl /utf-8 src\charread\charread_930.c core\signeddrv_client.c /O2 /GS- /Fe:%OUTDIR%\charread_930.exe /Icore /D_CRT_SECURE_NO_WARNINGS /nologo
if errorlevel 1 goto :fail

echo [2/5] enttrack
cl /utf-8 src\enttrack\enttrack_930.c core\signeddrv_client.c /O2 /GS- /Fe:%OUTDIR%\enttrack_930.exe /Icore /D_CRT_SECURE_NO_WARNINGS /nologo user32.lib
if errorlevel 1 goto :fail

echo [3/5] etview
cl /utf-8 src\etview\etview_930.c core\signeddrv_client.c /O2 /GS- /Fe:%OUTDIR%\etview_930.exe /Icore /D_CRT_SECURE_NO_WARNINGS /nologo user32.lib gdi32.lib
if errorlevel 1 goto :fail
cl /utf-8 src\etview_own\etview_own_930.c core\signeddrv_client.c /O2 /GS- /Fe:%OUTDIR%\etview_own_930.exe /Icore /D_CRT_SECURE_NO_WARNINGS /nologo user32.lib gdi32.lib
if errorlevel 1 goto :fail

echo [4/5] buff + map
cl /utf-8 src\buff\buff_930.c core\signeddrv_client.c /O2 /GS- /Fe:%OUTDIR%\buff_930.exe /Icore /D_CRT_SECURE_NO_WARNINGS /nologo
if errorlevel 1 goto :fail
cl /utf-8 src\map\map_930.c core\signeddrv_client.c /O2 /GS- /Fe:%OUTDIR%\map_930.exe /Icore /D_CRT_SECURE_NO_WARNINGS /nologo
if errorlevel 1 goto :fail
cl /utf-8 src\map\ask_930.c core\signeddrv_client.c /O2 /GS- /Fe:%OUTDIR%\ask_930.exe /Icore /D_CRT_SECURE_NO_WARNINGS /nologo
if errorlevel 1 goto :fail
cl /utf-8 src\inventory\inventory_930.c core\signeddrv_client.c /O2 /GS- /Fe:%OUTDIR%\inventory_930.exe /Icore /D_CRT_SECURE_NO_WARNINGS /nologo
if errorlevel 1 goto :fail
cl /utf-8 src\storage\storage_930.c core\signeddrv_client.c /O2 /GS- /Fe:%OUTDIR%\storage_930.exe /Icore /D_CRT_SECURE_NO_WARNINGS /nologo
if errorlevel 1 goto :fail
cl /utf-8 src\chat\chat_930.c core\signeddrv_client.c /O2 /GS- /Fe:%OUTDIR%\chat_930.exe /Icore /D_CRT_SECURE_NO_WARNINGS /nologo
if errorlevel 1 goto :fail
cl /utf-8 src\hotbar\hotbar_930.c core\signeddrv_client.c /O2 /GS- /Fe:%OUTDIR%\hotbar_930.exe /Icore /D_CRT_SECURE_NO_WARNINGS /nologo
if errorlevel 1 goto :fail
cl /utf-8 src\shop\shop_930.c core\signeddrv_client.c /O2 /GS- /Fe:%OUTDIR%\shop_930.exe /Icore /D_CRT_SECURE_NO_WARNINGS /nologo
if errorlevel 1 goto :fail
cl /utf-8 src\uidialogmon\uidialogmon_930.c core\signeddrv_client.c /O2 /GS- /Fe:%OUTDIR%\uidialogmon_930.exe /Icore /D_CRT_SECURE_NO_WARNINGS /nologo
if errorlevel 1 goto :fail
cl /utf-8 src\lasthit\lasthit_930.c core\signeddrv_client.c /O2 /GS- /Fe:%OUTDIR%\lasthit_930.exe /Icore /D_CRT_SECURE_NO_WARNINGS /nologo
if errorlevel 1 goto :fail
cl /utf-8 src\realtime_buff\realtime_buff_930.c core\signeddrv_client.c /O2 /GS- /Fe:%OUTDIR%\realtime_buff_930.exe /Icore /D_CRT_SECURE_NO_WARNINGS /nologo
if errorlevel 1 goto :fail
cl /utf-8 src\party\party_1009.c core\signeddrv_client.c /O2 /GS- /Fe:%OUTDIR%\party_1009.exe /Icore /Isrc\party /D_CRT_SECURE_NO_WARNINGS /nologo
if errorlevel 1 goto :fail
cl /utf-8 src\realtime_party\realtime_party_1009.c core\signeddrv_client.c /O2 /GS- /Fe:%OUTDIR%\realtime_party_1009.exe /Icore /Isrc\party /D_CRT_SECURE_NO_WARNINGS /nologo
if errorlevel 1 goto :fail
cl /utf-8 src\storage\storelist_930.c core\signeddrv_client.c /O2 /GS- /Fe:%OUTDIR%\storelist_930.exe /Icore /D_CRT_SECURE_NO_WARNINGS /nologo
if errorlevel 1 goto :fail

echo [4b] 추가 모듈 (ui/창/문/연구) — 신규 모듈은 여기에 추가한다
cl /utf-8 src\bodyact\bodyact_930.c core\signeddrv_client.c /O2 /GS- /Fe:%OUTDIR%\bodyact_930.exe /Icore /D_CRT_SECURE_NO_WARNINGS /nologo user32.lib
if errorlevel 1 goto :fail
cl /utf-8 src\bodyactview\bodyactview_930.c core\signeddrv_client.c /O2 /GS- /Fe:%OUTDIR%\bodyactview_930.exe /Icore /D_CRT_SECURE_NO_WARNINGS /nologo user32.lib gdi32.lib winmm.lib
if errorlevel 1 goto :fail
cl /utf-8 src\chatwin\chatwin_930.c core\signeddrv_client.c /O2 /GS- /Fe:%OUTDIR%\chatwin_930.exe /Icore /D_CRT_SECURE_NO_WARNINGS /nologo
if errorlevel 1 goto :fail
cl /utf-8 src\chatmon\chatmon_930.c core\signeddrv_client.c /O2 /GS- /Fe:%OUTDIR%\chatmon_930.exe /Icore /D_CRT_SECURE_NO_WARNINGS /nologo
if errorlevel 1 goto :fail
cl /utf-8 src\hchurn\hchurn_930.c core\signeddrv_client.c /O2 /GS- /Fe:%OUTDIR%\hchurn_930.exe /Icore /D_CRT_SECURE_NO_WARNINGS /nologo user32.lib winmm.lib
if errorlevel 1 goto :fail
cl /utf-8 src\prerender\prerender_930.c core\signeddrv_client.c /O2 /GS- /Fe:%OUTDIR%\prerender_930.exe /Icore /D_CRT_SECURE_NO_WARNINGS /nologo user32.lib winmm.lib
if errorlevel 1 goto :fail
cl /utf-8 src\storewin\storewin_930.c core\signeddrv_client.c /O2 /GS- /Fe:%OUTDIR%\storewin_930.exe /Icore /D_CRT_SECURE_NO_WARNINGS /nologo
if errorlevel 1 goto :fail
cl /utf-8 src\partyhud\partyhud_930.c core\signeddrv_client.c /O2 /GS- /Fe:%OUTDIR%\partyhud_930.exe /Icore /D_CRT_SECURE_NO_WARNINGS /nologo user32.lib
if errorlevel 1 goto :fail
cl /utf-8 src\partycap\partycap_930.c core\signeddrv_client.c /O2 /GS- /Fe:%OUTDIR%\partycap_930.exe /Icore /D_CRT_SECURE_NO_WARNINGS /nologo user32.lib gdi32.lib
if errorlevel 1 goto :fail
cl /utf-8 src\winmon\winmon_930.c core\signeddrv_client.c /O2 /GS- /Fe:%OUTDIR%\winmon_930.exe /Icore /D_CRT_SECURE_NO_WARNINGS /nologo
if errorlevel 1 goto :fail
cl /utf-8 src\doorwatch\doorwatch_930.c core\signeddrv_client.c /O2 /GS- /Fe:%OUTDIR%\doorwatch_930.exe /Icore /D_CRT_SECURE_NO_WARNINGS /nologo
if errorlevel 1 goto :fail
REM   (src\api\*.c 는 exe 가 아니라 lcapi 라이브러리이므로 여기에 넣지 않는다)


echo [5/5] DLL kit
call build_bot_modules.bat
if errorlevel 1 goto :fail
del /q *.obj 2>nul
echo.
echo [OK] build all complete.  output = %OUTDIR%
exit /b 0
:fail
echo.
echo [FAIL] build error. see log above.
exit /b 1
