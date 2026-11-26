@echo off
REM Build UIMessage probe (CommonMessageSubsystem) into analysis\bin.
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul
cd /d %~dp0
if not exist bin mkdir bin
cl /utf-8 probes\uimsg_1021.c core\signeddrv_client.c /O2 /GS- /Fe:bin\uimsg_1021.exe /Icore /D_CRT_SECURE_NO_WARNINGS /nologo
